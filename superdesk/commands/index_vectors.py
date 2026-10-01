# -*- coding: utf-8; -*-
#
# This file is part of Superdesk.
#
# Copyright 2026 Sourcefabric z.u. and contributors.
#
# For the full copyright and license information, please see the
# AUTHORS and LICENSE files distributed with this source code, or
# at https://www.sourcefabric.org/superdesk/license

import time
from datetime import datetime
from typing import Any

import click
import pymongo

from superdesk.ai import vectors
from superdesk.ai.errors import AIProviderError
from superdesk.core import get_current_async_app
from superdesk.metadata.item import CONTENT_STATE, CONTENT_TYPE, ITEM_STATE, ITEM_TYPE
from superdesk.resource_fields import ID_FIELD

from .async_cli import cli


@cli.command("app:index_vectors")
@click.option("--page-size", "-p", default=100, show_default=True, type=int)
@click.option("--chunk-size", default=200, show_default=True, type=int, help="Words per chunk")
@click.option("--chunk-overlap", default=40, show_default=True, type=int, help="Words shared by adjacent chunks")
@click.option("--date", "-d", help="Only items published since date (ISO format)")
async def cli_index_vectors(page_size, chunk_size, chunk_overlap, date):
    """Index published articles into the AI vector index.

    Articles are split into chunks, embedded via ``AI_EMBEDDINGS_URL`` using ``AI_EMBEDDINGS_MODEL``
    and stored in ``AI_VECTOR_INDEX`` on ``AI_VECTOR_ELASTICSEARCH_URL``.

    Example:
    ::

        $ AI_EMBEDDINGS_URL=http://localhost:13305/v1 python manage.py app:index_vectors
        $ python manage.py app:index_vectors --date=2026-01-01

    """
    if chunk_overlap >= chunk_size:
        raise click.BadParameter("--chunk-overlap must be smaller than --chunk-size")
    if not vectors.is_enabled():
        raise SystemExit("Set AI_EMBEDDINGS_URL to enable vector indexing")

    await IndexVectors(chunk_size, chunk_overlap).run(page_size, date)


class IndexVectors:
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    async def run(self, page_size: int, date: str | None = None):
        total_articles, total_chunks = 0, 0
        async with vectors.VectorIndex() as index:
            for items in self.get_published_items(page_size, date):
                start = time.time()
                actions: list[dict[str, Any]] = []
                indexed_ids: list[str] = []
                for item in items:
                    try:
                        actions.extend(await index.get_item_actions(item, self.chunk_size, self.chunk_overlap))
                    except AIProviderError as err:
                        print("Skipping item {}: {}".format(item[ID_FIELD], err.message))
                        continue
                    indexed_ids.append(str(item[ID_FIELD]))
                    total_articles += 1

                success, failed = await index.index_actions(indexed_ids, actions)
                total_chunks += success
                if failed:
                    print("Failed to index chunks: {}".format(failed))

                print(
                    "{} Indexed {} items ({} chunks) in {:.3f} seconds".format(
                        time.strftime("%X %x %Z"), len(items), len(actions), time.time() - start
                    )
                )

            print("Finished: {} articles, {} chunks indexed into {}".format(total_articles, total_chunks, index.index))

    def get_published_items(self, page_size: int, date: str | None):
        db = get_current_async_app().mongo.get_collection("archive")
        query: dict[str, Any] = {
            ITEM_STATE: {"$in": [CONTENT_STATE.PUBLISHED, CONTENT_STATE.CORRECTED]},
            ITEM_TYPE: CONTENT_TYPE.TEXT,
        }
        if date:
            query["firstpublished"] = {"$gte": datetime.fromisoformat(date)}

        last_id = None
        while True:
            if last_id is not None:
                query[ID_FIELD] = {"$gt": last_id}
            items = list(db.find(query, sort=[(ID_FIELD, pymongo.ASCENDING)], limit=page_size))
            if not items:
                break
            last_id = items[-1][ID_FIELD]
            yield items
