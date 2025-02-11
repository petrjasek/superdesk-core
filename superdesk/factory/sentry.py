import sentry_sdk


SENTRY_DSN = "SENTRY_DSN"


class SuperdeskSentry:
    """Sentry proxy that will do nothing in case sentry is not configured."""

    def __init__(self, app):
        if app.config.get(SENTRY_DSN):
            dsn = app.config[SENTRY_DSN]
            self.sentry = sentry_sdk.init(
                dsn=dsn,
                send_default_pii=True,
                traces_sample_rate=1.0,
            )
        else:
            self.sentry = None

    def captureException(self, exc_info=None, **kwargs):
        if self.sentry:
            sentry_sdk.capture_exception(exc_info, **kwargs)

    def captureMessage(self, message, **kwargs):
        if self.sentry:
            sentry_sdk.capture_message(message, **kwargs)
