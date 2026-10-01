from superdesk.core.config import ConfigModel


class AIConfig(ConfigModel):
    #: Seconds to wait for a response from an AI provider before the request is aborted
    request_timeout: int = 60

    #: Base URL of an OpenAI compatible embeddings service (e.g. Lemonade), vector search is off when empty
    embeddings_url: str = ""
    embeddings_model: str = "nomic-embed-text-v1"

    vector_elasticsearch_url: str = "http://localhost:9200"
    vector_index: str = "superdesk_vectors"


#: Populated by the app from the ``AI_`` prefixed settings when ``superdesk.ai`` is loaded.
#: Reading an attribute before the module is loaded raises a ``RuntimeError``.
config = AIConfig()
