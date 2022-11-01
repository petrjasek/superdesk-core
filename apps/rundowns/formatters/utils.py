from typing import List
from datetime import datetime, timedelta

from superdesk.text_utils import get_text
from superdesk.editor_utils import get_field_content_state

from .. import types


def to_string(item, key) -> str:
    return item.get(key) or ""


def item_title(show: types.IShow, rundown: types.IRundown, item: types.IRundownItem) -> str:
    return "-".join(
        filter(
            None,
            [
                to_string(item, "item_type").upper(),
                show.get("shortcode", "").upper(),
                (item.get("title") or "").upper(),
            ],
        )
    )


def format_duration(duration) -> str:
    if duration:
        delta = timedelta(seconds=int(duration))
        return (datetime(year=1, month=1, day=1) + delta).strftime("%H:%M:%S")
    return ""


def item_table_data(show: types.IShow, rundown: types.IRundown, item: types.IRundownItem, order: int) -> List[str]:
    return [
        str(order),
        to_string(item, "item_type").upper(),
        item_title(show, rundown, item),
        "Tone" if item.get("live_sound") else "OFF",
        item.get("additional_notes") or "",
        format_duration(item.get("duration")),
    ]
