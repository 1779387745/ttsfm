"""
Asynchronous TTS client implementation.

This module provides the AsyncTTSClient class for asynchronous
text-to-speech generation with OpenAI-compatible API.
"""

import asyncio
import json
import logging
import uuid
from typing import Dict, List, Optional, Union

import aiohttp
from aiohttp import ClientSession, ClientTimeout

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


class AsyncTTSClient:
    """
    Asynchronous TTS client for text-to-speech generation.

    This client provides an async interface for generating speech from text
    using OpenAI-compatible TTS services with support for concurrent requests.

    Attributes:
        base_url: Base URL for the TTS service
        api_key: API key for authentication (if required)
        timeout: Request timeout in seconds
        max_retries: Maximum number of retry attempts
        verify_ssl: Whether to verify SSL certificates
        max_concurrent: Maximum concurrent requests
    """

    def __init__(  # type: ignore[no-untyped-def]
        self,
        base_url: str = "https://www.openai.fm",
        api_key: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        verify_ssl: bool = True,
        max_concurrent: int = 10,
        default_headers: Optional[Dict[str, str]] = None,
        use_default_prompt: bool = False,
        **kwargs,
    ):
        """
        Initialize the async TTS client.

        Args:
            base_url: Base URL for the TTS service
            api_key: API key for authentication
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts
            verify_ssl: Whether to verify SSL certificates
            max_concurrent: Maximum concurrent requests
            **kwargs: Additional configuration options
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = resolve_api_key(api_key)
        self.timeout = timeout
        self.max_retries = max_retries
        self.verify_ssl = verify_ssl
        self.max_concurrent = max_concurrent
        self.use_default_prompt = use_default_prompt
        self.default_headers = default_headers or {}

        # Validate base URL
        if not validate_url(self.base_url):
            raise ValidationException(f"Invalid base URL: {self.base_url}")

        # Session will be created when needed
        self._session: Optional[ClientSession] = None
        self._semaphore = asyncio.Semaphore(max_concurrent)

        logger.info(f"Initialized async TTS client with base URL: {self.base_url}")

    async def __aenter__(self):  # type: ignore[no-untyped-def]
        """Async context manager entry."""
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore[no-untyped-def]
        """Async context manager exit."""
        await self.close()

    async def _ensure_session(self) -> None:
        """Ensure HTTP session is created."""
        if self._session is None or self._session.closed:
            # Setup headers
            headers = get_realistic_headers(self.default_headers)
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            # Create timeout configuration
            timeout = ClientTimeout(total=self.timeout)

            # Create session
            connector = aiohttp.TCPConnector(
                verify_ssl=self.verify_ssl, limit=self.max_concurrent * 2
            )

            self._session = ClientSession(headers=headers, timeout=timeout, connector=connector)

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

    async def generate_speech(  # type: ignore[no-untyped-def]
        self,
        text: str,
        voice: Union[Voice, str] = Voice.ALLOY,
        response_format: Union[AudioFormat, str] = AudioFormat.MP3,
        instructions: Optional[str] = None,
        max_length: int = 1000,
        validate_length: bool = True,
        **kwargs,
    ) -> TTSResponse:
        """
        Generate speech from text asynchronously.

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

        return await self._make_request(request)

    async def generate_speech_long_text(  # type: ignore[no-untyped-def]
        self,
        text: str,
        voice: Union[Voice, str] = Voice.ALLOY,
        response_format: Union[AudioFormat, str] = AudioFormat.MP3,
        instructions: Optional[str] = None,
        max_length: int = 1000,
        preserve_words: bool = True,
        auto_combine: bool = False,
        **kwargs,
    ) -> Union[TTSResponse, List[TTSResponse]]:
        """
        Generate speech from long text by splitting it into chunks asynchronously.

        This method automatically splits text that exceeds max_length into
        smaller chunks and generates speech for each chunk concurrently.

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
        # Sanitize text first
        clean_text = sanitize_text(text)

        # Split text into chunks
        chunks = split_text_by_length(clean_text, max_length, preserve_words)

        if not chunks:
            raise ValueError("No valid text chunks found after processing")

        send_format = self._resolve_long_text_format(response_format, auto_combine)

        # Create requests for all chunks
        requests = []
        for chunk in chunks:
            request = TTSRequest(
                input=chunk,
                voice=voice,
                response_format=send_format,
                instructions=instructions,
                max_length=max_length,
                validate_length=False,  # We already split the text
                **kwargs,
            )
            requests.append(request)

        # Process all chunks concurrently
        responses = await self.generate_speech_batch(requests=requests)

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

    async def generate_speech_from_long_text(  # type: ignore[no-untyped-def]
        self,
        text: str,
        voice: Union[Voice, str] = Voice.ALLOY,
        response_format: Union[AudioFormat, str] = AudioFormat.MP3,
        instructions: Optional[str] = None,
        max_length: int = 1000,
        preserve_words: bool = True,
        auto_combine: bool = False,
        **kwargs,
    ) -> Union[TTSResponse, List[TTSResponse]]:
        """
        Generate speech from long text by splitting it into chunks asynchronously.

        This is an alias for generate_speech_long_text for consistency.

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
        return await self.generate_speech_long_text(
            text=text,
            voice=voice,
            response_format=response_format,
            instructions=instructions,
            max_length=max_length,
            preserve_words=preserve_words,
            auto_combine=auto_combine,
            **kwargs,
        )

    async def generate_speech_batch(self, requests: List[TTSRequest]) -> List[TTSResponse]:
        """
        Generate speech for multiple requests concurrently.

        Args:
            requests: List of TTS requests

        Returns:
            List[TTSResponse]: List of generated audio responses

        Raises:
            TTSException: If any generation fails
        """
        if not requests:
            return []

        # Process requests concurrently with semaphore limiting
        tasks = [self._make_request(request) for request in requests]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        # Check for exceptions and convert them
        results: List[TTSResponse] = []
        for i, response in enumerate(responses):
            if isinstance(response, Exception):
                if isinstance(response, TTSException):
                    raise response
                raise TTSException(f"Request {i} failed") from response
            # At this point, response is guaranteed to be TTSResponse
            assert isinstance(response, TTSResponse)
            results.append(response)

        return results

    async def generate_speech_from_request(self, request: TTSRequest) -> TTSResponse:
        """
        Generate speech from a TTSRequest object asynchronously.

        Args:
            request: TTS request object

        Returns:
            TTSResponse: Generated audio response
        """
        return await self._make_request(request)

    async def _make_request(self, request: TTSRequest) -> TTSResponse:
        """
        Make the actual HTTP request to the TTS service.

        Args:
            request: TTS request object

        Returns:
            TTSResponse: Generated audio response

        Raises:
            TTSException: If request fails
        """
        await self._ensure_session()

        async with self._semaphore:  # Limit concurrent requests
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

            logger.info(
                "Generating speech for text: '%s...' with voice: %s",
                request.input[:50],
                request.voice,
            )

            # Make request with retries
            for attempt in range(self.max_retries + 1):
                try:
                    # Add random delay for rate limiting (except first attempt)
                    if attempt > 0:
                        delay = exponential_backoff(attempt - 1)
                        logger.info(f"Retrying request after {delay:.2f}s (attempt {attempt + 1})")
                        await asyncio.sleep(delay)

                    # Use form data as required by openai.fm
                    payload = dict(form_data)
                    # Normalize requested format
                    requested_format = request.response_format
                    if isinstance(requested_format, str):
                        try:
                            requested_format = AudioFormat(requested_format.lower())
                        except ValueError:
                            requested_format = AudioFormat.MP3

                    # Determine base format to request from openai.fm
                    # We request MP3 or WAV, then convert to other formats using ffmpeg
                    if requested_format == AudioFormat.MP3:
                        base_format = AudioFormat.MP3
                    else:
                        # For all other formats (WAV, OPUS, AAC, FLAC, PCM), request WAV
                        base_format = AudioFormat.WAV

                    payload["response_format"] = base_format.value
                    logger.debug(
                        f"Requesting {base_format.value} from openai.fm (target format: {requested_format.value})"
                    )
                    await self._ensure_session()
                    session = self._session
                    if session is None:
                        raise TTSException("HTTP session is not available")

                    async with session.post(url, data=payload) as response:
                        if response.status == 200:
                            return await self._process_openai_fm_response(response, request)
                        try:
                            error_data = await response.json()
                        except (json.JSONDecodeError, ValueError):
                            text = await response.text()
                            error_data = {"error": {"message": text or "Unknown error"}}

                        exception = create_exception_from_response(
                            response.status,
                            error_data,
                            f"TTS request failed with status {response.status}",
                        )

                        if response.status in (400, 401, 403, 404):
                            raise exception

                        if attempt == self.max_retries:
                            raise exception

                        logger.warning(f"Request failed with status {response.status}, retrying...")
                        continue

                except asyncio.TimeoutError:
                    if attempt == self.max_retries:
                        raise NetworkException(
                            f"Request timed out after {self.timeout}s",
                            timeout=self.timeout,
                            retry_count=attempt,
                        )
                    logger.warning("Request timed out, retrying...")
                    continue

                except aiohttp.ClientError as e:
                    if attempt == self.max_retries:
                        raise NetworkException(f"Client error: {str(e)}", retry_count=attempt)
                    logger.warning("Client error, retrying...")
                    continue

            # This should never be reached, but just in case
            raise TTSException("Maximum retries exceeded")

    async def _process_openai_fm_response(
        self, response: aiohttp.ClientResponse, request: TTSRequest
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
        audio_data = await response.read()

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

        # Estimate duration based on text length
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
                # Run CPU-intensive ffmpeg processing in thread pool
                loop = asyncio.get_event_loop()
                audio_data = await loop.run_in_executor(
                    None,
                    adjust_audio_speed,
                    audio_data,
                    request.speed,
                    actual_format.value,
                    actual_format.value,
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
                    # Run CPU-intensive ffmpeg processing in thread pool
                    loop = asyncio.get_event_loop()
                    audio_data = await loop.run_in_executor(
                        None,
                        convert_audio_format,
                        audio_data,
                        actual_format.value,
                        requested_format.value,
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
                    # Run CPU-intensive ffmpeg processing in thread pool
                    loop = asyncio.get_event_loop()
                    audio_data = await loop.run_in_executor(
                        None,
                        convert_audio_format,
                        audio_data,
                        "mp3",
                        "wav",
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
            "status_code": response.status,
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

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
