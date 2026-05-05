"""
TTSFM - Text-to-Speech for Free using OpenAI.fm

A Python library for generating high-quality text-to-speech audio using the free OpenAI.fm service.
Supports multiple voices and audio formats with a simple, intuitive API.

Example:
    >>> from ttsfm import TTSClient, Voice, AudioFormat
    >>>
    >>> client = TTSClient()
    >>>
    >>> # Generate MP3 audio
    >>> mp3_response = client.generate_speech(
    ...     text="Hello, world!",
    ...     voice=Voice.ALLOY,
    ...     response_format=AudioFormat.MP3
    ... )
    >>> mp3_response.save_to_file("hello")  # Saves as hello.mp3
    >>>
    >>> # Generate WAV audio
    >>> wav_response = client.generate_speech(
    ...     text="High quality audio",
    ...     voice=Voice.NOVA,
    ...     response_format=AudioFormat.WAV
    ... )
    >>> wav_response.save_to_file("audio")  # Saves as audio.wav
    >>>
    >>> # Generate OPUS audio
    >>> opus_response = client.generate_speech(
    ...     text="Compressed audio",
    ...     voice=Voice.ECHO,
    ...     response_format=AudioFormat.OPUS
    ... )
    >>> opus_response.save_to_file("compressed")  # Saves as compressed.wav
"""

from typing import Optional

from importlib.metadata import PackageNotFoundError, version as _package_version

from .async_client import AsyncTTSClient
from .audio import combine_audio_chunks, combine_responses
from .client import TTSClient
from .exceptions import (
    APIException,
    AudioProcessingException,
    AuthenticationException,
    NetworkException,
    QuotaExceededException,
    RateLimitException,
    ServiceUnavailableException,
    TTSException,
    ValidationException,
)
from .models import (
    APIError,
    AudioFormat,
    NetworkError,
    TTSError,
    TTSRequest,
    TTSResponse,
    ValidationError,
    Voice,
)
from .utils import split_text_by_length, validate_text_length

try:
    __version__ = _package_version("ttsfm")
except PackageNotFoundError:  # pragma: no cover - running from source tree without install
    __version__ = "0.0.0"
__author__ = "dbcccc"
__email__ = "120614547+dbccccccc@users.noreply.github.com"
__description__ = "Text-to-Speech API Client with OpenAI compatibility"
__url__ = "https://github.com/dbccccccc/ttsfm"

# Default client instance for convenience
default_client = None


def create_client(base_url: Optional[str] = None, api_key: Optional[str] = None, **kwargs) -> TTSClient:  # type: ignore[misc]
    """
    Create a new TTS client instance.

    Args:
        base_url: Base URL for the TTS service
        api_key: API key for authentication (if required)
        **kwargs: Additional client configuration

    Returns:
        TTSClient: Configured client instance
    """
    client_kwargs = kwargs.copy()
    if base_url is not None:
        client_kwargs["base_url"] = base_url
    if api_key is not None:
        client_kwargs["api_key"] = api_key
    return TTSClient(**client_kwargs)


def create_async_client(base_url: Optional[str] = None, api_key: Optional[str] = None, **kwargs) -> AsyncTTSClient:  # type: ignore[misc]
    """
    Create a new async TTS client instance.

    Args:
        base_url: Base URL for the TTS service
        api_key: API key for authentication (if required)
        **kwargs: Additional client configuration

    Returns:
        AsyncTTSClient: Configured async client instance
    """
    client_kwargs = kwargs.copy()
    if base_url is not None:
        client_kwargs["base_url"] = base_url
    if api_key is not None:
        client_kwargs["api_key"] = api_key
    return AsyncTTSClient(**client_kwargs)


def set_default_client(client: TTSClient) -> None:
    """Set the default client instance for convenience functions."""
    global default_client
    default_client = client


def generate_speech(text: str, voice: str = "alloy", **kwargs) -> TTSResponse:  # type: ignore[misc]
    """
    Convenience function to generate speech using the default client.

    Args:
        text: Text to convert to speech
        voice: Voice to use for generation
        **kwargs: Additional generation parameters

    Returns:
        TTSResponse: Generated audio response

    Raises:
        TTSException: If no default client is set or generation fails
    """
    if default_client is None:
        raise TTSException("No default client set. Use create_client() first.")

    return default_client.generate_speech(text=text, voice=voice, **kwargs)


def generate_speech_long_text(text: str, voice: str = "alloy", **kwargs):  # type: ignore[no-untyped-def]
    """
    Convenience function to generate speech from long text using the default client.

    Automatically splits long text into chunks and generates speech for each chunk.

    Args:
        text: Text to convert to speech (can be longer than 1000 characters)
        voice: Voice to use for generation
        **kwargs: Additional generation parameters (max_length, preserve_words, etc.)

    Returns:
        list: List of TTSResponse objects for each chunk

    Raises:
        TTSException: If no default client is set or generation fails
    """
    if default_client is None:
        raise TTSException("No default client set. Use create_client() first.")

    return default_client.generate_speech_long_text(text=text, voice=voice, **kwargs)


# Export all public components
__all__ = [
    # Main classes
    "TTSClient",
    "AsyncTTSClient",
    # Models
    "TTSRequest",
    "TTSResponse",
    "Voice",
    "AudioFormat",
    "TTSError",
    "APIError",
    "NetworkError",
    "ValidationError",
    # Exceptions
    "TTSException",
    "APIException",
    "NetworkException",
    "ValidationException",
    "RateLimitException",
    "AuthenticationException",
    "ServiceUnavailableException",
    "QuotaExceededException",
    "AudioProcessingException",
    # Factory functions
    "create_client",
    "create_async_client",
    "set_default_client",
    "generate_speech",
    "generate_speech_long_text",
    # Utility functions
    "validate_text_length",
    "split_text_by_length",
    "combine_audio_chunks",
    "combine_responses",
    # Package metadata
    "__version__",
    "__author__",
    "__email__",
    "__description__",
    "__url__",
]
