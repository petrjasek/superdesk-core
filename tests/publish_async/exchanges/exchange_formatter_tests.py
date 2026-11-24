from bson import ObjectId
from copy import deepcopy
from datetime import timedelta
import io
import json
from unittest import mock

from aioresponses import aioresponses
from yarl import URL

from superdesk.tests import TestCase
from superdesk.utc import utcnow
from superdesk.types import (
    SubscribersResource,
    SubscriberType,
    SubscriberDestination,
    PublishRequest,
    PublishRequestResponse,
    PublishQueueResource,
    PublishQueueState,
)
from superdesk.publish_async.formatters import BasePublishExchangeFormatter
from superdesk.publish.formatters import DeliveryFormatItem, Formatter, NINJS2Formatter, FormatReturnType
from superdesk.publish import registered_transmitters
from superdesk.publish.publish_service import PublishServiceBase
from superdesk.publish.transmitters.http_push import HTTPPushService
from superdesk.metadata.item import INGEST_ID
from superdesk import get_resource_service
from superdesk.lifecycle_timing import to_epoch_ms


class MockFormatter(Formatter):
    type = "mock"
    name = "Mock"
    use_cache = True

    async def format(self, article: dict, subscriber: dict | None, codes: list | None = None) -> FormatReturnType:
        raise Exception("Mock formatter failed")


class MockXMLFormatter(Formatter):
    type = "mock-xml"
    name = "Mock XML"
    content_type = "application/xml"
    media_from_source = True

    async def format(self, article: dict, subscriber: dict | None, codes: list | None = None) -> FormatReturnType:
        return [(1, "<newsItem/>")]


class MockUnlabelledFormatter(MockXMLFormatter):
    type = "mock-unlabelled"
    name = "Mock Unlabelled"
    content_type = None


class SelectedMediaXMLFormatter(MockXMLFormatter):
    type = "selected-media-xml"
    name = "Selected Media XML"

    async def format_for_delivery(
        self, article: dict, subscriber: dict | None, codes: list | None = None
    ) -> list[DeliveryFormatItem]:
        return [{"published_seq_num": 1, "formatted_item": "<newsItem/>", "media_item": article["selected_media"]}]


class CustomNINJSFormatter(NINJS2Formatter):
    type = "custom-ninjs"
    name = "Custom NINJS"

    async def format(self, article: dict, subscriber: dict | None, codes: list | None = None) -> FormatReturnType:
        return [(1, '{"custom": true}')]


class MockManifestTransmitter(PublishServiceBase):
    NAME = "Mock Manifest"
    include_associated_attachments = True

    def supports_delivery_manifest(self, content_type: str | None) -> bool:
        return True

    def needs_delivery_media(self, config: dict) -> bool:
        return bool(config.get("include_media"))


class BaseExchangeFormatterTestCase(TestCase):
    formatter: BasePublishExchangeFormatter
    subscriber: SubscribersResource

    async def asyncSetUp(self):
        await super().asyncSetUp()

        self.subscriber = SubscribersResource(
            id=ObjectId(),
            name="Mock Subscriber",
            products=[],
            subscriber_type=SubscriberType.WIRE,
            email="mock@subscribers.test",
            is_active=True,
            destinations=[
                SubscriberDestination(
                    _id="dest_1",
                    name="Mock 1 Destination",
                    format=MockFormatter.type,
                    delivery_type="file",
                ),
                SubscriberDestination(
                    _id="dest_2",
                    name="NINJS Destination",
                    format=NINJS2Formatter.type,
                    delivery_type="file",
                ),
                SubscriberDestination(
                    _id="dest_3",
                    name="Mock 3 Destination",
                    format=MockFormatter.type,
                    delivery_type="file",
                ),
            ],
        )

        await SubscribersResource.get_service().create([self.subscriber])

        self.formatter = BasePublishExchangeFormatter()

    async def test_normalizes_synchronous_and_async_formatter_results(self):
        formatter = Formatter()
        binary = {
            "published_seq_num": 2,
            "formatted_item": "",
            "encoded_item": b"\x00\xff",
            "media_item": {},
            "extension": "preserved",
        }
        expected = [{"published_seq_num": 1, "formatted_item": "<xml/>"}, binary]
        with mock.patch.object(formatter, "format", return_value=[(1, "<xml/>"), binary]):
            self.assertEqual(await formatter.format_for_delivery({}, None), expected)
        with mock.patch.object(formatter, "format", mock.AsyncMock(return_value=[(1, "<xml/>"), binary])):
            self.assertEqual(await formatter.format_for_delivery({}, None), expected)

    async def test_ninjs_format_override_is_normalized(self):
        result = await CustomNINJSFormatter().format_for_delivery({}, None)
        self.assertEqual(result, [{"published_seq_num": 1, "formatted_item": '{"custom": true}'}])

    async def test_invalid_formatter_result_is_rejected(self):
        formatter = Formatter()
        with mock.patch.object(formatter, "format", return_value=[{"formatted_item": "missing sequence"}]):
            with self.assertRaisesRegex(RuntimeError, "Invalid response from formatter"):
                await formatter.format_for_delivery({}, None)

    async def test_stores_formatter_errors_in_publish_queue_entry(self):
        item = dict(_id="abcd123", guid="abcd123", type="text", _current_version=1)
        request = PublishRequest(
            item=item,
            item_id="abcd123",
            operation="publish",
            published_state="published",
            item_type="text",
        )

        await self.formatter.get_tasks_for_subscriber(request, item, self.subscriber, PublishRequestResponse(), {})

        publish_queue = {
            queue.destination._id: queue
            async for queue in PublishQueueResource.get_service().get_all()
            if queue.destination
        }
        self.assertEqual(len(publish_queue), 3)

        self.assertEqual(publish_queue["dest_1"].state, PublishQueueState.ERROR)
        self.assertEqual(publish_queue["dest_1"].error_message, "Mock formatter failed")

        self.assertEqual(publish_queue["dest_2"].state, PublishQueueState.ROUTING)

        self.assertEqual(publish_queue["dest_3"].state, PublishQueueState.ERROR)
        self.assertEqual(publish_queue["dest_3"].error_message, "Mock formatter failed")

    async def test_http_push_manifest_uses_formatted_ninjs_and_cache_isolated_by_destination(self):
        self.subscriber.destinations = [
            SubscriberDestination(name="File", format="ninjs2", delivery_type="file"),
            SubscriberDestination(
                name="HTTP without assets",
                format="ninjs2",
                delivery_type="http_push",
                config={"resource_url": "http://example.com"},
            ),
            SubscriberDestination(
                name="HTTP with assets",
                format="ninjs2",
                delivery_type="http_push",
                config={"resource_url": "http://example.com", "assets_url": "http://example.com/assets"},
            ),
            SubscriberDestination(
                name="HTTP with assets cached",
                format="ninjs2",
                delivery_type="http_push",
                config={"resource_url": "http://example.com", "assets_url": "http://example.com/assets"},
            ),
        ]
        item = {
            "_id": "picture",
            "guid": "picture",
            "type": "picture",
            "_current_version": 1,
            "renditions": {
                "original": {"media": "original", "mimetype": "image/jpeg"},
                "unpublished": {"media": "hidden", "mimetype": "image/jpeg"},
            },
        }
        request = PublishRequest(
            item=item, item_id="picture", operation="publish", published_state="published", item_type="picture"
        )
        with mock.patch("superdesk.publish.formatters.ninjs_formatter.get_renditions_spec", return_value={}):
            tasks, _ = await self.formatter.get_tasks_for_subscriber(
                request, item, self.subscriber, PublishRequestResponse(), {}
            )

        queues = {}
        for task in tasks:
            assert task.destination is not None
            queues[task.destination.name] = task
        self.assertIsNone(queues["File"].delivery_media)
        self.assertEqual(queues["HTTP without assets"].delivery_media, [])
        expected = [{"media": "original", "resource": "upload", "mimetype": "image/jpeg"}]
        self.assertEqual(queues["HTTP with assets"].delivery_media, expected)
        self.assertEqual(queues["HTTP with assets cached"].delivery_media, expected)
        self.assertEqual(queues["HTTP with assets"].delivery_content_type, "application/json")
        stored = await PublishQueueResource.get_service().find_by_id(queues["HTTP with assets"].id)
        assert stored is not None
        self.assertEqual(stored.delivery_media, expected)

    async def test_manifest_uses_transmitter_specific_media_selection(self):
        self.subscriber.destinations = [
            SubscriberDestination(
                name="HTTP",
                format="mock-xml",
                delivery_type="http_push",
                config={"assets_url": "http://example.com/assets"},
            ),
            SubscriberDestination(name="FTP", format="mock-xml", delivery_type="ftp", config={"push_associated": True}),
            SubscriberDestination(
                name="Custom", format="mock-xml", delivery_type="mock-manifest", config={"include_media": True}
            ),
        ]
        item = {
            "_id": "picture",
            "guid": "picture",
            "type": "picture",
            "_current_version": 1,
            "renditions": {
                "original": {"media": "original", "mimetype": "image/jpeg"},
                "view": {"media": "view", "mimetype": "image/jpeg"},
                "other": {"media": "other", "mimetype": "image/jpeg"},
            },
            "associations": {"related": {"attachments": [{"media": "attachment", "mimetype": "application/pdf"}]}},
        }
        request = PublishRequest(
            item=item, item_id="picture", operation="publish", published_state="published", item_type="picture"
        )
        with (
            mock.patch.dict(registered_transmitters, {"mock-manifest": MockManifestTransmitter()}),
            mock.patch(
                "superdesk.publish.transmitters.file_providers.associations.get_renditions_spec",
                return_value={"view": {}},
            ),
        ):
            tasks, _ = await self.formatter.get_tasks_for_subscriber(
                request, item, self.subscriber, PublishRequestResponse(), {}
            )

        queues = {}
        for task in tasks:
            assert task.destination is not None
            queues[task.destination.name] = task
        self.assertEqual(
            {entry["media"] for entry in queues["HTTP"].delivery_media or []},
            {"original", "view", "other", "attachment"},
        )
        self.assertEqual({entry["media"] for entry in queues["FTP"].delivery_media or []}, {"original", "view"})
        self.assertEqual(
            {entry["media"] for entry in queues["Custom"].delivery_media or []},
            {"original", "view", "other", "attachment"},
        )
        stored = await PublishQueueResource.get_service().find_by_id(queues["FTP"].id)
        assert stored is not None
        self.assertEqual(stored.delivery_media, queues["FTP"].delivery_media)

    async def test_ftp_manifest_does_not_require_mime_type(self):
        self.subscriber.destinations = [
            SubscriberDestination(
                name="FTP", format="mock-unlabelled", delivery_type="ftp", config={"push_associated": True}
            )
        ]
        item = {
            "_id": "picture",
            "guid": "picture",
            "type": "picture",
            "_current_version": 1,
            "renditions": {"original": {"media": "image", "mimetype": "image/jpeg"}},
        }
        request = PublishRequest(
            item=item, item_id="picture", operation="publish", published_state="published", item_type="picture"
        )
        with mock.patch(
            "superdesk.publish.transmitters.file_providers.associations.get_renditions_spec", return_value={}
        ):
            tasks, _ = await self.formatter.get_tasks_for_subscriber(
                request, item, self.subscriber, PublishRequestResponse(), {}
            )
        self.assertIsNone(tasks[0].delivery_content_type)
        self.assertEqual(tasks[0].delivery_media, [{"media": "image", "resource": "upload", "mimetype": "image/jpeg"}])

    async def test_ftp_manifest_preserves_ninjs_rendition_filtering(self):
        self.subscriber.destinations = [
            SubscriberDestination(name="FTP", format="ninjs2", delivery_type="ftp", config={"push_associated": True})
        ]
        item = {
            "_id": "picture",
            "guid": "picture",
            "type": "picture",
            "_current_version": 1,
            "renditions": {
                "original": {"media": "original", "mimetype": "image/jpeg"},
                "excluded": {"media": "excluded", "mimetype": "image/jpeg"},
            },
        }
        request = PublishRequest(
            item=item, item_id="picture", operation="publish", published_state="published", item_type="picture"
        )
        with (
            mock.patch("superdesk.publish.formatters.ninjs_formatter.get_renditions_spec", return_value={}),
            mock.patch(
                "superdesk.publish.transmitters.file_providers.associations.get_renditions_spec",
                return_value={"excluded": {}},
            ),
        ):
            tasks, _ = await self.formatter.get_tasks_for_subscriber(
                request, item, self.subscriber, PublishRequestResponse(), {}
            )
        self.assertEqual(
            tasks[0].delivery_media, [{"media": "original", "resource": "upload", "mimetype": "image/jpeg"}]
        )

    async def test_ftp_ninjs_cache_does_not_reuse_another_subscribers_path(self):
        self.subscriber.destinations = [
            SubscriberDestination(
                name="FTP",
                format="ftp ninjs",
                delivery_type="ftp",
                config={"associated_path": "first", "push_associated": True, "include_original": True},
            )
        ]
        other_subscriber = deepcopy(self.subscriber)
        other_subscriber.id = ObjectId()
        other_subscriber.name = "Other Subscriber"
        assert other_subscriber.destinations is not None
        other_subscriber.destinations[0].config = {
            "associated_path": "second",
            "push_associated": True,
            "include_original": True,
        }
        await SubscribersResource.get_service().create([other_subscriber])
        item = {
            "_id": "picture",
            "guid": "picture",
            "type": "picture",
            "_current_version": 1,
            "renditions": {"original": {"media": "image.jpg", "mimetype": "image/jpeg"}},
        }
        request = PublishRequest(
            item=item, item_id="picture", operation="publish", published_state="published", item_type="picture"
        )
        cache = {}
        with (
            mock.patch("superdesk.publish.formatters.ninjs_formatter.get_renditions_spec", return_value={}),
            mock.patch(
                "superdesk.publish.transmitters.file_providers.associations.get_renditions_spec", return_value={}
            ),
        ):
            first, _ = await self.formatter.get_tasks_for_subscriber(
                request, item, self.subscriber, PublishRequestResponse(), cache
            )
            second, _ = await self.formatter.get_tasks_for_subscriber(
                request, item, other_subscriber, PublishRequestResponse(), cache
            )
        self.assertEqual(json.loads(first[0].formatted_item)["renditions"]["original"]["href"], "first/image.jpg")
        self.assertEqual(json.loads(second[0].formatted_item)["renditions"]["original"]["href"], "second/image.jpg")

    async def test_http_push_xml_manifest_includes_embedded_package_media(self):
        item = {
            "groups": [
                {"refs": [{"package_item": {"renditions": {"original": {"media": "image", "mimetype": "image/jpeg"}}}}]}
            ]
        }
        self.assertEqual(
            await self.formatter._get_delivery_media(item, include_package_items=True, transmitter_name="HTTP Push"),
            [{"media": "image", "resource": "upload", "mimetype": "image/jpeg"}],
        )

    async def test_http_push_manifest_resolves_only_public_attachment_references(self):
        attachments = {
            "public": {"media": "attachment-media", "mimetype": "application/pdf"},
            "internal": {"media": "private-media", "mimetype": "application/pdf", "internal": True},
        }
        service = mock.Mock(find_one_async=mock.AsyncMock(side_effect=lambda req, _id: attachments.get(_id)))
        item = {
            "attachments": [{"attachment": "public"}],
            "associations": {"related": {"attachments": [{"attachment": "internal"}]}},
        }
        with (
            mock.patch(
                "superdesk.publish_async.formatters.base_exchange_formatter.get_resource_service", return_value=service
            ),
            mock.patch.object(self.app.media, "url_for_external", return_value="https://example.com/attachment"),
        ):
            media = await self.formatter._get_delivery_media(
                item, include_package_items=False, transmitter_name="HTTP Push"
            )

        self.assertEqual(
            media, [{"media": "attachment-media", "resource": "attachments", "mimetype": "application/pdf"}]
        )
        self.assertEqual(item["attachments"], [{"attachment": "public"}])

    async def test_http_push_manifest_rejects_missing_attachment_reference(self):
        service = mock.Mock(find_one_async=mock.AsyncMock(return_value=None))
        with mock.patch(
            "superdesk.publish_async.formatters.base_exchange_formatter.get_resource_service", return_value=service
        ):
            with self.assertRaisesRegex(ValueError, "Attachment missing not found"):
                await self.formatter._get_delivery_media(
                    {"attachments": [{"attachment": "missing"}]}, False, "HTTP Push"
                )

    async def test_ftp_manifest_ignores_associated_attachment_references(self):
        item = {"associations": {"related": {"attachments": [{"attachment": "missing"}]}}}
        service = mock.Mock(find_one_async=mock.AsyncMock(return_value=None))
        with mock.patch(
            "superdesk.publish_async.formatters.base_exchange_formatter.get_resource_service", return_value=service
        ):
            media = await self.formatter._get_delivery_media(item, False, "FTP")
        self.assertEqual(media, [])
        service.find_one_async.assert_not_awaited()

    async def test_http_push_xml_creates_a_persisted_manifest(self):
        self.subscriber.destinations = [
            SubscriberDestination(
                name="HTTP XML",
                format="mock-xml",
                delivery_type="http_push",
                config={"assets_url": "http://example.com/assets", "resource_url": "http://example.com/push"},
            )
        ]
        item = {
            "_id": "picture",
            "guid": "picture",
            "type": "picture",
            "_current_version": 1,
            "renditions": {"original": {"media": "image", "mimetype": "image/jpeg"}, "crop": None},
        }
        request = PublishRequest(
            item=item, item_id="picture", operation="publish", published_state="published", item_type="picture"
        )
        tasks, _ = await self.formatter.get_tasks_for_subscriber(
            request, item, self.subscriber, PublishRequestResponse(), {}
        )
        stored = await PublishQueueResource.get_service().find_by_id(tasks[0].id)
        assert stored is not None
        self.assertEqual(stored.delivery_content_type, "application/xml")
        self.assertEqual(stored.delivery_media, [{"media": "image", "resource": "upload", "mimetype": "image/jpeg"}])
        self.assertIsNone(item["renditions"]["crop"])
        queue_item = stored.to_dict(context={"use_objectid": True})
        queue_item["encoded_item"] = b"<newsItem/>"
        transmitter = HTTPPushService()

        class Media(io.BytesIO):
            _id = "image"
            content_type = "image/jpeg"

        with (
            aioresponses() as http_mock,
            mock.patch.object(self.app.media, "get", return_value=Media(b"image data")) as get_media,
            mock.patch("superdesk.publish.transmitters.http_push.get_resource_service") as get_service,
            mock.patch.object(transmitter, "_transmit_legacy", side_effect=AssertionError("legacy path")),
        ):
            http_mock.get("http://example.com/assets/image", status=404)
            http_mock.post("http://example.com/assets", status=201)
            http_mock.post("http://example.com/push", status=201)
            await transmitter._transmit(queue_item, {})

        get_service.assert_not_called()
        get_media.assert_called_once_with("image", resource="upload")
        self.assertEqual(
            list(http_mock.requests),
            [
                ("GET", URL("http://example.com/assets/image")),
                ("POST", URL("http://example.com/assets")),
                ("POST", URL("http://example.com/push")),
            ],
        )
        sent = http_mock.requests[("POST", URL("http://example.com/push"))][0]
        self.assertEqual(sent.kwargs["data"], b"<newsItem/>")
        self.assertEqual(sent.kwargs["headers"]["Content-type"], "application/xml")

    async def test_http_push_xml_uses_formatter_selected_media_instead_of_source(self):
        self.subscriber.destinations = [
            SubscriberDestination(
                name="HTTP XML",
                format="selected-media-xml",
                delivery_type="http_push",
                config={"assets_url": "http://example.com/assets"},
            )
        ]
        item = {
            "_id": "picture",
            "guid": "picture",
            "type": "picture",
            "_current_version": 1,
            "renditions": {"original": {"media": "source", "mimetype": "image/jpeg"}},
            "selected_media": {"renditions": {"original": {"media": "selected", "mimetype": "image/jpeg"}}},
        }
        request = PublishRequest(
            item=item, item_id="picture", operation="publish", published_state="published", item_type="picture"
        )
        tasks, _ = await self.formatter.get_tasks_for_subscriber(
            request, item, self.subscriber, PublishRequestResponse(), {}
        )
        self.assertEqual(tasks[0].formatted_item, "<newsItem/>")
        self.assertEqual(
            tasks[0].delivery_media, [{"media": "selected", "resource": "upload", "mimetype": "image/jpeg"}]
        )

        item["selected_media"] = {}
        tasks, _ = await self.formatter.get_tasks_for_subscriber(
            request, item, self.subscriber, PublishRequestResponse(), {}
        )
        self.assertEqual(tasks[0].delivery_media, [])

    async def test_custom_ninjs_format_override_uses_legacy_media_handling(self):
        self.subscriber.destinations = [
            SubscriberDestination(
                name="Custom HTTP",
                format="custom-ninjs",
                delivery_type="http_push",
                config={"assets_url": "http://example.com/assets"},
            )
        ]
        item = {"_id": "story", "guid": "story", "type": "text", "_current_version": 1}
        request = PublishRequest(
            item=item, item_id="story", operation="publish", published_state="published", item_type="text"
        )
        tasks, _ = await self.formatter.get_tasks_for_subscriber(
            request, item, self.subscriber, PublishRequestResponse(), {}
        )
        self.assertEqual(tasks[0].formatted_item, '{"custom": true}')
        self.assertIsNone(tasks[0].delivery_media)

    async def test_manifest_failure_is_recorded_in_publish_queue(self):
        self.subscriber.destinations = [
            SubscriberDestination(
                name="HTTP XML",
                format="mock-xml",
                delivery_type="http_push",
                config={"assets_url": "http://example.com/assets"},
            ),
            SubscriberDestination(
                name="HTTP XML 2",
                format="mock-xml",
                delivery_type="http_push",
                config={"assets_url": "http://example.com/assets"},
            ),
        ]
        item = {
            "_id": "story",
            "guid": "story",
            "type": "text",
            "_current_version": 1,
            "attachments": [{"attachment": "missing"}],
        }
        request = PublishRequest(
            item=item, item_id="story", operation="publish", published_state="published", item_type="text"
        )
        service = mock.Mock(find_one_async=mock.AsyncMock(return_value=None))
        with mock.patch(
            "superdesk.publish_async.formatters.base_exchange_formatter.get_resource_service", return_value=service
        ):
            tasks, _ = await self.formatter.get_tasks_for_subscriber(
                request, item, self.subscriber, PublishRequestResponse(), {}
            )
        self.assertEqual(tasks, [])
        queues = [queue async for queue in PublishQueueResource.get_service().get_all()]
        self.assertEqual(len(queues), 2)
        for queue in queues:
            self.assertEqual(queue.state, PublishQueueState.ERROR)
            assert queue.error_message is not None
            self.assertIn("Attachment missing not found", queue.error_message)

    async def test_sets_queue_lifecycle_start_from_lifecycle_started_at(self):
        lifecycle_started_at = utcnow() - timedelta(minutes=10)
        item = {
            "_id": "lifecycle-ingest",
            "guid": "lifecycle-ingest",
            "type": "text",
            "_current_version": 1,
            "lifecycle_timing": {"lifecycle_started_at": lifecycle_started_at},
        }
        request = PublishRequest(
            item=item,
            item_id=item["_id"],
            operation="publish",
            published_state="published",
            item_type=item["type"],
        )

        await self.formatter.get_tasks_for_subscriber(request, item, self.subscriber, PublishRequestResponse(), {})
        publish_queue = {
            queue.destination._id: queue
            async for queue in PublishQueueResource.get_service().get_all()
            if queue.destination
        }

        self.assertEqual(lifecycle_started_at, publish_queue["dest_2"].lifecycle_started_at)

    async def test_sets_queue_lifecycle_start_from_request_when_filtered_item_drops_timing(self):
        lifecycle_started_at = utcnow() - timedelta(minutes=7)
        source_item = {
            "_id": "lifecycle-filtered",
            "guid": "lifecycle-filtered",
            "type": "text",
            "_current_version": 1,
            "lifecycle_timing": {"lifecycle_started_at": lifecycle_started_at},
        }
        request = PublishRequest(
            item=source_item,
            item_id=source_item["_id"],
            operation="publish",
            published_state="published",
            item_type=source_item["type"],
        )

        filtered_item = {
            "_id": source_item["_id"],
            "guid": source_item["guid"],
            "type": source_item["type"],
            "_current_version": source_item["_current_version"],
        }

        with mock.patch.object(self.formatter, "filter_item_fields", return_value=filtered_item):
            await self.formatter.get_request_tasks(request, PublishRequestResponse(subscribers=[self.subscriber]))

        publish_queue = {
            queue.destination._id: queue
            async for queue in PublishQueueResource.get_service().get_all()
            if queue.destination
        }

        self.assertEqual(lifecycle_started_at, publish_queue["dest_2"].lifecycle_started_at)

    async def test_fallbacks_to_ingest_doc_lifecycle_start_when_missing_on_item(self):
        lifecycle_started_at = utcnow() - timedelta(minutes=9)
        ingest_id = "ingest-source-1"

        item = {
            "_id": "lifecycle-fallback",
            "guid": "lifecycle-fallback",
            "type": "text",
            "_current_version": 1,
            "ingest_provider": "5ffeb066bc16d5875dc53081",
            INGEST_ID: ingest_id,
            "lifecycle_timing": {},
        }
        request = PublishRequest(
            item=item,
            item_id=item["_id"],
            operation="publish",
            published_state="published",
            item_type=item["type"],
        )

        ingest_service = get_resource_service("ingest")
        with mock.patch.object(
            ingest_service,
            "find_one_async",
            return_value={"lifecycle_timing": {"lifecycle_started_at": lifecycle_started_at}},
        ):
            await self.formatter.get_tasks_for_subscriber(request, item, self.subscriber, PublishRequestResponse(), {})

        publish_queue = {
            queue.destination._id: queue
            async for queue in PublishQueueResource.get_service().get_all()
            if queue.destination
        }

        self.assertEqual(lifecycle_started_at, publish_queue["dest_2"].lifecycle_started_at)

    async def test_sets_lifecycle_to_transmit_for_content_api_on_create(self):
        lifecycle_started_at = utcnow() - timedelta(seconds=8)
        completed_at = utcnow()
        subscriber = SubscribersResource(
            id=ObjectId(),
            name="Content API Subscriber",
            products=[],
            subscriber_type=SubscriberType.WIRE,
            email="content-api@subscribers.test",
            is_active=True,
            destinations=[
                SubscriberDestination(
                    _id="dest_content_api",
                    name="Content API",
                    format=NINJS2Formatter.type,
                    delivery_type="content_api",
                )
            ],
        )
        await SubscribersResource.get_service().create([subscriber])

        item = {
            "_id": "content-api-item",
            "guid": "content-api-item",
            "type": "text",
            "_current_version": 1,
            "lifecycle_timing": {"lifecycle_started_at": lifecycle_started_at},
        }
        request = PublishRequest(
            item=item,
            item_id=item["_id"],
            operation="publish",
            published_state="published",
            item_type=item["type"],
        )

        with mock.patch("superdesk.publish_async.formatters.base_exchange_formatter.utcnow", return_value=completed_at):
            await self.formatter.get_tasks_for_subscriber(request, item, subscriber, PublishRequestResponse(), {})

        publish_queue = {
            queue.destination._id: queue
            async for queue in PublishQueueResource.get_service().get_all()
            if queue.destination
        }

        queue_item = publish_queue["dest_content_api"]
        self.assertEqual(PublishQueueState.SUCCESS, queue_item.state)
        self.assertEqual(completed_at, queue_item.completed_at)
        self.assertEqual(to_epoch_ms(lifecycle_started_at), queue_item.lifecycle_started_ms)
        self.assertEqual(to_epoch_ms(completed_at), queue_item.completed_ms)
        self.assertEqual(8000, queue_item.lifecycle_to_transmit_ms)
