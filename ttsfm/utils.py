"""
Utility functions for the TTSFM package.

This module provides common utility functions used throughout the package,
including HTTP helpers, validation utilities, and configuration management.
"""

import logging
import os
import random
import re
from html import unescape
from itertools import cycle
from threading import Lock
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple, Union
from urllib.parse import urljoin, urlparse

# Configure logging
logger = logging.getLogger(__name__)

DEFAULT_USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_0) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/16.5 Safari/605.1.15"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.4 Mobile/15E148 Safari/604.1"
    ),
]

_HEADER_SEED = os.getenv("TTSFM_HEADER_SEED")
_USE_FAKE_USERAGENT = os.getenv("TTSFM_USE_FAKE_USERAGENT", "false").lower() == "true"
_RANDOMIZE_HEADERS = os.getenv("TTSFM_RANDOMIZE_HEADERS", "false").lower() == "true"

_HEADER_RANDOM: Optional[random.Random]
if _RANDOMIZE_HEADERS:
    _HEADER_RANDOM = random.Random(_HEADER_SEED) if _HEADER_SEED is not None else random.Random()
else:
    _HEADER_RANDOM = None

_LANGUAGE_OPTIONS = ["en-US,en;q=0.9", "en-GB,en;q=0.8", "en-CA,en;q=0.7"]
_PLATFORM_OPTIONS = ['"Windows"', '"macOS"', '"Linux"']
_LANGUAGE_CYCLE = cycle(_LANGUAGE_OPTIONS)
_PLATFORM_CYCLE = cycle(_PLATFORM_OPTIONS)
_LANGUAGE_LOCK = Lock()
_PLATFORM_LOCK = Lock()
_UPGRADE_TOGGLE = cycle([True, False])
_UPGRADE_LOCK = Lock()

_USER_AGENT_CYCLE = cycle(DEFAULT_USER_AGENTS)
_USER_AGENT_LOCK = Lock()

try:  # Optional dependency – only used when explicitly enabled
    if _USE_FAKE_USERAGENT:
        from fake_useragent import UserAgent
    else:
        UserAgent = None
except Exception as exc:  # pragma: no cover - defensive import guard
    logger.debug("fake-useragent unavailable: %s", exc)
    UserAgent = None

QUOTE_CHAR_MAP = dict.fromkeys([0x201C, 0x201D, 0x201E, 0x201F, 0x0060], '"')
QUOTE_CHAR_MAP.update(
    {
        0x2019: "'",
        0x2018: "'",
        0x201A: "'",
        0x00B4: "'",
    }
)
QUOTE_TRANSLATION = str.maketrans(QUOTE_CHAR_MAP)


def get_user_agent() -> str:
    """Return a realistic User-Agent string without requiring network access."""
    override = os.getenv("TTSFM_USER_AGENT")
    if override:
        return override.strip()

    if _USE_FAKE_USERAGENT and UserAgent is not None:  # pragma: no cover
        # Optional dependency required for dynamic user-agent generation
        try:
            ua = UserAgent(fallback=DEFAULT_USER_AGENTS[0])
            candidate = ua.random
            if candidate:
                return candidate
        except Exception as exc:  # pragma: no cover - fake_useragent instability
            logger.debug("fake-useragent lookup failed, using static list: %s", exc)

    with _USER_AGENT_LOCK:
        return next(_USER_AGENT_CYCLE)


def _next_language() -> str:
    with _LANGUAGE_LOCK:
        return next(_LANGUAGE_CYCLE)


def _next_platform() -> str:
    with _PLATFORM_LOCK:
        return next(_PLATFORM_CYCLE)


def _upgrade_insecure_requests() -> bool:
    if _HEADER_RANDOM:
        return _HEADER_RANDOM.random() < 0.5
    with _UPGRADE_LOCK:
        return next(_UPGRADE_TOGGLE)


def get_realistic_headers(custom_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Generate HTTP headers that mimic a browser while remaining deterministic."""
    user_agent = get_user_agent()

    headers = {
        "Accept": "application/json, audio/*",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": _next_language(),
        "Cache-Control": "no-cache",
        "DNT": "1",
        "Pragma": "no-cache",
        "User-Agent": user_agent,
        "X-Requested-With": "XMLHttpRequest",
    }

    if any(browser in user_agent.lower() for browser in ["chrome", "edge", "chromium"]):
        version_match = re.search(r"(?:Chrome|Edge|Chromium)/(\d+)", user_agent)
        major_version = version_match.group(1) if version_match else "121"

        if "google chrome" in user_agent.lower():
            brands = [
                f'"Google Chrome";v="{major_version}"',
                f'"Chromium";v="{major_version}"',
                '"Not A(Brand";v="99"',
            ]
        elif "microsoft edge" in user_agent.lower():
            brands = [
                f'"Microsoft Edge";v="{major_version}"',
                f'"Chromium";v="{major_version}"',
                '"Not A(Brand";v="99"',
            ]
        else:
            brands = [
                f'"Chromium";v="{major_version}"',
                '"Not A(Brand";v="8"',
            ]

        headers.update(
            {
                "Sec-Ch-Ua": ", ".join(brands),
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": _next_platform(),
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
            }
        )

    if _upgrade_insecure_requests():
        headers["Upgrade-Insecure-Requests"] = "1"

    if custom_headers:
        headers.update(custom_headers)

    return headers


def validate_text_length(text: str, max_length: int = 1000, raise_error: bool = True) -> bool:
    """
    Validate text length against maximum allowed characters.

    Args:
        text: Text to validate
        max_length: Maximum allowed length in characters
        raise_error: Whether to raise an exception if validation fails

    Returns:
        bool: True if text is within limits, False otherwise

    Raises:
        ValueError: If text exceeds max_length and raise_error is True
    """
    if not text:
        return True

    text_length = len(text)

    if text_length > max_length:
        if raise_error:
            raise ValueError(
                f"Text is too long ({text_length} characters). "
                f"Maximum allowed length is {max_length} characters. "
                "Requests above this threshold should be split and combined."
            )
        return False

    return True


_SENTENCE_TERMINATORS = {".", "!", "?"}


def _split_into_sentences(text: str) -> List[str]:
    sentences: List[str] = []
    buffer: List[str] = []
    length = len(text)
    i = 0

    while i < length:
        char = text[i]
        buffer.append(char)

        if char in _SENTENCE_TERMINATORS:
            j = i + 1
            while j < length and text[j] in _SENTENCE_TERMINATORS:
                buffer.append(text[j])
                j += 1
            sentence = "".join(buffer).strip()
            if sentence:
                sentences.append(sentence)
            buffer = []
            i = j - 1
        i += 1

    remainder = "".join(buffer).strip()
    if remainder:
        sentences.append(remainder)

    return sentences


def _split_long_segment(segment: str, max_length: int) -> List[str]:
    """Fallback splitter for oversized segments."""
    max_length = max(1, max_length)
    if len(segment) <= max_length:
        return [segment]

    parts: List[str] = []
    words = segment.split()

    if not words:
        for i in range(0, len(segment), max_length):
            chunk = segment[i : i + max_length]
            if chunk.strip():
                parts.append(chunk)
        return parts

    current_words: List[str] = []
    current_len = 0

    for word in words:
        word_len = len(word)

        if word_len > max_length:
            if current_words:
                parts.append(" ".join(current_words))
                current_words = []
                current_len = 0

            for i in range(0, word_len, max_length):
                chunk = word[i : i + max_length]
                if chunk.strip():
                    parts.append(chunk)
            continue

        separator = 1 if current_words else 0
        proposed = current_len + word_len + separator

        if proposed <= max_length:
            if separator:
                current_len += 1
            current_words.append(word)
            current_len += word_len
            continue

        if current_words:
            parts.append(" ".join(current_words))

        current_words = [word]
        current_len = word_len

    if current_words:
        parts.append(" ".join(current_words))

    return parts


def split_text_by_length(
    text: str,
    max_length: int = 1000,
    preserve_words: bool = True,
) -> List[str]:
    """Split text into chunks no longer than ``max_length`` characters."""
    if not text:
        return []

    if max_length < 1:
        raise ValueError("max_length must be at least 1")
    if max_length > 1000:
        raise ValueError("max_length cannot exceed 1000 (upstream TTS limit)")

    if len(text) <= max_length:
        return [text]

    chunks: List[str] = []

    if preserve_words:
        sentences = _split_into_sentences(text)
        current_segment: List[str] = []
        current_length = 0

        for sentence in sentences:
            if not sentence:
                continue

            separator = " " if current_segment else ""
            candidate_length = current_length + len(separator) + len(sentence)

            if candidate_length <= max_length:
                current_segment.append(sentence)
                current_length = candidate_length
                continue

            if current_segment:
                chunks.append(" ".join(current_segment))

            if len(sentence) > max_length:
                chunks.extend(_split_long_segment(sentence, max_length))
                current_segment = []
                current_length = 0
                continue

            current_segment = [sentence]
            current_length = len(sentence)

        if current_segment:
            chunks.append(" ".join(current_segment))
    else:
        for i in range(0, len(text), max_length):
            chunk = text[i : i + max_length]
            if chunk.strip():
                chunks.append(chunk)

    return [chunk for chunk in chunks if chunk.strip()]


def sanitize_text(text: str) -> str:
    """Sanitize input text for TTS processing while keeping user content intact."""
    if not text:
        return ""

    if len(text) > 50000:
        raise ValueError("Input text too long for sanitization (max 50000 characters)")

    normalized = unescape(text)
    normalized = normalized.translate(QUOTE_TRANSLATION)
    normalized = normalized.replace(" ", " ")

    without_tags = re.sub(r"<[^>]+>", " ", normalized)
    cleaned = without_tags.replace("<", " ").replace(">", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)

    return cleaned.strip()


def validate_url(url: str) -> bool:
    """
    Validate if a URL is properly formatted.

    Args:
        url: URL to validate

    Returns:
        bool: True if URL is valid, False otherwise
    """
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False


def build_url(base_url: str, path: str) -> str:
    """
    Build a complete URL from base URL and path.

    Args:
        base_url: Base URL
        path: Path to append

    Returns:
        str: Complete URL
    """
    # Ensure base_url ends with /
    if not base_url.endswith("/"):
        base_url += "/"

    # Ensure path doesn't start with /
    if path.startswith("/"):
        path = path[1:]

    return urljoin(base_url, path)


def get_random_delay(min_delay: float = 1.0, max_delay: float = 5.0) -> float:
    """
    Get a random delay with jitter for rate limiting.

    Args:
        min_delay: Minimum delay in seconds
        max_delay: Maximum delay in seconds

    Returns:
        float: Random delay in seconds
    """
    base_delay = random.uniform(min_delay, max_delay)
    jitter = random.uniform(0.1, 0.5)
    return base_delay + jitter


_SAFE_METADATA_RESPONSE_HEADERS = frozenset(
    {
        "cache-control",
        "content-length",
        "content-type",
        "date",
        "etag",
        "last-modified",
        "server",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
        "x-request-id",
    }
)


def safe_response_headers_for_metadata(
    headers: Union[Mapping[str, str], Iterable[Tuple[str, str]]],
) -> Dict[str, str]:
    """Subset of HTTP response headers safe to retain in client metadata (no cookies / auth)."""
    out: Dict[str, str] = {}
    try:
        items = headers.items()  # type: ignore[union-attr]
    except AttributeError:
        return out
    for key, value in items:
        if key.lower() in _SAFE_METADATA_RESPONSE_HEADERS:
            out[key] = value if isinstance(value, str) else str(value)
    return out


def exponential_backoff(attempt: int, base_delay: float = 1.0, max_delay: float = 60.0) -> float:
    """
    Calculate exponential backoff delay.

    Args:
        attempt: Attempt number (0-based)
        base_delay: Base delay in seconds
        max_delay: Maximum delay in seconds

    Returns:
        float: Delay in seconds
    """
    delay = base_delay * (2**attempt)
    jitter = random.uniform(0.1, 0.3) * delay
    return min(delay + jitter, max_delay)


def load_config_from_env(prefix: str = "TTSFM_") -> Dict[str, Any]:
    """
    Load configuration from environment variables.

    Args:
        prefix: Prefix for environment variables

    Returns:
        Dict[str, Any]: Configuration dictionary
    """
    config: Dict[str, Any] = {}

    for key, value in os.environ.items():
        if key.startswith(prefix):
            config_key = key[len(prefix) :].lower()

            # Try to convert to appropriate type
            if value.lower() in ("true", "false"):
                config[config_key] = value.lower() == "true"
            elif value.isdigit():
                config[config_key] = int(value)
            elif "." in value and value.replace(".", "").isdigit():
                config[config_key] = float(value)
            else:
                config[config_key] = value

    return config


def resolve_api_key(explicit: Optional[str]) -> Optional[str]:
    """Use explicit API key when provided; otherwise read ``TTSFM_API_KEY`` via :func:`load_config_from_env`."""
    if explicit is not None:
        return explicit
    env_cfg = load_config_from_env()
    val = env_cfg.get("api_key")
    return str(val) if val else None


def setup_logging(
    level: Union[str, int] = logging.INFO,
    format_string: Optional[str] = None,
) -> None:
    """
    Setup logging configuration for the package.

    Args:
        level: Logging level
        format_string: Custom format string
    """
    if format_string is None:
        format_string = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    logging.basicConfig(level=level, format=format_string, handlers=[logging.StreamHandler()])


def estimate_audio_duration(text: str, words_per_minute: float = 150.0) -> float:
    """
    Estimate audio duration based on text length.

    Args:
        text: Input text
        words_per_minute: Average speaking rate

    Returns:
        float: Estimated duration in seconds
    """
    if not text:
        return 0.0

    # Count words (simple whitespace split)
    word_count = len(text.split())

    # Calculate duration in seconds
    duration = (word_count / words_per_minute) * 60.0

    # Add some buffer for pauses and processing
    return duration * 1.1


def format_file_size(size_bytes: int) -> str:
    """
    Format file size in human-readable format.

    Args:
        size_bytes: Size in bytes

    Returns:
        str: Formatted size string
    """
    if size_bytes == 0:
        return "0 B"

    size_names = ["B", "KB", "MB", "GB"]
    i = 0
    size_float = float(size_bytes)

    while size_float >= 1024 and i < len(size_names) - 1:
        size_float /= 1024.0
        i += 1

    return f"{size_float:.1f} {size_names[i]}"
