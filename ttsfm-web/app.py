"""
TTSFM Web Application

A Flask web application that provides a user-friendly interface
for the TTSFM text-to-speech package.
"""

import logging
import os
import secrets
import time

try:
    from .websocket_handler import WebSocketTTSHandler
except ImportError:  # pragma: no cover - fallback when run as script
    from websocket_handler import WebSocketTTSHandler

from collections import defaultdict, deque
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerificationError
from dotenv import load_dotenv
from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    stream_with_context,
    url_for,
)
from flask_cors import CORS
from flask_socketio import SocketIO

# Import i18n support
from i18n import init_i18n, set_locale

# Import the TTSFM package
try:
    from ttsfm import AudioFormat, TTSClient, Voice, __version__ as PACKAGE_VERSION
    from ttsfm.audio import combine_audio_chunks
    from ttsfm.capabilities import get_capabilities
    from ttsfm.exceptions import (
        APIException,
        AudioProcessingException,
        NetworkException,
        ValidationException,
    )
    from ttsfm.utils import split_text_by_length
except ImportError:
    # Fallback for development when package is not installed
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from ttsfm import AudioFormat, TTSClient, Voice, __version__ as PACKAGE_VERSION
    from ttsfm.audio import combine_audio_chunks
    from ttsfm.capabilities import get_capabilities
    from ttsfm.exceptions import APIException, NetworkException, ValidationException
    from ttsfm.utils import split_text_by_length

# Load environment variables
load_dotenv()

DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

APP_ROOT = Path(__file__).resolve().parent
INSTANCE_PATH = APP_ROOT / "instance"

# Create Flask app
app = Flask(
    __name__,
    static_folder="static",
    static_url_path="/static",
    root_path=str(APP_ROOT),
    instance_path=str(INSTANCE_PATH),
)

_DEFAULT_DEV_SECRET = "ttsfm-secret-key-change-in-production"
_secret_key = os.getenv("SECRET_KEY", _DEFAULT_DEV_SECRET)
if not DEBUG and _secret_key == _DEFAULT_DEV_SECRET:
    _secret_key = secrets.token_hex(32)
    logger.warning(
        "SECRET_KEY was not set; using an ephemeral secret for this process. "
        "Set SECRET_KEY for stable sessions across restarts (e.g. secrets.token_hex(32))."
    )
app.secret_key = _secret_key
app.config["PACKAGE_VERSION"] = PACKAGE_VERSION

_cors_raw = os.getenv("TTSFM_CORS_ORIGINS", "").strip()
if _cors_raw and _cors_raw != "*":
    _cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]
    CORS(app, origins=_cors_origins, supports_credentials=True)
    _socketio_cors_origins = _cors_origins
    _socketio_credentials = True
else:
    CORS(app)
    _socketio_cors_origins = "*"
    _socketio_credentials = False


def _default_host() -> str:
    """Choose a sensible default bind host.

    Docker containers need to listen on all interfaces so port mappings work,
    while local installs can continue to use localhost.
    """

    # Common indicator that we're running inside a Docker container
    if os.path.exists("/.dockerenv"):
        return "0.0.0.0"

    return "localhost"


HOST = os.getenv("HOST", _default_host())
PORT = int(os.getenv("PORT", "8000"))

# Socket.IO async driver: eventlet (legacy default prod), threading (default DEBUG),
# or gevent (install optional extra ``web-gevent``, set TTSFM_SOCKETIO_ASYNC_MODE=gevent).
_default_socketio_async = "threading" if DEBUG else "eventlet"
_async_env = os.getenv("TTSFM_SOCKETIO_ASYNC_MODE", _default_socketio_async).strip().lower()
if _async_env not in ("eventlet", "threading", "gevent"):
    logger.warning(
        "Invalid TTSFM_SOCKETIO_ASYNC_MODE=%r; using %s", _async_env, _default_socketio_async
    )
    async_mode = _default_socketio_async
else:
    async_mode = _async_env

socketio = SocketIO(
    app,
    cors_allowed_origins=_socketio_cors_origins,
    async_mode=async_mode,
    logger=DEBUG,  # Enable logging in debug mode for troubleshooting
    engineio_logger=DEBUG,
    ping_timeout=60,  # Time to wait for pong response
    ping_interval=25,  # Interval between ping messages
    cors_credentials=_socketio_credentials,
    manage_session=False,  # Don't interfere with Flask sessions
)

# Initialize i18n support
init_i18n(app)


@app.context_processor
def _inject_package_version():
    return {"package_version": app.config.get("PACKAGE_VERSION", "unknown")}


# API Key configuration
REQUIRE_API_KEY = os.getenv("REQUIRE_API_KEY", "false").lower() == "true"

ARGON2_HASH_PREFIXES = ("$argon2i$", "$argon2d$", "$argon2id$")
PASSWORD_HASHER = PasswordHasher()


def _load_api_key_material() -> Tuple[List[str], List[str]]:
    """Load plaintext API keys and Argon2 hashes from the environment."""
    plain_keys: List[str] = []
    prehashed_entries: List[str] = []

    hashed_env = os.getenv("TTSFM_API_KEY_HASHES")
    if hashed_env:
        prehashed_entries.extend([item.strip() for item in hashed_env.split(",") if item.strip()])

    multi_keys = os.getenv("TTSFM_API_KEYS")
    if multi_keys:
        plain_keys.extend([item.strip() for item in multi_keys.split(",") if item.strip()])

    single_key = os.getenv("TTSFM_API_KEY")
    if single_key:
        plain_keys.append(single_key.strip())

    hashes: List[str] = []
    for entry in prehashed_entries:
        if entry.startswith(ARGON2_HASH_PREFIXES):
            hashes.append(entry)
        elif entry:
            logger.warning("Ignoring unsupported API key hash format; expected Argon2 hashes.")

    stored_plain = [key for key in plain_keys if key]
    return stored_plain, hashes


PLAIN_API_KEYS, API_KEY_HASHES = _load_api_key_material()
API_KEYS_CONFIGURED = bool(PLAIN_API_KEYS or API_KEY_HASHES)

RATE_LIMIT_WINDOW = int(os.getenv("TTSFM_AUTH_WINDOW_SECONDS", "60"))
RATE_LIMIT_ATTEMPTS = int(os.getenv("TTSFM_AUTH_MAX_ATTEMPTS", "5"))
_MAX_FAILED_AUTH_IPS = int(os.getenv("TTSFM_AUTH_MAX_TRACKED_IPS", "5000"))
_FAILED_AUTH_ATTEMPTS: Dict[str, deque] = defaultdict(deque)


def create_tts_client() -> TTSClient:
    """Factory returning an isolated TTS client per request."""
    default_prompt = os.getenv("TTSFM_DEFAULT_PROMPT", "false").lower() == "true"
    return TTSClient(use_default_prompt=default_prompt)


# API Key validation decorator


def require_api_key(f):
    """Decorator to require API key for protected endpoints."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Skip API key check if not required
        if not REQUIRE_API_KEY:
            return f(*args, **kwargs)

        # Check if API key is configured
        if not API_KEYS_CONFIGURED:
            logger.warning("API key protection is enabled but no API keys are configured")
            return jsonify({"error": "Authentication service is unavailable"}), 500

        # Get API key from request headers - prioritize Authorization header
        # (OpenAI compatible)
        provided_key = None

        # 1. Check Authorization header first (OpenAI standard)
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            provided_key = auth_header[7:]  # Remove 'Bearer ' prefix

        # 2. Check X-API-Key header as fallback
        if not provided_key:
            provided_key = request.headers.get("X-API-Key")

        # 3. Check API key from query parameters as fallback
        if not provided_key:
            provided_key = request.args.get("api_key")

        # 4. Check API key from JSON body as fallback
        if not provided_key and request.is_json:
            data = request.get_json(silent=True)
            if data:
                provided_key = data.get("api_key")

        client_ip = request.remote_addr or "unknown"

        if _is_rate_limited(client_ip):
            logger.warning("Authentication rate limit exceeded for %s", client_ip)
            return jsonify({"error": "Too many authentication attempts"}), 429

        # Validate API key
        if not _is_valid_api_key(provided_key):
            _register_failed_attempt(client_ip)
            logger.warning("Invalid API key attempt from %s", client_ip)
            return jsonify({"error": "Authentication failed"}), 401

        _reset_failed_attempts(client_ip)

        return f(*args, **kwargs)

    return decorated_function


def _is_valid_api_key(provided: Optional[str]) -> bool:
    if not provided:
        return False

    for key in PLAIN_API_KEYS:
        if len(provided) == len(key) and secrets.compare_digest(provided, key):
            return True

    for stored_hash in API_KEY_HASHES:
        if not stored_hash.startswith(ARGON2_HASH_PREFIXES):
            logger.warning("Unsupported API key hash format encountered; ignoring entry.")
            continue

        try:
            PASSWORD_HASHER.verify(stored_hash, provided)
        except InvalidHash:
            logger.warning("Skipping invalid API key hash entry in configuration.")
            continue
        except VerificationError:
            continue
        else:
            return True

    return False


def _prune_failed_auth_map() -> None:
    while len(_FAILED_AUTH_ATTEMPTS) > _MAX_FAILED_AUTH_IPS:
        first_ip = next(iter(_FAILED_AUTH_ATTEMPTS))
        del _FAILED_AUTH_ATTEMPTS[first_ip]


def _register_failed_attempt(ip: str) -> None:
    attempts = _FAILED_AUTH_ATTEMPTS[ip]
    now = time.monotonic()
    attempts.append(now)
    _trim_attempts(attempts, now)
    _prune_failed_auth_map()


def _reset_failed_attempts(ip: str) -> None:
    _FAILED_AUTH_ATTEMPTS.pop(ip, None)


def _trim_attempts(attempts: deque, now: float) -> None:
    while attempts and now - attempts[0] > RATE_LIMIT_WINDOW:
        attempts.popleft()


def _is_rate_limited(ip: str) -> bool:
    attempts = _FAILED_AUTH_ATTEMPTS.get(ip)
    if attempts is None:
        return False
    now = time.monotonic()
    _trim_attempts(attempts, now)
    if not attempts:
        _FAILED_AUTH_ATTEMPTS.pop(ip, None)
        return False
    return len(attempts) >= RATE_LIMIT_ATTEMPTS


def _chunk_bytes(data: bytes, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
    view = memoryview(data)
    for offset in range(0, len(view), chunk_size):
        yield bytes(view[offset : offset + chunk_size])


def _is_safe_url(target: Optional[str]) -> bool:
    """Validate that a target URL is safe for redirection.

    Allows only relative URLs or absolute URLs that match this server's host
    and http/https schemes. Prevents open redirects to external domains.
    """
    if not target:
        return False

    if "\\" in target:
        return False

    parsed = urlparse(target)
    # Reject if scheme or netloc is present, or if it starts with //
    if parsed.scheme or parsed.netloc or target.startswith("//"):
        return False
    # Only allow paths starting with /
    if not parsed.path.startswith("/"):
        return False
    joined = urljoin(request.host_url, target)
    host = urlparse(request.host_url)
    j = urlparse(joined)
    return j.scheme in ("http", "https") and j.netloc == host.netloc


websocket_handler = WebSocketTTSHandler(
    socketio,
    create_tts_client,
    auth_context={
        "require_api_key": REQUIRE_API_KEY,
        "api_keys_configured": API_KEYS_CONFIGURED,
        "is_valid_api_key": _is_valid_api_key,
        "is_rate_limited": _is_rate_limited,
        "register_failed": _register_failed_attempt,
        "reset_failed_attempts": _reset_failed_attempts,
    },
)

logger.info("Initialized web app with TTSFM using openai.fm free service")
logger.info("WebSocket support enabled with %s async mode", async_mode)


@app.route("/set-language/<lang_code>")
def set_language(lang_code):
    """Set the user's language preference."""
    if set_locale(lang_code):
        # Redirect back only if the referrer is safe; otherwise go home
        target = request.referrer
        if _is_safe_url(target):
            return redirect(target)
        return redirect(url_for("index"))
    else:
        # Invalid language code, redirect to home
        return redirect(url_for("index"))


@app.route("/")
def index():
    """Serve the main web interface."""
    return render_template("index.html")


@app.route("/playground")
def playground():
    """Serve the interactive playground."""
    return render_template("playground.html")


@app.route("/docs")
def docs():
    """Serve the API documentation."""
    return render_template("docs.html")


@app.route("/websocket-demo")
def websocket_demo():
    """Serve the WebSocket streaming demo page."""
    return render_template("websocket_demo.html")


@app.route("/api/voices", methods=["GET"])
def get_voices():
    """Get list of available voices."""
    try:
        voices = [
            {
                "id": voice.value,
                "name": voice.value.title(),
                "description": f"{voice.value.title()} voice",
            }
            for voice in Voice
        ]

        return jsonify({"voices": voices, "count": len(voices)})

    except Exception as e:
        logger.error(f"Error getting voices: {e}")
        return jsonify({"error": "Failed to get voices"}), 500


@app.route("/api/formats", methods=["GET"])
def get_formats():
    """Get list of supported audio formats."""
    try:
        formats = [
            {
                "id": "mp3",
                "name": "MP3",
                "mime_type": "audio/mpeg",
                "description": "MP3 audio format - good quality, small file size",
                "quality": "Good",
                "file_size": "Small",
                "use_case": "Web, mobile apps, general use",
            },
            {
                "id": "opus",
                "name": "OPUS",
                "mime_type": "audio/opus",
                "description": "OPUS audio format - excellent quality, small file size",
                "quality": "Excellent",
                "file_size": "Small",
                "use_case": "Web streaming, VoIP",
            },
            {
                "id": "aac",
                "name": "AAC",
                "mime_type": "audio/aac",
                "description": "AAC audio format - good quality, medium file size",
                "quality": "Good",
                "file_size": "Medium",
                "use_case": "Apple devices, streaming",
            },
            {
                "id": "flac",
                "name": "FLAC",
                "mime_type": "audio/flac",
                "description": "FLAC audio format - lossless quality, large file size",
                "quality": "Lossless",
                "file_size": "Large",
                "use_case": "High-quality archival",
            },
            {
                "id": "wav",
                "name": "WAV",
                "mime_type": "audio/wav",
                "description": "WAV audio format - lossless quality, large file size",
                "quality": "Lossless",
                "file_size": "Large",
                "use_case": "Professional audio",
            },
            {
                "id": "pcm",
                "name": "PCM",
                "mime_type": "audio/pcm",
                "description": "PCM audio format - raw audio data, large file size",
                "quality": "Raw",
                "file_size": "Large",
                "use_case": "Audio processing",
            },
        ]

        return jsonify({"formats": formats, "count": len(formats)})

    except Exception as e:
        logger.error(f"Error getting formats: {e}")
        return jsonify({"error": "Failed to get formats"}), 500


@app.route("/api/validate-text", methods=["POST"])
@require_api_key
def validate_text():
    """Validate text length and provide splitting suggestions."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        text = data.get("text", "").strip()
        max_length = data.get("max_length", 1000)

        if not text:
            return jsonify({"error": "Text is required"}), 400

        text_length = len(text)
        is_valid = text_length <= max_length

        result = {
            "text_length": text_length,
            "max_length": max_length,
            "is_valid": is_valid,
            "needs_splitting": not is_valid,
        }

        if not is_valid:
            # Provide splitting suggestions
            chunks = split_text_by_length(text, max_length, preserve_words=True)
            result.update(
                {
                    "suggested_chunks": len(chunks),
                    "chunk_preview": [
                        chunk[:100] + "..." if len(chunk) > 100 else chunk for chunk in chunks[:3]
                    ],
                }
            )

        return jsonify(result)

    except Exception as e:
        logger.error(f"Text validation error: {e}")
        return jsonify({"error": "Text validation failed"}), 500


@app.route("/api/status", methods=["GET"])
def get_status():
    """Get service status."""
    try:
        with create_tts_client() as client:
            probe_url = client.base_url.rstrip("/") + "/"
            probe = None
            try:
                probe = client.session.head(probe_url, timeout=(2.0, 4.0), allow_redirects=True)
            except Exception:
                probe = None
            if probe is None or probe.status_code == 405:
                if probe is not None:
                    probe.close()
                probe = client.session.get(probe_url, timeout=(2.0, 4.0), stream=True)
            status = probe.status_code
            probe.close()
            if status >= 500:
                raise RuntimeError(f"upstream returned HTTP {status}")

        return jsonify(
            {
                "status": "online",
                "tts_service": "openai.fm (free)",
                "package_version": app.config.get("PACKAGE_VERSION", "unknown"),
                "timestamp": datetime.now().isoformat(),
            }
        )

    except Exception as e:
        logger.error(f"Status check failed: {e}")
        return (
            jsonify(
                {
                    "status": "error",
                    "tts_service": "openai.fm (free)",
                    "error": "Service status check failed",
                    "timestamp": datetime.now().isoformat(),
                }
            ),
            503,
        )


@app.route("/api/health", methods=["GET"])
def health_check():
    """Health check endpoint with capabilities info."""
    caps = get_capabilities()
    return jsonify(
        {
            "status": "healthy",
            "package_version": app.config.get("PACKAGE_VERSION", "unknown"),
            "image_variant": caps.get_capabilities()["image_variant"],
            "ffmpeg_available": caps.ffmpeg_available,
            "timestamp": datetime.now().isoformat(),
        }
    )


@app.route("/api/capabilities", methods=["GET"])
def get_system_capabilities():
    """Get system capabilities and available features."""
    caps = get_capabilities()
    return jsonify(caps.get_capabilities())


@app.route("/api/websocket/status", methods=["GET"])
def websocket_status():
    """Get WebSocket server status and active connections."""
    return jsonify(
        {
            "websocket_enabled": True,
            "async_mode": async_mode,
            "active_sessions": websocket_handler.get_active_sessions_count(),
            "transport_options": ["websocket", "polling"],
            "endpoint": f"ws{'s' if request.is_secure else ''}://{request.host}/socket.io/",
            "timestamp": datetime.now().isoformat(),
        }
    )


@app.route("/api/auth-status", methods=["GET"])
def auth_status():
    """Get authentication status and requirements."""
    return jsonify(
        {
            "api_key_required": REQUIRE_API_KEY,
            "api_key_configured": API_KEYS_CONFIGURED if REQUIRE_API_KEY else None,
            "timestamp": datetime.now().isoformat(),
        }
    )


@app.route("/api/translations/<lang_code>", methods=["GET"])
def get_translations(lang_code):
    """Get translations for a specific language."""
    try:
        if hasattr(app, "language_manager"):
            translations = app.language_manager.translations.get(lang_code, {})
            return jsonify(translations)
        else:
            return jsonify({}), 404
    except Exception as e:
        logger.error(f"Error getting translations for {lang_code}: {e}")
        return jsonify({"error": "Failed to get translations"}), 500


# OpenAI-compatible API endpoints


@app.route("/v1/audio/speech", methods=["POST"])
@require_api_key
def openai_speech():
    """OpenAI-compatible speech generation endpoint with auto-combine feature."""
    try:
        # Parse request data
        data = request.get_json()
        if not data:
            return (
                jsonify(
                    {
                        "error": {
                            "message": "No JSON data provided",
                            "type": "invalid_request_error",
                            "code": "missing_data",
                        }
                    }
                ),
                400,
            )

        # Extract OpenAI-compatible parameters
        input_text = data.get("input", "").strip()
        voice = data.get("voice", "alloy")
        response_format = data.get("response_format", "mp3")
        instructions = data.get("instructions", "").strip() or None
        speed = data.get("speed")  # Optional: 0.25 to 4.0

        # TTSFM-specific parameters
        # New parameter: auto-combine long text (default: True)
        auto_combine = data.get("auto_combine", True)
        # Custom parameter for chunk size
        max_length = data.get("max_length", 1000)
        try:
            max_length = int(max_length)
        except (TypeError, ValueError):
            return (
                jsonify(
                    {
                        "error": {
                            "message": "max_length must be an integer",
                            "type": "invalid_request_error",
                            "code": "invalid_max_length",
                        }
                    }
                ),
                400,
            )
        if max_length < 1 or max_length > 1000:
            return (
                jsonify(
                    {
                        "error": {
                            "message": "max_length must be between 1 and 1000",
                            "type": "invalid_request_error",
                            "code": "invalid_max_length",
                        }
                    }
                ),
                400,
            )

        # Validate required fields
        if not input_text:
            return (
                jsonify(
                    {
                        "error": {
                            "message": "Input text is required",
                            "type": "invalid_request_error",
                            "code": "missing_input",
                        }
                    }
                ),
                400,
            )

        # Validate voice
        try:
            voice_enum = Voice(voice.lower())
        except ValueError:
            voice_options = ", ".join(v.value for v in Voice)
            return (
                jsonify(
                    {
                        "error": {
                            "message": (f"Invalid voice: {voice}. Must be one of: {voice_options}"),
                            "type": "invalid_request_error",
                            "code": "invalid_voice",
                        }
                    }
                ),
                400,
            )

        # Validate format
        try:
            format_enum = AudioFormat(response_format.lower())
        except ValueError:
            format_options = ", ".join(fmt.value for fmt in AudioFormat)
            return (
                jsonify(
                    {
                        "error": {
                            "message": (
                                "Invalid response_format: "
                                f"{response_format}. Must be one of: {format_options}"
                            ),
                            "type": "invalid_request_error",
                            "code": "invalid_format",
                        }
                    }
                ),
                400,
            )

        # Validate speed parameter if provided
        if speed is not None:
            try:
                speed = float(speed)
                if not 0.25 <= speed <= 4.0:
                    return (
                        jsonify(
                            {
                                "error": {
                                    "message": "Speed must be between 0.25 and 4.0",
                                    "type": "invalid_request_error",
                                    "code": "invalid_speed",
                                }
                            }
                        ),
                        400,
                    )
            except (ValueError, TypeError):
                return (
                    jsonify(
                        {
                            "error": {
                                "message": "Speed must be a number",
                                "type": "invalid_request_error",
                                "code": "invalid_speed",
                            }
                        }
                    ),
                    400,
                )

        # Check feature availability before processing
        caps = get_capabilities()

        # Check if requested format requires ffmpeg
        if format_enum.value in ["opus", "aac", "flac", "pcm"] and not caps.ffmpeg_available:
            return (
                jsonify(
                    {
                        "error": {
                            "message": f"Format '{format_enum.value}' requires ffmpeg. "
                            f"Available formats: {', '.join(caps.get_supported_formats())}",
                            "type": "feature_unavailable_error",
                            "code": "ffmpeg_required",
                            "available_formats": caps.get_supported_formats(),
                            "hint": "Use the full Docker image (dbcccc/ttsfm:latest) instead of the slim variant.",
                        }
                    }
                ),
                400,
            )

        # Check if speed adjustment requires ffmpeg
        if speed is not None and speed != 1.0 and not caps.ffmpeg_available:
            return (
                jsonify(
                    {
                        "error": {
                            "message": "Speed adjustment requires ffmpeg. "
                            "Use the full Docker image (dbcccc/ttsfm:latest).",
                            "type": "feature_unavailable_error",
                            "code": "ffmpeg_required",
                            "hint": "Speed adjustment is only available in the full Docker image.",
                        }
                    }
                ),
                400,
            )

        # Check if MP3 auto-combine requires ffmpeg (for long text)
        if (
            len(input_text) > max_length
            and auto_combine
            and format_enum == AudioFormat.MP3
            and not caps.ffmpeg_available
        ):
            return (
                jsonify(
                    {
                        "error": {
                            "message": "MP3 auto-combine for long text requires ffmpeg. "
                            "Use WAV format, disable auto_combine, or use the full Docker image.",
                            "type": "feature_unavailable_error",
                            "code": "ffmpeg_required",
                            "hint": "MP3 auto-combine is only available in the full Docker image.",
                        }
                    }
                ),
                400,
            )

        logger.info(
            "OpenAI API: Generating speech: text='%s...', voice=%s, "
            "requested_format=%s, auto_combine=%s, speed=%s",
            input_text[:50],
            voice,
            response_format,
            auto_combine,
            speed,
        )

        client = create_tts_client()
        try:
            if len(input_text) > max_length and auto_combine:
                logger.info(
                    "Long text detected (%s chars); auto-combining with format %s",
                    len(input_text),
                    format_enum.value,
                )

                responses = client.generate_speech_long_text(
                    text=input_text,
                    voice=voice_enum,
                    response_format=format_enum,
                    instructions=instructions,
                    max_length=max_length,
                    preserve_words=True,
                    speed=speed,
                )

                if not responses:
                    return (
                        jsonify(
                            {
                                "error": {
                                    "message": "No valid text chunks found",
                                    "type": "processing_error",
                                    "code": "no_chunks",
                                }
                            }
                        ),
                        400,
                    )

                audio_chunks = [resp.audio_data for resp in responses]
                actual_format = responses[0].format
                combined_audio = combine_audio_chunks(audio_chunks, actual_format.value)

                if not combined_audio:
                    return (
                        jsonify(
                            {
                                "error": {
                                    "message": "Failed to combine audio chunks",
                                    "type": "processing_error",
                                    "code": "combine_failed",
                                }
                            }
                        ),
                        500,
                    )

                content_type = responses[0].content_type

                logger.info(
                    "Successfully combined %s chunks into single audio file",
                    len(responses),
                )

                headers = {
                    "Content-Type": content_type,
                    "X-Audio-Format": actual_format.value,
                    "X-Audio-Size": str(len(combined_audio)),
                    "X-Chunks-Combined": str(len(responses)),
                    "X-Original-Text-Length": str(len(input_text)),
                    "X-Auto-Combine": "true",
                    "X-Powered-By": "TTSFM-OpenAI-Compatible",
                    "X-Requested-Format": format_enum.value,
                }

                if (
                    responses
                    and responses[0].metadata
                    and "requested_speed" in responses[0].metadata
                ):
                    headers["X-Requested-Speed"] = str(responses[0].metadata["requested_speed"])
                    headers["X-Speed-Applied"] = str(
                        responses[0].metadata.get("speed_applied", False)
                    ).lower()

                return Response(
                    stream_with_context(_chunk_bytes(combined_audio)),
                    mimetype=content_type,
                    headers=headers,
                    direct_passthrough=True,
                )

            if len(input_text) > max_length and not auto_combine:
                return (
                    jsonify(
                        {
                            "error": {
                                "message": (
                                    f"Input text is too long ({len(input_text)} characters). "
                                    f"Maximum allowed length is {max_length} characters. "
                                    "Enable the auto_combine parameter to split and combine "
                                    "long input automatically."
                                ),
                                "type": "invalid_request_error",
                                "code": "text_too_long",
                            }
                        }
                    ),
                    400,
                )

            response = client.generate_speech(
                text=input_text,
                voice=voice_enum,
                response_format=format_enum,
                instructions=instructions,
                max_length=max_length,
                validate_length=True,
                speed=speed,
            )

            headers = {
                "Content-Type": response.content_type,
                "X-Audio-Format": response.format.value,
                "X-Audio-Size": str(response.size),
                "X-Chunks-Combined": "1",
                "X-Auto-Combine": str(auto_combine).lower(),
                "X-Powered-By": "TTSFM-OpenAI-Compatible",
                "X-Requested-Format": format_enum.value,
            }

            if response.metadata and "requested_speed" in response.metadata:
                headers["X-Requested-Speed"] = str(response.metadata["requested_speed"])
                headers["X-Speed-Applied"] = str(
                    response.metadata.get("speed_applied", False)
                ).lower()

            return Response(
                stream_with_context(_chunk_bytes(response.audio_data)),
                mimetype=response.content_type,
                headers=headers,
                direct_passthrough=True,
            )
        finally:
            client.close()

    except ValidationException as e:
        logger.warning(f"OpenAI API validation error: {e}")
        return (
            jsonify(
                {
                    "error": {
                        "message": "Invalid request parameters",
                        "type": "invalid_request_error",
                        "code": "validation_error",
                    }
                }
            ),
            400,
        )

    except APIException as e:
        logger.error(f"OpenAI API error: {e}")
        return jsonify(
            {
                "error": {
                    "message": "Text-to-speech generation failed",
                    "type": "api_error",
                    "code": "tts_error",
                }
            }
        ), getattr(e, "status_code", 500)

    except NetworkException as e:
        logger.error(f"OpenAI API network error: {e}")
        return (
            jsonify(
                {
                    "error": {
                        "message": "TTS service is currently unavailable",
                        "type": "service_unavailable_error",
                        "code": "service_unavailable",
                    }
                }
            ),
            503,
        )

    except AudioProcessingException as e:
        logger.error(f"OpenAI API audio processing error: {e}")
        return (
            jsonify(
                {
                    "error": {
                        "message": str(e.message),
                        "type": "audio_processing_error",
                        "code": "audio_processing_error",
                    }
                }
            ),
            400,
        )

    except RuntimeError as e:
        # Catch ffmpeg-related errors from audio_processing module
        error_msg = str(e)
        logger.error(f"OpenAI API runtime error: {error_msg}")

        # Check if it's an ffmpeg-related error
        if "ffmpeg" in error_msg.lower():
            return (
                jsonify(
                    {
                        "error": {
                            "message": "FFmpeg is not available in this environment",
                            "type": "feature_unavailable_error",
                            "code": "ffmpeg_required",
                            "hint": "This feature requires the full Docker image. "
                            "Use dbcccc/ttsfm:latest instead of the slim variant.",
                        }
                    }
                ),
                400,
            )
        # Re-raise if not ffmpeg-related
        raise

    except Exception as e:
        logger.error(f"OpenAI API unexpected error: {e}")
        return (
            jsonify(
                {
                    "error": {
                        "message": "An unexpected error occurred",
                        "type": "internal_error",
                        "code": "internal_error",
                    }
                }
            ),
            500,
        )


@app.route("/v1/models", methods=["GET"])
def openai_models():
    """OpenAI-compatible models endpoint."""
    return jsonify(
        {
            "object": "list",
            "data": [
                {
                    "id": "gpt-4o-mini-tts",
                    "object": "model",
                    "created": 1699564800,
                    "owned_by": "ttsfm",
                    "permission": [],
                    "root": "gpt-4o-mini-tts",
                    "parent": None,
                }
            ],
        }
    )


@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    return jsonify({"error": "Endpoint not found"}), 404


@app.errorhandler(405)
def method_not_allowed(error):
    """Handle 405 errors."""
    return jsonify({"error": "Method not allowed"}), 405


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    logger.error(f"Internal server error: {error}")
    return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    logger.info(f"Starting TTSFM web application on {HOST}:{PORT}")
    logger.info("Using openai.fm free TTS service")
    logger.info(f"Debug mode: {DEBUG}")

    # Log API key protection status
    if REQUIRE_API_KEY:
        if API_KEYS_CONFIGURED:
            logger.info("🔒 API key protection is ENABLED")
            logger.info("All TTS generation requests require a valid API key")
        else:
            logger.warning(
                "⚠️ API key protection is enabled but TTSFM_API_KEY(S) are not configured!"
            )
            logger.warning("Please set the TTSFM_API_KEY or TTSFM_API_KEYS environment variables")
    else:
        logger.info("🔓 API key protection is DISABLED - all requests are allowed")
        logger.info("Set REQUIRE_API_KEY=true to enable API key protection")

    try:
        logger.info(f"Starting with {async_mode} async mode")
        socketio.run(app, host=HOST, port=PORT, debug=DEBUG)
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    except Exception as e:
        logger.error(f"Failed to start application: {e}")
    finally:
        logger.info("TTSFM web application shut down")
