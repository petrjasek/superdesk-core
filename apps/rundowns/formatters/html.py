
from flask import render_template

from . import BaseFormatter

def rundown_item_content(item):
    return "foo<br />bar<br />"

class HtmlFormatter(BaseFormatter):

    def __init__(self, id, name, template):
        self.id = id
        self.name = name
        self.template = template

    def export(self, dest, show, rundown, items):
        dest["content"] = render_template(self.template, show=show, rundown=rundown, items=items)
        dest["content_type"] = "text/html"
