class Error(Exception):
    ...


class ConfigurationError(Error):
    ...


class ClientError(Error):
    ...


class ProviderError(Error):
    ...


class Conflict(Error):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class NotFound(Error):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message
