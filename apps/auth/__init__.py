# -*- coding: utf-8; -*-
#
# This file is part of Superdesk.
#
# Copyright 2013, 2014 Sourcefabric z.u. and contributors.
#
# For the full copyright and license information, please see the
# AUTHORS and LICENSE files distributed with this source code, or
# at https://www.sourcefabric.org/superdesk/license

from typing import Any, Dict, TypedDict
import flask
import logging
from flask_babel import _
from eve.utils import config

import superdesk
from superdesk.errors import SuperdeskApiError
from superdesk.services import BaseService
from superdesk.celery_app import celery
from apps.auth.auth import SuperdeskTokenAuth
from .auth import AuthUsersResource, AuthResource  # noqa
from .sessions import SessionsResource, UserSessionClearResource
from .session_purge import RemoveExpiredSessions
from .service import UserSessionClearService, AuthService

logger = logging.getLogger(__name__)


class AuthUser(TypedDict):
    username: str
    password: str
    is_active: bool
    is_enabled: bool


class Session(TypedDict):
    user: Any
    session_preferences: Dict[str, Any]


auth_users_service = BaseService[AuthUser]("auth_users", backend=superdesk.get_backend())
sessions_service = BaseService[Session]("sessions", backend=superdesk.get_backend())
clear_sessions_service = UserSessionClearService("clear_sessions", backend=superdesk.get_backend())
auth_service = AuthService("auth", backend=superdesk.get_backend())


def init_app(app) -> None:
    app.auth = SuperdeskTokenAuth()  # Overwrite the app default auth

    AuthUsersResource(auth_users_service.datasource, app=app, service=auth_users_service)
    SessionsResource(sessions_service.datasource, app=app, service=sessions_service)
    UserSessionClearResource(clear_sessions_service.datasource, app=app, service=clear_sessions_service)
    AuthResource(auth_service.datasource, app=app, service=auth_service)


@celery.task
def session_purge():
    try:
        RemoveExpiredSessions().run()
    except Exception as ex:
        logger.error(ex)


def get_user(required=False):
    """Get user authenticated for current request.

    :param boolean required: if True and there is no user it will raise an error
    """
    user = flask.g.get("user", {})
    if config.ID_FIELD not in user and required:
        raise SuperdeskApiError.notFoundError(_("Invalid user."))
    return user


def get_user_id(required=False):
    """Get authenticated user id.

    :param boolean required: if True and there is no user it will raise an error
    """
    user = get_user(required)
    return user.get(config.ID_FIELD)


def get_auth():
    """Get authenticated session data."""
    auth = flask.g.get("auth", {})
    return auth


def is_current_user_admin(required=False):
    """Test if current user is administrator.

    :param required: raise an error if required and there is no user context
    """
    user = get_user(required) or {}
    return user.get("user_type", "") == "administrator"


superdesk.command("session:gc", RemoveExpiredSessions())
