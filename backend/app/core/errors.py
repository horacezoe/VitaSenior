class AppError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None, *, retryable: bool = False):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.details, self.retryable = details or {}, retryable

def unimplemented() -> None:
    raise AppError(501, "MODULE_NOT_IMPLEMENTED", "This business module is not implemented in F0")
