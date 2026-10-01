"""Vector index of published articles, used for semantic and hybrid search.

Articles are split into chunks, embedded by an OpenAI compatible service configured with
``AI_EMBEDDINGS_URL`` and stored in ``AI_VECTOR_INDEX`` on ``AI_VECTOR_ELASTICSEARCH_URL``.

Works with Elasticsearch 7.x and 8.x. On 8.4+ vectors are searched with approximate kNN, on older
versions with a brute force ``script_score``. Keyword and vector results are merged with reciprocal
rank fusion here rather than in Elasticsearch, as its RRF needs 8.9+ and a paid license.
"""

from typing import Any

from elasticsearch import AsyncElasticsearch, NotFoundError
from elasticsearch.helpers import async_bulk

from superdesk.resource_fields import ID_FIELD
from superdesk.text_utils import get_text

from .config import config as ai_config
from .providers.openai_compatible import OpenAICompatibleClient

VECTOR_FIELD = "text_vector"
RRF_K = 60

_server_versions: dict[str, tuple[int, int]] = {}


def is_enabled() -> bool:
    return bool(ai_config.embeddings_url)


def split_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    step = chunk_size - chunk_overlap
    return [" ".join(words[i : i + chunk_size]) for i in range(0, max(len(words) - chunk_overlap, 1), step)]


def get_item_text(item: dict[str, Any]) -> str:
    return " ".join(
        get_text(item[field], content="html", lf_on_block=True)
        for field in ("abstract", "body_html")
        if item.get(field)
    )


class VectorIndex:
    def __init__(self) -> None:
        self.url = ai_config.vector_elasticsearch_url
        self.index = ai_config.vector_index
        self.model = ai_config.embeddings_model
        self.es = AsyncElasticsearch([self.url])
        self.embeddings = OpenAICompatibleClient(ai_config.embeddings_url.rstrip("/"))
        self._index_ready = False

    async def __aenter__(self) -> "VectorIndex":
        return self

    async def __aexit__(self, *args) -> None:
        await self.es.close()

    async def get_version(self) -> tuple[int, int]:
        if self.url not in _server_versions:
            info = await self.es.info()
            major, minor = info["version"]["number"].split(".")[:2]
            _server_versions[self.url] = (int(major), int(minor))
        return _server_versions[self.url]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self.embeddings.embed(texts, self.model)

    async def ensure_index(self, dims: int) -> None:
        if self._index_ready:
            return

        if not await self.es.indices.exists(index=self.index):
            vector_mapping: dict[str, Any] = {"type": "dense_vector", "dims": dims}
            if await self.get_version() >= (8, 0):
                vector_mapping.update({"index": True, "similarity": "cosine"})

            await self.es.indices.create(
                index=self.index,
                body={
                    "mappings": {
                        "properties": {
                            "article_id": {"type": "keyword"},
                            "guid": {"type": "keyword"},
                            "title": {"type": "text"},
                            "chunk_index": {"type": "integer"},
                            "chunk_text": {"type": "text"},
                            "language": {"type": "keyword"},
                            "publish_date": {"type": "date"},
                            VECTOR_FIELD: vector_mapping,
                        }
                    }
                },
            )

        self._index_ready = True

    async def get_item_actions(self, item: dict[str, Any], chunk_size: int, chunk_overlap: int) -> list[dict]:
        """Embed an item and return the bulk actions for its chunks, raises ``AIProviderError``"""

        title = item.get("headline") or ""
        chunks = split_text(get_item_text(item), chunk_size, chunk_overlap)
        if not chunks:
            return []

        # title is prefixed so each chunk carries article context
        vectors = await self.embed([f"{title}\n{chunk}" for chunk in chunks])
        publish_date = item.get("firstpublished") or item.get("versioncreated")

        return [
            {
                "_index": self.index,
                "_id": "{}:{}".format(item[ID_FIELD], i),
                "_source": {
                    "article_id": str(item[ID_FIELD]),
                    "guid": item.get("guid"),
                    "title": title,
                    "chunk_index": i,
                    "chunk_text": chunk,
                    "language": item.get("language"),
                    "publish_date": publish_date.isoformat() if publish_date else None,
                    VECTOR_FIELD: vector,
                },
            }
            for i, (chunk, vector) in enumerate(zip(chunks, vectors))
        ]

    async def index_actions(self, article_ids: list[str], actions: list[dict]) -> tuple[int, list]:
        """Replace all chunks of given articles with the new ones"""

        if not actions:
            return 0, []

        await self.ensure_index(len(actions[0]["_source"][VECTOR_FIELD]))
        # removes stale chunks when an updated article now has fewer chunks
        await self.es.delete_by_query(
            index=self.index,
            body={"query": {"terms": {"article_id": article_ids}}},
            refresh=True,
        )
        success, failed = await async_bulk(self.es, actions, raise_on_error=False, stats_only=False)
        return success, failed  # type: ignore[return-value]

    async def search(self, query: str, size: int = 10) -> list[dict[str, Any]]:
        """Hybrid keyword + vector search, raises ``AIProviderError`` when embedding fails"""

        vector = (await self.embed([query]))[0]
        candidates = max(size * 5, 50)

        keyword_hits = await self._search(
            {"query": {"multi_match": {"query": query, "fields": ["title^2", "chunk_text"]}}, "size": candidates}
        )
        vector_hits = await self._search(await self._get_vector_query(vector, candidates))

        scores: dict[str, float] = {}
        sources: dict[str, dict] = {}
        for hits in (keyword_hits, vector_hits):
            for rank, hit in enumerate(hits):
                scores[hit["_id"]] = scores.get(hit["_id"], 0.0) + 1.0 / (RRF_K + rank + 1)
                sources[hit["_id"]] = hit["_source"]

        top = sorted(scores, key=scores.__getitem__, reverse=True)[:size]
        return [{**sources[hit_id], "score": scores[hit_id]} for hit_id in top]

    async def _get_vector_query(self, vector: list[float], candidates: int) -> dict[str, Any]:
        if await self.get_version() >= (8, 4):
            return {
                "knn": {
                    "field": VECTOR_FIELD,
                    "query_vector": vector,
                    "k": candidates,
                    "num_candidates": candidates * 2,
                },
                "size": candidates,
            }

        return {
            "query": {
                "script_score": {
                    "query": {"match_all": {}},
                    "script": {
                        # +1 as scores must not be negative
                        "source": f"cosineSimilarity(params.query_vector, '{VECTOR_FIELD}') + 1.0",
                        "params": {"query_vector": vector},
                    },
                }
            },
            "size": candidates,
        }

    async def _search(self, body: dict[str, Any]) -> list[dict]:
        body["_source"] = {"excludes": [VECTOR_FIELD]}
        try:
            response = await self.es.search(index=self.index, body=body)
        except NotFoundError:
            return []
        return response["hits"]["hits"]
