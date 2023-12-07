# -*- coding: utf-8; -*-
#
# This file is part of Superdesk.
#
# Copyright 2013, 2014 Sourcefabric z.u. and contributors.
#
# For the full copyright and license information, please see the
# AUTHORS and LICENSE files distributed with this source code, or
# at https://www.sourcefabric.org/superdesk/license

from .media_references import MediaReferencesResource, MediaReference
from .media_editor import MediaEditorService, MediaEditorResource
from superdesk.services import BaseService
import superdesk


media_references_service = BaseService[MediaReference]("media_references", backend=superdesk.get_backend())


def init_app(app) -> None:
    endpoint_name = "media_references"
    MediaReferencesResource(endpoint_name, app=app, service=media_references_service)

    endpoint_name = "media_editor"
    service = MediaEditorService(endpoint_name, backend=superdesk.get_backend())
    MediaEditorResource(endpoint_name, app=app, service=service)

    app.client_config.setdefault("media", {}).update({"renditions": app.config.get("RENDITIONS")})
