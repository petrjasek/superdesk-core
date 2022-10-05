import copy
import logging
import superdesk

from typing import Optional
from flask import current_app as app
from datetime import timedelta

from apps.auth import get_user_id

from . import privileges, types, rundown_items, utils


logger = logging.getLogger(__name__)


class TemplatesResource(superdesk.Resource):
    url = r'/shows/<regex("[a-f0-9]{24}"):show>/templates'
    resource_title = "rundown_templates"
    schema = {
        "title": {
            "type": "string",
            "required": True,
        },
        "show": superdesk.Resource.rel("shows", required=True),
        "description": {
            "type": "string",
            "nullable": True,
        },
        "airtime_time": {
            "type": "time",
            "nullable": True,
        },
        "airtime_date": {
            "type": "date",
            "nullable": True,
        },
        "planned_duration": {
            "type": "number",
            "nullable": True,
        },
        "repeat": {
            "type": "boolean",
        },
        "schedule": {
            "type": "dict",
            "nullable": True,
            "schema": {
                "freq": {
                    "type": "string",
                    "allowed": ["DAILY", "WEEKLY", "MONTHLY", "YEARLY"],
                },
                "interval": {
                    "type": "number",
                    "default": 1,
                },
                "by_month": {
                    "type": "list",
                    "allowed": list(range(1, 13)),
                },
                "by_month_day": {
                    "type": "list",
                    "allowed": list(range(-31, 32)),
                },
                "by_day": {
                    "type": "list",
                    "allowed": list(range(0, 7)),
                },
                "by_week_no": {
                    "type": "list",
                    "allowed": list(range(0, 52)),
                },
            },
        },
        "create_before_seconds": {"type": "number"},
        "title_template": {
            "type": "dict",
            "nullable": True,
            "schema": {
                "prefix": {
                    "type": "string",
                },
                "separator": {
                    "type": "string",
                },
                "date_format": {
                    "type": "string",
                },
            },
        },
        "scheduled_on": {
            "type": "datetime",
            "readonly": True,
            "nullable": True,
        },
        "create_before": {
            "type": "datetime",
            "readonly": True,
            "nullable": True,
        },
        "created_by": superdesk.Resource.rel("users", readonly=True),
        "last_updated_by": superdesk.Resource.rel("users", readonly=True),
        "items": {
            "type": "list",
            "schema": {
                "type": "dict",
                "schema": rundown_items.RundownItemsResource.schema,  # type: ignore
            },
        },
    }

    privileges = {"POST": privileges.RUNDOWNS, "PATCH": privileges.RUNDOWNS, "DELETE": privileges.RUNDOWNS}


def fix_self_link(doc) -> None:
    if "_links" not in doc:
        return
    doc["_links"]["self"]["href"] = "/shows/{show}/templates/{_id}".format(
        show=doc["show"],
        _id=doc["_id"],
    )
    doc["_links"]["self"]["title"] = TemplatesResource.resource_title


def empty_schedule(updates):
    updates["scheduled_on"] = None


class TemplatesService(superdesk.Service):
    def set_scheduled_on(self, updates, original=None):
        """Reset current schedule when schedule config changes."""
        if original is None:
            original = {}

        updated = copy.copy(original)
        updated.update(updates)

        if any([updates.get(field) != original.get(field) for field in ["schedule", "airtime_time", "repeat", "create_before_seconds"]]):
            time = utils.parse_time(updated["airtime_time"]) if updated.get("airtime_time") else None
            date = utils.parse_date(updated["airtime_date"]) if updated.get("airtime_date") else None
            if not time or not updated.get("repeat") or not updated.get("schedule"):
                updates["scheduled_on"] = updates["create_after"] = None
                return
            local_start = utils.get_local_date(time=time, date=date)
            create_after_delta = timedelta(seconds=updated["create_before_seconds"]) if updated.get("create_before_seconds") else (
                timedelta(hours=app.config["RUNDOWNS_SCHEDULE_HOURS"])
            )
            updates["scheduled_on"] = utils.get_next_date(updated["schedule"], local_start)
            updates["create_after"] = updates["scheduled_on"] + create_after_delta if updates.get("scheduled_on") else None
            if not updates["scheduled_on"]:
                logger.warning("Could not schedule next Rundown for template %s", updated["title"])
            else:
                logger.info("Next rundown for template %s scheduled on %s", updated["title"], updates["scheduled_on"].isoformat())

    def on_create(self, docs):
        for doc in docs:
            self.set_scheduled_on(doc)
            doc["created_by"] = get_user_id()

    def on_update(self, updates, original):
        self.set_scheduled_on(updates, original)
        updates["last_updated_by"] = get_user_id()

    def on_created(self, docs):
        super().on_created(docs)
        for doc in docs:
            fix_self_link(doc)

    def on_fetched(self, response):
        super().on_fetched(response)
        for doc in response["_items"]:
            fix_self_link(doc)

    def on_fetched_item(self, doc):
        super().on_fetched_item(doc)
        fix_self_link(doc)

    def find_one(self, req, **lookup) -> Optional[types.IRundownTemplate]:
        template: types.IRundownTemplate = super().find_one(req=req, **lookup)
        return template


templates_service = TemplatesService()
