"""
Main TTS client implementation.

This module provides the primary TTSClient class for synchronous
text-to-speech generation with OpenAI-compatible API.
"""

import json
import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple, Union

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .audio import combine_responses
from .exceptions import (
    APIException,
    NetworkException,
    TTSException,
    ValidationException,
    create_exception_from_response,
)
from .models import (
    AudioFormat,
    TTSRequest,
    TTSResponse,
    Voice,
)
from .utils import (
    build_url,
    estimate_audio_duration,
    exponential_backoff,
    format_file_size,
    get_realistic_headers,
    resolve_api_key,
    safe_response_headers_for_metadata,
    sanitize_text,
    split_text_by_length,
    validate_url,
)

logger = logging.getLogger(__name__)


class TTSClient:
    """
    Synchronous TTS client for text-to-speech generation.

    This client provides a simple interface for generating speech from text
    using OpenAI-compatible TTS services.

    Attributes:
        base_url: Base URL for the TTS service
        api_key: API key for authentication (if required)
        timeout: Request timeout in seconds
        max_retries: Maximum number of retry attempts
        verify_ssl: Whether to verify SSL certificates
    """

    def __init__(
        self,
        base_url: str = "https://www.openai.fm",
        api_key: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        verify_ssl: bool = True,
        preferred_format: Optional[AudioFormat] = None,
        default_headers: Optional[Dict[str, str]] = None,
        use_default_prompt: bool = False,
        **kwargs,  # type: ignore[no-untyped-def]
    ) -> None:
        """
        Initialize the TTS client.

        Args:
            base_url: Base URL for the TTS service
            api_key: API key for authentication
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts
            verify_ssl: Whether to verify SSL certificates
            preferred_format: Preferred audio format (affects header selection)
            **kwargs: Additional configuration options
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = resolve_api_key(api_key)
        self.timeout = timeout
        self.max_retries = max_retries
        self.verify_ssl = verify_ssl
        self.preferred_format = preferred_format or AudioFormat.WAV
        self.use_default_prompt = use_default_prompt
        self.default_headers = default_headers or {}

        # Validate base URL
        if not validate_url(self.base_url):
            raise ValidationException(f"Invalid base URL: {self.base_url}")

        # Setup HTTP session with retry strategy
        self.session = requests.Session()
        self._session_lock = threading.RLock()

        # Configure retry strategy
        retry_strategy = Retry(
            total=max_retries,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST"],  # Updated parameter name
            backoff_factor=1,
        )

        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=10)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        # Set default headers
        base_headers = get_realistic_headers(self.default_headers)
        self.session.headers.update(base_headers)

        if self.api_key:
            self.session.headers["Authorization"] = f"Bearer {self.api_key}"

        logger.info(f"Initialized TTS client with base URL: {self.base_url}")

    def _spawn_worker_session(self) -> requests.Session:
        """Create an isolated Session for concurrent chunk requests (thread-safe)."""
        sess = requests.Session()
        retry_strategy = Retry(
            total=self.max_retries,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST"],
            backoff_factor=1,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=4, pool_maxsize=4)
        sess.mount("http://", adapter)
        sess.mount("https://", adapter)
        base_headers = get_realistic_headers(self.default_headers)
        sess.headers.update(base_headers)
        if self.api_key:
            sess.headers["Authorization"] = f"Bearer {self.api_key}"
        return sess

    def _get_headers_for_format(self, requested_format: AudioFormat) -> Dict[str, str]:
        """
        Get appropriate headers to get the desired base format from openai.fm.

        Based on testing, openai.fm returns:
        - MP3: When using minimal headers
        - WAV: When using more complex headers with specific Accept values

        We request MP3 or WAV from openai.fm, then convert to other formats using ffmpeg.

        Args:
            requested_format: The desired audio format

        Returns:
            Dict[str, str]: HTTP headers optimized for the base format
        """
        # For MP3, use minimal headers
        if requested_format == AudioFormat.MP3:
            return {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

        # For all other formats, request WAV from openai.fm (we'll convert later if needed)
        # Use more complex headers to get WAV response
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            "Accept": "audio/*,*/*;q=0.9",
        }

    def _get_content_type_for_format(self, audio_format: AudioFormat) -> str:
        """
        Get the appropriate MIME type for an audio format.

        Args:
            audio_format: The audio format

        Returns:
            str: The MIME type for the format
        """
        format_to_mime = {
            AudioFormat.MP3: "audio/mpeg",
            AudioFormat.WAV: "audio/wav",
            AudioFormat.OPUS: "audio/opus",
            AudioFormat.AAC: "audio/aac",
            AudioFormat.FLAC: "audio/flac",
            AudioFormat.PCM: "audio/pcm",
        }
        return format_to_mime.get(audio_format, "audio/mpeg")

    def generate_speech(
        self,
        text: str,
        voice: Union[Voice, str] = Voice.ALLOY,
        response_format: Union[AudioFormat, str] = AudioFormat.MP3,
        instructions: Optional[str] = None,
        max_length: int = 1000,
        validate_length: bool = True,
        **kwargs,  # type: ignore[no-untyped-def]
    ) -> TTSResponse:
        """
        Generate speech from text.

        Args:
            text: Text to convert to speech
            voice: Voice to use for generation
            response_format: Audio format for output
            instructions: Optional instructions for voice modulation
            max_length: Maximum allowed text length in characters (default: 1000)
            validate_length: Whether to validate text length (default: True)
            **kwargs: Additional parameters

        Returns:
            TTSResponse: Generated audio response

        Raises:
            TTSException: If generation fails
            ValueError: If text exceeds max_length and validate_length is True
        """
        # Create and validate request
        request = TTSRequest(
            input=sanitize_text(text),
            voice=voice,
            response_format=response_format,
            instructions=instructions,
            max_length=max_length,
            validate_length=validate_length,
            **kwargs,
        )

        return self._make_request(request)

    def generate_speech_from_request(self, request: TTSRequest) -> TTSResponse:
        """
        Generate speech from a TTSRequest object.

        Args:
            request: TTS request object

        Returns:
            TTSResponse: Generated audio response
        """
        return self._make_request(request)

    def generate_speech_batch(
        self,
        text: str,
        voice: Union[Voice, str] = Voice.ALLOY,
        response_format: Union[AudioFormat, str] = AudioFormat.MP3,
        instructions: Optional[str] = None,
        max_length: int = 1000,
        preserve_words: bool = True,
        max_concurrent_chunks: Optional[int] = None,
        **kwargs,  # type: ignore[no-untyped-def]
    ) -> List[TTSResponse]:
        """
        Generate speech from long text by splitting it into chunks.

        This method automatically splits text that exceeds max_length into
        smaller chunks and generates speech for each chunk separately.

        Args:
            text: Text to convert to speech
            voice: Voice to use for generation
            response_format: Audio format for output
            instructions: Optional instructions for voice modulation
            max_length: Maximum length per chunk (default: 1000)
            preserve_words: Whether to avoid splitting words (default: True)
            max_concurrent_chunks: Max parallel HTTP workers for chunk requests (default: env
                ``TTSFM_SYNC_LONG_TEXT_WORKERS`` or 4). Use ``1`` to force sequential requests.
            **kwargs: Additional parameters

        Returns:
            Union[TTSResponse, List[TTSResponse]]: Combined response when ``auto_combine``
            is True, otherwise the list of chunk responses

        Raises:
            TTSException: If generation fails for any chunk
        """

        # Sanitize text first
        clean_text = sanitize_text(text)

        # Split text into chunks
        chunks = split_text_by_length(clean_text, max_length, preserve_words)

        if not chunks:
            raise ValueError("No valid text chunks found after processing")

        if max_concurrent_chunks is None:
            try:
                workers = int(os.environ.get("TTSFM_SYNC_LONG_TEXT_WORKERS", "4"))
            except ValueError:
                workers = 4
        else:
            workers = int(max_concurrent_chunks)
        workers = max(1, min(workers, len(chunks)))

        worker_tls = threading.local()
        worker_sessions: List[requests.Session] = []
        sessions_lock = threading.Lock()

        def _get_worker_session() -> requests.Session:
            sess = getattr(worker_tls, "session", None)
            if sess is None:
                sess = self._spawn_worker_session()
                worker_tls.session = sess
                with sessions_lock:
                    worker_sessions.append(sess)
            return sess

        def _one_chunk(index: int, chunk: str) -> Tuple[int, TTSResponse]:
            request = TTSRequest(
                input=chunk,
                voice=voice,
                response_format=response_format,
                instructions=instructions,
                max_length=max_length,
                validate_length=False,
                **kwargs,
            )
            if workers == 1:
                return index, self._make_request(request)
            return index, self._make_request(request, http_session=_get_worker_session())

        if workers == 1:
            responses: List[TTSResponse] = []
            for i, chunk in enumerate(chunks):
                logger.info(
                    "Processing chunk %s/%s (%s characters)", i + 1, len(chunks), len(chunk)
                )
                _, response = _one_chunk(i, chunk)
                responses.append(response)
            return responses

        logger.info("Processing %s chunks with up to %s concurrent workers", len(chunks), workers)
        ordered: List[Optional[TTSResponse]] = [None] * len(chunks)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_one_chunk, i, c): i for i, c in enumerate(chunks)}
            for fut in as_completed(futures):
                index, response = fut.result()
                ordered[index] = response
        for sess in worker_sessions:
            try:
                sess.close()
            except OSError:
                pass
        return [r for r in ordered if r is not None]

    def generate_speech_long_text(
        self,
        text: str,
        voice: Union[Voice, str] = Voice.ALLOY,
        response_format: Union[AudioFormat, str] = AudioFormat.MP3,
        instructions: Optional[str] = None,
        max_length: int = 1000,
        preserve_words: bool = True,
        auto_combine: bool = False,
        max_concurrent_chunks: Optional[int] = None,
        **kwargs,  # type: ignore[no-untyped-def]
    ) -> Union[TTSResponse, List[TTSResponse]]:
        """
        Generate speech from long text by splitting it into chunks.

        This is an alias for generate_speech_batch for consistency with AsyncTTSClient.
        Automatically splits text that exceeds max_length into smaller chunks
        and generates speech for each chunk separately.

        Args:
            text: Text to convert to speech
            voice: Voice to use for generation
            response_format: Audio format for output
            instructions: Optional instructions for voice modulation
            max_length: Maximum length per chunk (default: 1000)
            preserve_words: Whether to avoid splitting words (default: True)
            **kwargs: Additional parameters

        Returns:
            Union[TTSResponse, List[TTSResponse]]: Combined response when ``auto_combine``
            is True, otherwise the list of chunk responses

        Raises:
            TTSException: If generation fails for any chunk
        """
        responses = self.generate_speech_batch(
            text=text,
            voice=voice,
            response_format=self._resolve_long_text_format(response_format, auto_combine),
            instructions=instructions,
            max_length=max_length,
            preserve_words=preserve_words,
            max_concurrent_chunks=max_concurrent_chunks,
            **kwargs,
        )

        if auto_combine:
            combined = combine_responses(responses)
            original_format = self._normalise_format_value(response_format)
            if combined.metadata is None:
                combined.metadata = {}
            combined.metadata.setdefault("actual_format", combined.format.value)
            if original_format != combined.format.value:
                combined.metadata["original_requested_format"] = original_format
            return combined

        return responses

    @staticmethod
    def _normalise_format_value(response_format: Union[AudioFormat, str]) -> str:
        if isinstance(response_format, AudioFormat):
            return response_format.value
        return str(response_format).lower()

    def _resolve_long_text_format(
        self,
        response_format: Union[AudioFormat, str],
        auto_combine: bool,
    ) -> Union[AudioFormat, str]:
        if not auto_combine:
            return response_format

        fmt_value = self._normalise_format_value(response_format)
        try:
            fmt_enum = AudioFormat(fmt_value)
        except ValueError:
            return AudioFormat.WAV

        if fmt_enum is AudioFormat.MP3:
            return AudioFormat.WAV

        return response_format

    def _make_request(
        self,
        request: TTSRequest,
        http_session: Optional[requests.Session] = None,
    ) -> TTSResponse:
        """
        Make the actual HTTP request to the openai.fm TTS service.

        Args:
            request: TTS request object
            http_session: Optional dedicated session (for parallel chunk requests).

        Returns:
            TTSResponse: Generated audio response

        Raises:
            TTSException: If request fails
        """
        url = build_url(self.base_url, "api/generate")

        # Prepare form data for openai.fm API
        voice_value = (
            request.voice.value if isinstance(request.voice, Voice) else str(request.voice)
        )
        format_value = (
            request.response_format.value
            if isinstance(request.response_format, AudioFormat)
            else str(request.response_format)
        )

        form_data = {
            "input": request.input,
            "voice": voice_value,
            "generation": str(uuid.uuid4()),
            "response_format": format_value,
        }

        # Add prompt/instructions if provided
        if request.instructions:
            form_data["prompt"] = request.instructions
        elif self.use_default_prompt:
            # Default prompt for better quality
            form_data["prompt"] = (
                "Affect/personality: Natural and clear\n\n"
                "Tone: Friendly and professional, creating a pleasant "
                "listening experience.\n\n"
                "Pronunciation: Clear, articulate, and steady, ensuring "
                "each word is easily understood while maintaining a "
                "natural, conversational flow.\n\n"
                "Pause: Brief, purposeful pauses between sentences to "
                "allow time for the listener to process the information.\n\n"
                "Emotion: Warm and engaging, conveying the intended "
                "message effectively."
            )
        # Convert string format to AudioFormat enum if needed
        requested_format = request.response_format
        if isinstance(requested_format, str):
            try:
                requested_format = AudioFormat(requested_format.lower())
            except ValueError:
                requested_format = AudioFormat.MP3  # Default to MP3 for unknown formats

        # Determine base format to request from openai.fm
        # We request MP3 or WAV, then convert to other formats using ffmpeg
        if requested_format == AudioFormat.MP3:
            base_format = AudioFormat.MP3
        else:
            # For all other formats (WAV, OPUS, AAC, FLAC, PCM), request WAV
            base_format = AudioFormat.WAV

        form_data["response_format"] = base_format.value
        format_headers = self._get_headers_for_format(requested_format)

        logger.info(
            f"Generating speech for text: '{request.input[:50]}...' with voice: {request.voice}"
        )
        logger.debug(
            f"Requesting {base_format.value} from openai.fm (target format: {requested_format.value})"
        )

        # Make request with retries
        for attempt in range(self.max_retries + 1):
            try:
                # Add random delay for rate limiting (except first attempt)
                if attempt > 0:
                    delay = exponential_backoff(attempt - 1)
                    logger.info(f"Retrying request after {delay:.2f}s (attempt {attempt + 1})")
                    time.sleep(delay)

                # Use multipart form data as required by openai.fm
                payload = dict(form_data)
                if http_session is not None:
                    response = http_session.post(
                        url,
                        data=payload,
                        headers=format_headers,
                        timeout=self.timeout,
                        verify=self.verify_ssl,
                    )
                else:
                    with self._session_lock:
                        response = self.session.post(
                            url,
                            data=payload,
                            headers=format_headers,
                            timeout=self.timeout,
                            verify=self.verify_ssl,
                        )

                # Handle different response types
                if response.status_code == 200:
                    return self._process_openai_fm_response(response, request)
                else:
                    # Try to parse error response
                    try:
                        error_data = response.json()
                    except (json.JSONDecodeError, ValueError):
                        error_data = {"error": {"message": response.text or "Unknown error"}}

                    # Create appropriate exception
                    exception = create_exception_from_response(
                        response.status_code,
                        error_data,
                        f"TTS request failed with status {response.status_code}",
                    )

                    # Don't retry for certain errors
                    if response.status_code in [400, 401, 403, 404]:
                        raise exception

                    # For retryable errors, continue to next attempt
                    if attempt == self.max_retries:
                        raise exception

                    logger.warning(
                        f"Request failed with status {response.status_code}, retrying..."
                    )
                    continue

            except requests.exceptions.Timeout:
                if attempt == self.max_retries:
                    raise NetworkException(
                        f"Request timed out after {self.timeout}s",
                        timeout=self.timeout,
                        retry_count=attempt,
                    )
                logger.warning("Request timed out, retrying...")
                continue

            except requests.exceptions.ConnectionError as e:
                if attempt == self.max_retries:
                    raise NetworkException(f"Connection error: {str(e)}", retry_count=attempt)
                logger.warning("Connection error, retrying...")
                continue

            except requests.exceptions.RequestException as e:
                if attempt == self.max_retries:
                    raise NetworkException(f"Request error: {str(e)}", retry_count=attempt)
                logger.warning("Request error, retrying...")
                continue

        # This should never be reached, but just in case
        raise TTSException("Maximum retries exceeded")

    def _process_openai_fm_response(
        self,
        response: requests.Response,
        request: TTSRequest,
    ) -> TTSResponse:
        """
        Process a successful response from the openai.fm TTS service.

        Args:
            response: HTTP response object
            request: Original TTS request

        Returns:
            TTSResponse: Processed response object
        """
        # Get content type from response headers
        content_type = response.headers.get("content-type", "audio/mpeg")

        # Get audio data
        audio_data = response.content

        if not audio_data:
            raise APIException("Received empty audio data from openai.fm")

        # Determine format from content type
        if "audio/mpeg" in content_type or "audio/mp3" in content_type:
            actual_format = AudioFormat.MP3
        elif "audio/wav" in content_type:
            actual_format = AudioFormat.WAV
        elif "audio/opus" in content_type:
            actual_format = AudioFormat.OPUS
        elif "audio/aac" in content_type:
            actual_format = AudioFormat.AAC
        elif "audio/flac" in content_type:
            actual_format = AudioFormat.FLAC
        else:
            # Default to MP3 for openai.fm
            actual_format = AudioFormat.MP3

        # Estimate duration based on text length (rough approximation)
        estimated_duration = estimate_audio_duration(request.input)

        # Normalize requested format
        requested_format = request.response_format
        if isinstance(requested_format, str):
            try:
                requested_format = AudioFormat(requested_format.lower())
            except ValueError:
                requested_format = AudioFormat.MP3  # Default fallback

        # Apply speed adjustment if requested (requires ffmpeg)
        speed_applied = False
        if request.speed is not None and request.speed != 1.0:
            try:
                from .audio_processing import adjust_audio_speed

                logger.info(f"Applying speed adjustment: {request.speed}x")
                audio_data = adjust_audio_speed(
                    audio_data,
                    speed=request.speed,
                    input_format=actual_format.value,
                    output_format=actual_format.value,
                )
                speed_applied = True
                # Adjust estimated duration based on speed
                if estimated_duration:
                    estimated_duration = estimated_duration / request.speed
            except RuntimeError as e:
                logger.warning(f"Speed adjustment failed: {e}")
                # Continue without speed adjustment
            except Exception as e:
                logger.error(f"Unexpected error during speed adjustment: {e}")
                # Continue without speed adjustment

        # Convert format if needed (requires ffmpeg for non-MP3/WAV formats)
        if actual_format != requested_format:
            # Check if conversion is needed
            if requested_format in [
                AudioFormat.OPUS,
                AudioFormat.AAC,
                AudioFormat.FLAC,
                AudioFormat.PCM,
            ]:
                try:
                    from .audio_processing import convert_audio_format

                    logger.info(
                        f"Converting audio from {actual_format.value} to {requested_format.value}"
                    )
                    audio_data = convert_audio_format(
                        audio_data,
                        input_format=actual_format.value,
                        output_format=requested_format.value,
                    )
                    actual_format = requested_format
                    # Update content type after conversion
                    content_type = self._get_content_type_for_format(requested_format)
                    logger.info(f"Successfully converted to {requested_format.value}")
                except RuntimeError as e:
                    logger.warning(
                        f"Format conversion failed: {e}. Returning {actual_format.value} format."
                    )
                    # Continue with original format
                except Exception as e:
                    logger.error(f"Unexpected error during format conversion: {e}")
                    # Continue with original format
            elif requested_format == AudioFormat.WAV and actual_format == AudioFormat.MP3:
                # Convert MP3 to WAV if requested
                try:
                    from .audio_processing import convert_audio_format

                    logger.info("Converting audio from MP3 to WAV")
                    audio_data = convert_audio_format(
                        audio_data,
                        input_format="mp3",
                        output_format="wav",
                    )
                    actual_format = AudioFormat.WAV
                    # Update content type after conversion
                    content_type = self._get_content_type_for_format(AudioFormat.WAV)
                    logger.info("Successfully converted to WAV")
                except RuntimeError as e:
                    logger.warning(f"Format conversion failed: {e}. Returning MP3 format.")
                except Exception as e:
                    logger.error(f"Unexpected error during format conversion: {e}")

        # Get voice value for logging
        voice_value = request.voice.value if hasattr(request.voice, "value") else str(request.voice)

        # Create response object
        metadata = {
            "response_headers": safe_response_headers_for_metadata(response.headers),
            "status_code": response.status_code,
            "url": str(response.url),
            "service": "openai.fm",
            "voice": voice_value,
            "original_text": (
                request.input[:100] + "..." if len(request.input) > 100 else request.input
            ),
            "requested_format": (
                requested_format.value
                if isinstance(requested_format, AudioFormat)
                else str(requested_format)
            ),
            "actual_format": (
                actual_format.value
                if isinstance(actual_format, AudioFormat)
                else str(actual_format)
            ),
        }

        # Add speed metadata if speed was requested
        if request.speed is not None:
            metadata["requested_speed"] = request.speed
            metadata["speed_applied"] = speed_applied

        tts_response = TTSResponse(
            audio_data=audio_data,
            content_type=content_type,
            format=actual_format,
            size=len(audio_data),
            duration=estimated_duration,
            metadata=metadata,
        )

        actual_format_str = (
            actual_format.value if isinstance(actual_format, AudioFormat) else str(actual_format)
        )
        logger.info(
            "Successfully generated %s of %s audio from openai.fm using voice %s",
            format_file_size(len(audio_data)),
            actual_format_str.upper(),
            voice_value,
        )

        return tts_response

    def close(self) -> None:
        """Close the HTTP session."""
        if hasattr(self, "session"):
            self.session.close()

    def __enter__(self):  # type: ignore[no-untyped-def]
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore[no-untyped-def]
        """Context manager exit."""
        self.close()
