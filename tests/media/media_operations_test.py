import io
import requests_mock

from superdesk.flask import Flask
from superdesk.media.media_operations import download_file_from_url
from superdesk.tests import AsyncTestCase


class MediaOperationsTestCase(AsyncTestCase):
    async def test_download_file_from_url_relative(self):
        app = Flask(__name__)
        app.config["SERVER_NAME"] = "localhost"
        body = io.BytesIO(b"data")
        async with app.app_context():
            with requests_mock.mock() as mock:
                mock.get("http://localhost/test/foo.jpg", body=body)
                out = download_file_from_url("/test/foo.jpg")
        self.assertEqual(b"data", out[0].read())
