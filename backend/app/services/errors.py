"""Domain errors translated to HTTP responses by a single exception handler."""

from __future__ import annotations


class DomainError(Exception):
    status_code = 400
    code = "domain_error"

    def __init__(self, message: str, *, field: str | None = None, detail: dict | None = None):
        super().__init__(message)
        self.message = message
        self.field = field
        self.detail = detail or {}


class ValidationError(DomainError):
    status_code = 422
    code = "validation_error"


class NotFoundError(DomainError):
    status_code = 404
    code = "not_found"


class ConflictError(DomainError):
    status_code = 409
    code = "conflict"


class PermissionDeniedError(DomainError):
    status_code = 403
    code = "permission_denied"


class AuthenticationError(DomainError):
    status_code = 401
    code = "not_authenticated"


class RateLimitedError(DomainError):
    status_code = 429
    code = "rate_limited"

    def __init__(self, message: str, retry_after: int = 60):
        super().__init__(message, detail={"retry_after_seconds": retry_after})
        self.retry_after = retry_after
