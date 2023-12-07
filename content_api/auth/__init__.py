# -*- coding: utf-8; -*-
#
# This file is part of Superdesk.
#
# Copyright 2013, 2014 Sourcefabric z.u. and contributors.
#
# For the full copyright and license information, please see the
# AUTHORS and LICENSE files distributed with this source code, or
# at https://www.sourcefabric.org/superdesk/license

import superdesk

from apps.auth.auth import AuthData, AuthResource
from superdesk.services import BaseService
from .auth import AuthUsersResource, AuthUser


auth_service = BaseService[AuthData]("auth", backend=superdesk.get_backend())
auth_user_service = BaseService[AuthUser]("auth_user", backend=superdesk.get_backend())


def init_app(app) -> None:
    AuthResource(auth_service.datasource, app=app, service=auth_service)
    AuthUsersResource("auth_user", app=app, service=auth_user_service)
