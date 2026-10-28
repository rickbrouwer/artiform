class ArtiformError(Exception):
    """Base class for all errors raised by artiform."""


class ConfigError(ArtiformError):
    """The configuration file is invalid."""


class ApiError(ArtiformError):
    """Artifactory returned an unexpected HTTP error."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class NotFoundError(ApiError):
    """Artifactory returned HTTP 404."""

    def __init__(self, message: str):
        super().__init__(404, message)
