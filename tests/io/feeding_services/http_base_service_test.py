from superdesk.io.feeding_services.http_base_service import HTTPFeedingServiceBase
from superdesk.tests import AsyncTestCase


class FeedingServiceWithUrl(HTTPFeedingServiceBase):
    URL = "http://example.com"

    fields = []

    def _update(self, provider, update):
        pass


class TestFeedingService(AsyncTestCase):
    async def test_validate_config_url_null(self):
        service = FeedingServiceWithUrl()
        service.provider = {"config": {"url": None}}
        await service.validate_config()
