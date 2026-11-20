from typing import Any, Literal, Callable
from functools import partial
import re

from yarl import URL
from aiointercept import aiointercept, CallbackResult

from superdesk.core.types import HTTP_METHOD


HttpMockCallback = Callable[[str], CallbackResult]
HttpMocks = dict[Literal["*"] | str, dict[tuple[HTTP_METHOD | Literal["*"], str], HttpMockCallback]]


__all__ = [
    "mock_http",
    "start_mock_http",
    "stop_mock_http",
    "mock_multiple_endpoints",
    "CallbackResult",
]


async def start_mock_http(context: Any) -> aiointercept:
    try:
        mock: aiointercept | None = getattr(context, "_http_mock", None)
    except KeyError:
        mock = None
    if mock is not None:
        return mock

    mock = aiointercept(mock_external_urls=True, passthrough=["127.0.0.1", "localhost"])
    await mock.start()
    setattr(context, "_http_mock", mock)

    if hasattr(context, "addAsyncCleanup"):
        context.addAsyncCleanup(stop_mock_http, context)

    return mock


async def stop_mock_http(context: Any) -> None:
    try:
        mock: aiointercept | None = getattr(context, "_http_mock", None)
    except KeyError:
        mock = None
    if mock is not None:
        await mock.stop()
        setattr(context, "_http_mock", None)


def mock_http(context: Any) -> aiointercept:
    try:
        mock: aiointercept | None = getattr(context, "_http_mock", None)
    except KeyError:
        mock = None
    if mock is None:
        raise RuntimeError("HTTP mocks have not been started for this context")
    return mock


def mock_multiple_endpoints(context: Any, http_mocks: HttpMocks | CallbackResult) -> aiointercept:
    methods: list[HTTP_METHOD] = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
    mock = mock_http(context)

    def _mock_requests(request_method: HTTP_METHOD, request_url: str, **kwargs) -> CallbackResult:
        parsed_url = URL(request_url)
        if isinstance(http_mocks, CallbackResult):
            return http_mocks

        host_mocks = http_mocks.get(parsed_url.host or "") or http_mocks.get("*") or {}
        for (http_method, path_prefix), callback in host_mocks.items():
            if http_method in ("*", request_method) and (
                path_prefix == "*" or parsed_url.path.startswith(path_prefix)
            ):
                return callback(request_url)

        return CallbackResult(status=404, body="Mock didn't match any requests", content_type="text/plain")

    for method in methods:
        mock.add(
            re.compile(r".*"),
            method,
            callback=partial(_mock_requests, method),
            repeat=True,
        )

    return mock
