
import superdesk

from typing import List

from superdesk.utils import ListCursor

from . import privileges, rundowns, rundown_items, formatters, shows


available_services: List[formatters.BaseFormatter] = []


class ExportResource(superdesk.Resource):
    schema = {
        "name": superdesk.Resource.field(type="string", readonly=True),
        "format": {
            "type": "string",
            "required": True,
        },
        "rundown": superdesk.Resource.rel("rundowns", required=True),
        "content": superdesk.Resource.field(type="string", readonly=True),
        "content_type": superdesk.Resource.field(type="string", readonly=True),
    }

    privileges = {
        "POST": privileges.RUNDOWNS,
    }


class ExportService(superdesk.Service):
    def get(self, req, lookup):
        return ListCursor([
            dict(
                _id=service.id,
                name=service.name,
            )
            for service
            in available_services
        ])

    def create(self, docs, **kwargs):
        return [
            self.render(doc)
            for doc in docs
        ]

    def render(self, doc):
        rundown = rundowns.rundowns_service.find_one(req=None, _id=doc["rundown"])
        assert rundown is not None, {"rundown": 1}
        show = shows.shows_service.find_one(req=None, _id=rundown["show"])
        assert show is not None, {"show": 1}
        formatter = next((
            service
            for service in available_services
            if doc["format"] == service.id
        ), None)
        assert formatter, {"formatter": 1}
        items = rundown_items.items_service.get_rundown_items(rundown)
        formatter.export(doc, show, rundown, items)
        return doc["rundown"]


export_service = ExportService()
