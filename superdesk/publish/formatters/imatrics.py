from superdesk.text_utils import get_text
from .ninjs_formatter import NINJSFormatter


def format_datetime(date):
    return date.isoformat()


class IMatricsFormatter(NINJSFormatter):
    def _transform_to_ninjs(self, article, subscriber, recursive=True):
        return {
            "uuid": article["guid"],
            "createdTimestamp": format_datetime(article["firstcreated"]),
            "latestVersionTimestamp": format_datetime(article["versioncreated"]),
            "publicationTimestamp": format_datetime(article["firstpublished"]),
            "authors": [author["sub_label"] for author in article.get("authors") or []],
            "language": article["language"],
            "pubStatus": True,
            "newspapers": [],
            "channels": [],
            "concepts": [],
            "headline": get_text(article["headline"]),
            "preamble": get_text(article["abstract"], lf_on_block=True).strip(),
            "dateline": article["dateline"]["text"]
            if article.get("dateline") and article["dateline"].get("text")
            else "",
            "body": [
                line
                for line in get_text(article["body_html"], lf_on_block=True).split("\n")
                if line
            ],
        }
