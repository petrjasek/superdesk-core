# -*- coding: utf-8; -*-
#
# This file is part of Superdesk.
#
# Copyright 2013, 2021 Sourcefabric z.u. and contributors.
#
# For the full copyright and license information, please see the
# AUTHORS and LICENSE files distributed with this source code, or
# at https://www.sourcefabric.org/superdesk/license

from typing import Dict, Any
from collections.abc import Iterator

from superdesk.publish import register_transmitter_file_provider, registered_transmitters, TransmitterFileEntry


def parse_attachments(media: Dict[str, TransmitterFileEntry], item: Dict[str, Any]):
    for attachment in item.get("attachments") or []:
        media.update(
            {
                attachment["media"]: TransmitterFileEntry(
                    media=attachment["media"], mimetype=attachment["mimetype"], resource="attachments"
                )
            }
        )


def iter_attachment_sources(transmitter_name: str, item: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    yield item
    if any(
        (transmitter.NAME or delivery_type) == transmitter_name
        and getattr(transmitter, "include_associated_attachments", False)
        for delivery_type, transmitter in registered_transmitters.items()
    ):
        for assoc in (item.get("associations") or {}).values():
            if assoc is None:
                continue
            yield assoc
            for assoc2 in (assoc.get("associations") or {}).values():
                if assoc2 is None:
                    continue
                yield assoc2


def get_attachment_files_for_transmission(
    transmitter_name: str, item: Dict[str, Any]
) -> Dict[str, TransmitterFileEntry]:
    media: Dict[str, TransmitterFileEntry] = {}
    for source in iter_attachment_sources(transmitter_name, item):
        parse_attachments(media, source)

    return media


register_transmitter_file_provider(get_attachment_files_for_transmission)
