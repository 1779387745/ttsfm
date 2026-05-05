"""
Exception classes for the TTSFM package.

This module defines the exception hierarchy used throughout the package
for consistent error handling and reporting.
"""

from typing import Any, Dict, Optional


class TTSException(Exception):
    """
    Base exception class for all TTSFM-related errors.

    Attributes:
        message: Human-readable error message
        code: Error code for programmatic handling
        details: Additional error details
    """

    def __init__(
        self, message: str, code: Optional[str] = None, details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.message = message
        self.code = code or self.__class__.__name__
        self.details = details or {}

    def __str__(self) -> str:
        if self.code:
            return f"[{self.code}] {self.message}"
        return self.message

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(message='{self.message}', code='{self.code}')"


class APIException(TTSException):
    """
    Exception raised for API-related errors.

    This includes HTTP errors, invalid responses, and server-side issues.
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_data: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.status_code = status_code
        self.response_data = response_data or {}

    def __str__(self) -> str:
        if self.status_code:
            return f"[HTTP {self.status_code}] {self.message}"
        return super().__str__()


class NetworkException(TTSException):
    """
    Exception raised for network-related errors.

    This includes connection timeouts, DNS resolution failures, and other
    network connectivity issues.
    """

    def __init__(
        self, message: str, timeout: Optional[float] = None, retry_count: int = 0, **kwargs: Any
    ) -> None:
        super().__init__(message, **kwargs)
        self.timeout = timeout
        self.retry_count = retry_count


class ValidationException(TTSException):
    """
    Exception raised for input validation errors.

    This includes invalid parameters, missing required fields, and
    data format issues.
    """

    def __init__(
        self, message: str, field: Optional[str] = None, value: Optional[Any] = None, **kwargs: Any
    ) -> None:
        super().__init__(message, **kwargs)
        self.field = field
        self.value = value

    def __str__(self) -> str:
        if self.field:
            return f"Validation error for '{self.field}': {self.message}"
        return f"Validation error: {self.message}"


class RateLimitException(APIException):
    """
    Exception raised when API rate limits are exceeded.

    Attributes:
        retry_after: Seconds to wait before retrying (if provided by server)
        limit: Rate limit that was exceeded
        remaining: Remaining requests in current window
    """

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after: Optional[int] = None,
        limit: Optional[int] = None,
        remaining: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, status_code=429, **kwargs)
        self.retry_after = retry_after
        self.limit = limit
        self.remaining = remaining

    def __str__(self) -> str:
        msg = super().__str__()
        if self.retry_after:
            msg += f" (retry after {self.retry_after}s)"
        return msg


class AuthenticationException(APIException):
    """
    Exception raised for authentication and authorization errors.

    This includes invalid API keys, expired tokens, and insufficient
    permissions.
    """

    def __init__(self, message: str = "Authentication failed", **kwargs: Any) -> None:
        super().__init__(message, status_code=401, **kwargs)


class ServiceUnavailableException(APIException):
    """
    Exception raised when the TTS service is temporarily unavailable.

    This includes server maintenance, overload conditions, and
    temporary service outages.
    """

    def __init__(
        self,
        message: str = "Service temporarily unavailable",
        retry_after: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, status_code=503, **kwargs)
        self.retry_after = retry_after


class QuotaExceededException(APIException):
    """
    Exception raised when usage quotas are exceeded.

    This includes monthly limits, character limits, and other
    usage-based restrictions.
    """

    def __init__(
        self,
        message: str = "Usage quota exceeded",
        quota_type: Optional[str] = None,
        limit: Optional[int] = None,
        used: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, status_code=402, **kwargs)
        self.quota_type = quota_type
        self.limit = limit
        self.used = used


class AudioProcessingException(TTSException):
    """
    Exception raised for audio processing errors.

    This includes format conversion issues, audio generation failures,
    and output processing problems.
    """

    def __init__(self, message: str, audio_format: Optional[str] = None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.audio_format = audio_format


def create_exception_from_response(
    status_code: int, response_data: Dict[str, Any], default_message: str = "API request failed"
) -> APIException:
    """
    Create appropriate exception from API response.

    Args:
        status_code: HTTP status code
        response_data: Response data from API
        default_message: Default message if none in response

    Returns:
        APIException: Appropriate exception instance
    """
    err = response_data.get("error")
    if isinstance(err, str) and err.strip():
        message = err
    elif isinstance(err, dict):
        message = err.get("message", default_message)
    else:
        message = default_message

    if status_code == 401:
        return AuthenticationException(message, response_data=response_data)
    elif status_code == 402:
        return QuotaExceededException(message, response_data=response_data)
    elif status_code == 429:
        retry_after = response_data.get("retry_after")
        return RateLimitException(message, retry_after=retry_after, response_data=response_data)
    elif status_code == 503:
        retry_after = response_data.get("retry_after")
        return ServiceUnavailableException(
            message,
            retry_after=retry_after,
            response_data=response_data,
        )
    else:
        return APIException(message, status_code=status_code, response_data=response_data)
