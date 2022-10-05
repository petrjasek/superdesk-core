import datetime
import dateutil.rrule as rrule

from typing import Optional
from flask import current_app as app

from superdesk.utc import utcnow, utc_to_local


def parse_time(timestr: str) -> datetime.time:
    return datetime.time.fromisoformat(timestr).replace(microsecond=0)


def parse_date(datestr: str) -> datetime.date:
    return datetime.date.fromisoformat(datestr)


def combine_date_time(
    date: datetime.date, time: datetime.time, tz: Optional[datetime.tzinfo] = None
) -> datetime.datetime:
    return datetime.datetime(
        year=date.year,
        month=date.month,
        day=date.day,
        hour=time.hour,
        minute=time.minute,
        second=time.second,
        tzinfo=tz if tz is not None else time.tzinfo,
        microsecond=0,
    )


def get_local_date(time: datetime.time, date: Optional[datetime.date] = None) -> datetime.datetime:
    now = utcnow()
    local_date = utc_to_local(app.config["RUNDOWNS_TIMEZONE"], now)
    if date is None:
        date = local_date.date()
    return combine_date_time(date, time, local_date.tzinfo)


def get_next_date(schedule, start_date: datetime.datetime) -> Optional[datetime.datetime]:
    assert start_date.tzinfo is not None, "start_date must be time zone aware"
    if not schedule.get("freq"):
        return None
    freq = schedule.get("freq", "DAILY").upper()
    assert hasattr(rrule, freq), "Unknown frequency {}".format(freq)
    now = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc).replace(microsecond=0)
    dates = list(
        rrule.rrule(
            freq=getattr(rrule, freq),
            interval=schedule.get("interval", 1),
            bymonth=schedule.get("by_month"),
            bymonthday=schedule.get("by_month_day"),
            byweekday=schedule.get("by_day"),
            byweekno=schedule.get("by_week_no"),
            dtstart=start_date.replace(microsecond=0),
            count=10,
        )
    )
    for date in dates:
        if date > now and date > start_date:
            print("DATE", date, start_date)
            return date
    return None
