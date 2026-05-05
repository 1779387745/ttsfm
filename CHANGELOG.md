# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [3.5.0] - 2026-05-05

### Breaking

- `TTSRequest` and `split_text_by_length` no longer accept `max_length` greater than 1000 (values above the upstream limit used to be clamped; they now raise `ValueError`).

### Fixed

- Web playground: wait for `/api/auth-status` before opening the streaming WebSocket so required API keys are not sent empty; reconnect after API key input when the server requires a key.
- `AsyncTTSClient`: API key from `TTSFM_API_KEY` / env is now applied to `self.api_key` (was only read into a local variable).
- WebSocket auth: `bearer` field in Socket.IO `auth` may be a full `Bearer …` string; the prefix is stripped correctly.
- Sync `generate_speech_batch`: reuse one `requests.Session` per worker thread instead of opening/closing a session per chunk.

### Changed

- GitHub Actions CI runs the test and lint suite on Python **3.9, 3.10, 3.11, and 3.12** (`fail-fast: false`).
- README (EN/zh): describe openai.fm as the live default upstream; disclaimer no longer implies the upstream or project is unusable.

## [3.4.2] - 2025-12-17

### Security
- **Fixed information exposure vulnerability** (CWE-209, CWE-497)
  - Sanitized error messages in FFmpeg-related exceptions
  - Replaced raw exception details with user-friendly messages
  - Detailed errors now only logged internally for debugging
  - Prevents exposure of internal file paths, stack traces, and system configuration

### Fixed
- **Complete Chinese translation coverage**
  - Added 30+ missing translation keys for web interface
  - Translated WebSocket streaming UI components
  - Translated playground controls and tooltips
  - Translated audio player metadata and statistics
  - All UI elements now properly display in Chinese mode

### Changed
- Removed redundant version badge from home page feature section
- Improved error message consistency across API endpoints

## [3.4.1] - 2025-11-08

### Fixed
- **WebSocket connection issues** ([#37](https://github.com/dbccccccc/ttsfm/issues/37))
  - Fixed Socket.IO server configuration with proper timeouts and CORS settings
  - Fixed client transport order (polling first, then upgrade to WebSocket)
  - Added explicit Socket.IO path configuration (`/socket.io/`)
  - Enhanced connection timeout and upgrade settings
  - Improved error logging and debugging information
- **WebSocket client improvements**:
  - Added ping/pong connection testing functionality
  - Better status messages and error handling in UI
  - Enhanced console logging for troubleshooting
  - Automatic connection testing on successful connect

### Added
- **WebSocket test script** (`scripts/test_websocket.py`)
  - Automated WebSocket connection testing
  - Ping/pong latency testing
  - TTS generation verification
  - Comprehensive test output with status indicators
- **WebSocket troubleshooting documentation** (`docs/websocket-troubleshooting.md`)
  - Common issues and solutions
  - Configuration reference
  - Debugging steps
  - Browser compatibility notes

### Changed
- Socket.IO server configuration now includes:
  - `ping_timeout: 60` seconds
  - `ping_interval: 25` seconds
  - `logger` and `engineio_logger` enabled in debug mode
  - `cors_credentials: True` for proper CORS handling
- Socket.IO client configuration now includes:
  - Transport order: `['polling', 'websocket']` for better reliability
  - `upgrade: true` and `rememberUpgrade: true` for transport optimization
  - `timeout: 20000` ms connection timeout
  - Explicit path configuration

### Technical
- WebSocket connections now successfully establish in both local and Docker environments
- Transport upgrade from polling to WebSocket working correctly
- All WebSocket tests passing (connection, ping/pong, TTS streaming)
- Docker image tested and verified (594MB full variant)

## [3.4.0] - 2025-10-28

### Added
- **Image variant detection system**: Automatic detection of full vs slim Docker images
  - New `ttsfm/capabilities.py` module with `SystemCapabilities` class
  - Runtime detection of ffmpeg availability
  - Global singleton instance for efficient capability checking
- **New API endpoints**:
  - `/api/capabilities` - Complete system capabilities report
  - Enhanced `/api/health` endpoint with image variant information
- **Comprehensive format support**: 6 audio formats with real ffmpeg-based conversion
  - Always available: MP3, WAV
  - Full image only: OPUS, AAC, FLAC, PCM
- **Speed adjustment**: 0.25x to 4.0x playback speed (requires ffmpeg)
- **Enhanced error handling**: Clear error messages with helpful hints
- **Improved web documentation**: Complete rewrite with v3.4.0 features
  - Docker image variants section
  - OpenAI-compatible API documentation
  - System capabilities documentation
  - Speed adjustment guide
  - Format conversion details
  - Long text handling
  - Python package examples
  - WebSocket streaming
  - Error handling reference

### Fixed
- Slim image error handling: Proper error reporting instead of silent failures
- RuntimeError exception handling in web API
- Footer removed from all web pages for cleaner interface

### Changed
- Improved error response format with structured messages
- Updated README.md with v3.4.0 features and examples
- Playground UI enhancements for feature detection
- Documentation reorganized for better clarity

### Technical
- Capabilities detection uses singleton pattern
- Early validation prevents expensive operations
- All tests passing (25 unit tests + integration tests)

## [3.4.0-beta1] - 2025-10-28

### Added
- **Image variant detection system**: Automatic detection of full vs slim Docker images
  - New `ttsfm/capabilities.py` module with `SystemCapabilities` class
  - Runtime detection of ffmpeg availability using `shutil.which("ffmpeg")`
  - Global singleton instance via `get_capabilities()` function
- **New API endpoints for feature discovery**:
  - `/api/capabilities` - Returns complete system capabilities report
    - `ffmpeg_available`: Boolean indicating ffmpeg availability
    - `image_variant`: "full" or "slim"
    - `features`: Dictionary of available features (speed_adjustment, format_conversion, mp3_auto_combine, basic_formats)
    - `supported_formats`: List of available audio formats
  - Enhanced `/api/health` endpoint with `image_variant` and `ffmpeg_available` fields
- **Early validation for ffmpeg-dependent features**:
  - Advanced formats (OPUS, AAC, FLAC, PCM) checked before processing
  - Speed adjustment (speed != 1.0) validated before processing
  - MP3 auto-combine for long text validated before processing
  - Returns 400 error with helpful hints when features unavailable
- **Playground UI enhancements for slim image**:
  - Automatic capabilities loading on page load
  - Image variant badge in navbar ("Full Image" green / "Slim Image" yellow)
  - Speed slider disabled with tooltip when ffmpeg unavailable
  - Advanced format options disabled and marked "(requires full image)"
  - Error messages include hints from API responses
- **Comprehensive test scripts**:
  - `scripts/test_slim_image.py` - Integration tests against running server
  - `scripts/test_slim_simulation.py` - Unit tests with mocked ffmpeg unavailability

### Fixed
- **Slim image error handling**: Slim image now properly reports errors instead of failing silently
  - Clear error messages for unavailable features
  - Helpful hints directing users to full Docker image
  - Proper HTTP 400 status codes with structured error responses
- **RuntimeError exception handling**: Web API now catches ffmpeg-related errors from audio_processing module

### Changed
- **Improved error response format**: All feature unavailability errors now include:
  - `message`: Clear description of the issue
  - `type`: "feature_unavailable_error"
  - `code`: "ffmpeg_required"
  - `hint`: Helpful suggestion to use full Docker image
  - `available_formats`: List of supported formats (when applicable)

### Technical
- Capabilities detection uses singleton pattern for efficiency
- Early validation prevents expensive operations when features unavailable
- Playground JavaScript loads capabilities asynchronously
- All 25 tests passing plus new integration and simulation tests

## [3.4.0-alpha4] - 2025-10-28

### Added
- **Format conversion with ffmpeg**: All 6 audio formats now properly converted using ffmpeg
  - MP3, WAV: Direct from openai.fm (no conversion needed)
  - OPUS, AAC, FLAC, PCM: Converted from WAV using ffmpeg
  - Proper MIME type headers for each format (audio/opus, audio/aac, audio/flac, audio/pcm)
  - Downloads now have correct file extensions (.opus, .aac, .flac, .pcm)
- **Format selector in playground**: Added dropdown to select audio format in web UI
  - Clean display showing only format names (mp3, wav, opus, aac, flac, pcm)
  - Integrated with existing playground functionality

### Fixed
- **Content-Type headers after format conversion**: Fixed issue where converted formats returned wrong content-type
  - Added `_get_content_type_for_format()` helper method to both sync and async clients
  - Content-type now properly updated after ffmpeg conversion
  - Downloads now use correct file extensions based on actual format
- **Speed display in playground**: Fixed bug where speed always showed "1.0x" regardless of actual speed
  - Updated `buildGenerationMeta()` to include speed and speedApplied fields
  - Speed now correctly displayed in audio stats (0.25x, 0.5x, 1.0x, 1.5x, 2.0x, 4.0x)

### Changed
- **Removed legacy format mapping**: Eliminated header-based format "faking" in favor of real conversion
  - Removed `get_supported_format()` and `maps_to_wav()` functions from `ttsfm/models.py`
  - Simplified client code by ~30 lines
  - All formats now return actual requested format, not approximations
- **Migrated playground to OpenAI API**: Removed old `/api/generate` endpoints
  - Playground now uses `/v1/audio/speech` endpoint exclusively
  - Consistent API format across all interfaces
  - Speed parameter now works correctly in playground

### Technical
- Format conversion uses `convert_audio_format()` from `audio_processing.py`
- Async client runs ffmpeg conversion in thread pool to avoid blocking
- Graceful fallback to original format if ffmpeg unavailable
- All 25 tests passing with new format conversion logic

## [3.4.0-alpha3] - 2025-10-26

### Fixed
- **Critical bug fix**: Speed parameter was not being extracted from API requests in web app
  - Web API endpoint `/v1/audio/speech` now correctly extracts and passes `speed` parameter to TTSFM client
  - Added proper validation for speed parameter (must be between 0.25 and 4.0)
  - Speed adjustment now works correctly for both single-chunk and long-text generation

### Changed
- **Separated Docker build workflows**: Split monolithic workflow into two independent files
  - `.github/workflows/docker-build-full.yml` - Builds full variant with ffmpeg
  - `.github/workflows/docker-build-slim.yml` - Builds slim variant without ffmpeg
  - Improved clarity, debugging, and parallel execution
  - Independent cache scopes for each variant

### Added
- Speed metadata headers in API responses:
  - `X-Requested-Speed`: The speed value requested by the client
  - `X-Speed-Applied`: Whether speed adjustment was actually applied (true/false)

## [3.4.0-alpha2] - 2025-10-25

### Changed
- Improved Docker workflow configuration for dual image variants
- Enhanced documentation for Docker image variants

## [3.4.0-alpha1] - 2025-10-23

### Added
- **Dual Docker image variants**: Full image with ffmpeg and slim image without ffmpeg
  - Full variant: `dbcccc/ttsfm:latest`, `dbcccc/ttsfm:v3.4.0-alpha1`
  - Slim variant: `dbcccc/ttsfm:v3.4.0-alpha1-slim`
- **Speed adjustment feature**: Adjust audio playback speed from 0.25x to 4.0x (requires ffmpeg)
  - Implemented using ffmpeg's `atempo` filter with automatic filter chaining for extreme speeds
  - Supported in both sync (`TTSClient`) and async (`AsyncTTSClient`) clients
  - Integrated into `/v1/audio/speech` API endpoint
  - Response metadata includes `speed_applied` and `requested_speed` fields
- **Runtime ffmpeg detection**: Graceful degradation with helpful error messages when ffmpeg is unavailable
- **New audio processing module**: `ttsfm/audio_processing.py` with `adjust_audio_speed()` and `convert_audio_format()` functions

### Changed
- Dockerfile now uses `VARIANT` build argument to conditionally install ffmpeg
- GitHub Actions workflow builds both full and slim variants with separate cache scopes
- Updated README (EN/ZH) with image variant comparison table and speed adjustment examples
- Enhanced error messages to guide users to full image when ffmpeg features are needed

### Documentation
- Added comprehensive `docs/v3.4-dual-image-implementation.md` with feature matrix and migration guide
- Updated README examples to demonstrate speed adjustment usage
- Added test suite for audio processing functionality

### Technical
- Speed adjustment runs in thread pool for async client to avoid blocking
- Duration estimation automatically adjusted based on speed multiplier
- Separate Docker cache scopes for efficient multi-variant builds

## [3.3.2-3.3.7] - 2025-10-21

fixes and improvements since 3.3.1

## [3.3.1] - 2025-10-18

### Changed
- Enforced a 1000-character ceiling across the core clients, CLI, and web API, with sentence-aware splitting that falls back to word chunks when required.
- Refreshed the README (EN/ZH), translations, and UI badges to document the new limit and updated release version.
- Bundled `ffmpeg` inside the runtime Docker image so MP3 auto-combine succeeds out of the box without manual package installs.

### Testing
- `pytest`
- Manual `/v1/audio/speech` request (≈1.6k chars) exercised Docker auto-combine; returned `X-Chunks-Combined: 2` and a playable MP3.

## [3.3.0-alpha5] - 2025-09-19

### Fixed
- Restored lint compliance across the repo (flake8, import hygiene, line wrapping) so the release pipeline can publish successfully.
- Hardened Docker smoke test to manage container lifecycle and surface logs when health checks fail.
- Ensured Eventlet monkey patching happens before Flask imports to stop recursion-depth crashes and restore HTTP endpoint health.
- Forced long-text auto-combine flows to request WAV when MP3 would require `ffmpeg`, avoiding runtime errors on stock deployments.

### Documentation
- Updated release notes to point to the `alpha5` build.

## [3.3.0-alpha4] - 2025-09-19

### Changed
- Enforced MP3 pass-through while mapping all other requested formats to WAV so the service returns predictable audio without failing compatibility checks.
- Python clients now normalise outbound `response_format` payloads to the supported set and surface fallback metadata when a WAV result is returned.
- Docker build workflow tags only `v*` image aliases to avoid duplicate semver tags without the `v` prefix.

### Removed
- Web playground and WebSocket demo no longer expose manual format selectors, reducing confusion around unavoidable WAV fallbacks.

### Documentation
- README (EN/ZH) clarifies the MP3-only guarantee and WAV fallback, and the UI copy was refreshed accordingly.

## [3.3.0-alpha3] - 2025-09-18

### Added
- Centralised audio chunk combining in `ttsfm/audio.py`, including the reusable `combine_responses` helper for both core and web flows.
- `auto_combine=True` support in the synchronous/asynchronous clients and CLI delivers a single audio file for long text (pydub still optional for non-WAV output).
- Regression tests (`tests/test_clients.py`) covering the new combination paths.

### Changed
- Long-text splitting now falls back to word-level chunks with a small tolerance so punctuation stays intact while respecting `max_length` limits.

### Documentation
- README (EN/ZH) highlights the Python auto-combine option and CLI flag; `AI_NOTES.md` captures the refreshed test instructions.

### Testing
- Added regression coverage for the audio helper refactor and client auto-combine behaviour; `pytest` commands documented for follow-up runs.

## [3.3.0-alpha2] - 2025-09-18

### Changed
- Non-WAV audio combining now passes explicit decoder hints so OPUS/AAC/FLAC/PCM chunks merge correctly in the web stack.
- WebSocket streaming tasks close their per-request `TTSClient` once finished, preventing open `requests.Session` handles from accumulating.
- Sentence splitting falls back to word-level chunks (with a small tolerance to keep punctuation) ensuring every generated request respects `max_length`.

### Documentation
- Clarified in README (EN/ZH) that automatic long-text combining is provided by the Docker/OpenAI-compatible API, not the core Python client.

### Testing
- Added regression tests for the enhanced text splitting and audio combiner behaviour and documented run commands in `AI_NOTES.md`.

## [3.3.0-alpha] - 2025-09-17

### Added
- Flask web app now spins up per-request TTS clients, streams responses, hashes API keys, and enforces simple rate limits.
- WebSocket handler tracks active tasks, supports cancellation, and streams base64 audio chunks for responsive UIs.
- Frontend metadata fetches use a cached API client, and CI now runs lint/test gates before packaging artifacts.

### Changed
- Deterministic HTTP header generation no longer depends on network user-agent lookups.
- Default narration prompts are opt-in for both sync and async clients, and retry logic preserves original exceptions.
- Audio combining requires "pydub" for non-WAV formats and fails fast when the dependency is missing.

### Fixed
- Async client retry payload handling copies request bodies per attempt to avoid mutation side effects.

## [3.2.9] - 2025-09-16

### Container build
- Replaced the Docker image with a multi-stage build that installs dependencies in a throwaway stage and keeps only the runtime layers.
- Taught the entrypoint build to accept a VERSION build argument so tagged releases surface the correct version without bundling .git metadata.
- Added a .dockerignore that drops virtualenvs, docs, tests, and lock artifacts from the build context for faster, smaller builds.

### Continuous integration
- Extended the Docker workflow to run on pushes and pull requests so image regressions surface before releases.
- Simplified release pushes by skipping image size enforcement while keeping multi-arch publishing for tagged releases.

### Web playground
- Rebuilt the playground controller so validation, random prompts, reset, and share/download buttons behave again.
- Restored audio metadata reporting (duration, size, format, voice, timestamps) and added richer streaming progress indicators.

## [3.2.8] - 2025-09-16

### 🐳 Docker Reliability Improvements

- Containers now bind to `0.0.0.0` by default when running under Docker, resolving WebSocket startup loops and HTTP 502 errors when exposing port 8000.
- Health endpoints and UI badges report the correct v3.2.8 identifier so deployments reflect the running build instantly.

### 📘 Documentation & Release Prep

- README (EN/ZH) updated with guidance for overriding the bind host via the `HOST` environment variable.
- Package metadata, translations, and distribution manifests bumped for the v3.2.8 Python and container releases.

## [3.2.3] - 2025-06-27

### 🔄 Enhanced OpenAI API Compatibility

This release consolidates the OpenAI-compatible API endpoints and introduces intelligent auto-combine functionality.

### ✨ Added

- **Auto-Combine Parameter**: New optional `auto_combine` parameter in `/v1/audio/speech` endpoint (default: `true`)
- **Intelligent Text Handling**: Automatically detects long text and combines audio chunks when `auto_combine=true`
- **Enhanced Error Messages**: Better error handling for long text when auto-combine is disabled
- **Response Headers**: Added `X-Auto-Combine` and `X-Chunks-Combined` headers for transparency

### 🔄 Changed

- **Unified Endpoint**: Combined `/v1/audio/speech` and `/v1/audio/speech-combined` into single endpoint
- **Backward Compatibility**: Maintains full OpenAI API compatibility while adding TTSFM-specific features
- **Default Behavior**: Long text is now automatically split and combined by default (can be disabled)

### 🗑️ Removed

- **Deprecated Endpoint**: Removed `/v1/audio/speech-combined` endpoint (functionality moved to main endpoint)
- **Legacy Web Options**: Removed confusing batch processing options from web interface for cleaner UX
- **Complex UI Elements**: Simplified playground interface to focus on auto-combine

### 🧹 Streamlined Web Experience

- **User-Focused Design**: Web interface now emphasizes auto-combine as the primary approach
- **Developer Features Preserved**: All advanced functionality remains in Python package
- **Clear Separation**: Web for users, Python package for developers

### 📋 Migration Guide

- **No Breaking Changes**: Existing API calls continue to work unchanged
- **Long Text**: Now automatically handled by default - no need to use separate endpoint
- **Disable Auto-Combine**: Add `"auto_combine": false` to request body to get original behavior

## [3.2.2] - 2025-06-26

### 🎵 Combined Audio Functionality

This release introduces the revolutionary combined audio feature that allows generating single, seamless audio files from long text content.

### ✨ Added

- **Combined Audio Endpoints**: New `/api/generate-combined` and `/v1/audio/speech-combined` endpoints
- **Intelligent Text Splitting**: Smart algorithm that splits text at sentence boundaries, then word boundaries, preserving natural speech flow
- **Seamless Audio Combination**: Professional audio processing to merge chunks into single continuous files
- **OpenAI Compatibility**: Full OpenAI TTS API compatibility for combined audio generation
- **Advanced Fallback System**: Multiple fallback mechanisms for audio combination (PyDub → WAV concatenation → raw concatenation)
- **Rich Metadata**: Response headers with chunk count, file size, and processing information
- **Comprehensive Testing**: Full test suite with unit tests, integration tests, and performance benchmarks

### 🔄 Changed

- **Extended Character Limits**: No longer limited to 4096 characters per request
- **Enhanced Web Interface**: Updated documentation with combined audio endpoint information
- **Improved Error Handling**: Better validation and error messages for long text processing

### 🛠️ Technical Features

- **Concurrent Processing**: Parallel chunk processing for faster generation
- **Memory Optimization**: Efficient memory usage for large text processing
- **Format Support**: Works with all supported audio formats (MP3, WAV, OPUS, AAC, FLAC, PCM)
- **Performance Monitoring**: Built-in performance tracking and optimization
- **Unicode Support**: Full Unicode text handling for international content

### 📋 Use Cases

- **Long Articles**: Convert blog posts and articles to single audio files
- **Audiobooks**: Generate chapters as continuous audio
- **Educational Content**: Transform learning materials to audio format
- **Accessibility**: Enhanced support for visually impaired users
- **Podcast Creation**: Convert scripts to professional audio content

## [3.1.0] - 2024-12-19

### 🔧 Format Support Improvements

This release focuses on fixing audio format handling and improving format delivery optimization.

### ✨ Added

- **Smart Header Selection**: Intelligent HTTP header selection to optimize format delivery from openai.fm service
- **Format Mapping Functions**: Helper functions for better format handling and optimization
- **Enhanced Web Interface**: Improved format selection with detailed descriptions for each format
- **Comprehensive Format Documentation**: Updated README and documentation with complete format information

### 🔄 Changed

- **File Naming Logic**: Files are now saved with extensions based on the actual returned format, not the requested format
- **Enhanced Logging**: Added format-specific log messages for better debugging
- **Web API Enhancement**: `/api/formats` endpoint now provides detailed information about all supported formats
- **Documentation Updates**: README and package documentation now include comprehensive format guides

### 🐛 Fixed

- **MAJOR FIX**: Resolved file naming issue where files were saved with incorrect double extensions (e.g., `test.wav.mp3`, `test.opus.wav`)
- **Correct File Extensions**: Files now save with proper single extensions based on actual audio format (e.g., `test.mp3`, `test.wav`)
- **Format Optimization**: Improved format delivery through smart request optimization
- **Format Handling**: Better handling of all supported audio formats

### 📝 Technical Details

- **Format Optimization**: Smart request optimization to deliver the best quality for each format
- **Backward Compatibility**: Existing code continues to work unchanged
- **Enhanced Format Support**: Improved support for all 6 audio formats (MP3, WAV, OPUS, AAC, FLAC, PCM)

## [3.0.0] - 2025-06-06

### 🎉 First Python Package Release

This is the first release of TTSFM as an installable Python package. Previous versions (v1.x and v2.x) were service-only releases that provided the API server but not a pip-installable package.

### ✨ Added

- **Complete Package Restructure**: Modern Python package structure with proper typing
- **Async Support**: Full asynchronous client implementation with `asyncio`
- **OpenAI API Compatibility**: Drop-in replacement for OpenAI TTS API
- **Type Hints**: Complete type annotation support throughout the codebase
- **CLI Interface**: Command-line tool for easy TTS generation
- **Web Application**: Optional Flask-based web interface
- **Docker Support**: Multi-architecture Docker images (linux/amd64, linux/arm64)
- **Comprehensive Error Handling**: Detailed exception hierarchy
- **Multiple Audio Formats**: Support for MP3, WAV, FLAC, and more
- **Voice Options**: Multiple voice models (alloy, ash, ballad, coral, echo, fable, nova, onyx, sage, shimmer)
- **Text Processing**: Automatic text length validation and splitting
- **Rate Limiting**: Built-in rate limiting and retry mechanisms
- **Configuration**: Environment variable and configuration file support

### 🔧 Technical Improvements

- **Modern Build System**: Using `pyproject.toml` with setuptools
- **GitHub Actions**: Automated Docker builds and PyPI publishing
- **Development Tools**: Pre-commit hooks, linting, testing setup
- **Documentation**: Comprehensive README and inline documentation
- **Package Management**: Proper dependency management with optional extras

### 🌐 API Changes

- **Breaking**: Complete API redesign for better usability
- **OpenAI Compatible**: `/v1/audio/speech` endpoint compatibility
- **RESTful Design**: Clean REST API design
- **Health Checks**: Built-in health check endpoints
- **CORS Support**: Cross-origin resource sharing enabled

### 📦 Installation Options

```bash
# Basic installation
pip install ttsfm

# With web application support
pip install ttsfm[web]

# With development tools
pip install ttsfm[dev]

# Docker
docker run -p 8000:8000 dbcccc/ttsfm:latest
```

### 🚀 Quick Start

```python
from ttsfm import TTSClient, Voice

client = TTSClient()
response = client.generate_speech(
    text="Hello! This is TTSFM v3.0.0",
    voice=Voice.CORAL
)

with open("speech.mp3", "wb") as f:
    f.write(response.audio_data)
```

### 📦 Package vs Service History

**Important Note**: This v3.0.0 is the first release of TTSFM as a Python package available on PyPI. Previous versions (v1.x and v2.x) were service/API server releases only and were not available as installable packages.

- **v1.x - v2.x**: Service releases (API server only, not pip-installable)
- **v3.0.0+**: Full Python package releases (pip-installable with service capabilities)

### 🐛 Bug Fixes

- Fixed Docker build issues with dependency resolution
- Improved error handling and user feedback
- Better handling of long text inputs
- Enhanced stability and performance

### 📚 Documentation

- Complete API documentation
- Usage examples and tutorials
- Docker deployment guide
- Development setup instructions

---

## Previous Service Releases (Not Available as Python Packages)

The following versions were service/API server releases only and were not available as pip-installable packages:

### [2.0.0-alpha9] - 2025-04-09
- Service improvements (alpha release)

### [2.0.0-alpha8] - 2025-04-09
- Service improvements (alpha release)

### [2.0.0-alpha7] - 2025-04-07
- Service improvements (alpha release)

### [2.0.0-alpha6] - 2025-04-07
- Service improvements (alpha release)

### [2.0.0-alpha5] - 2025-04-07
- Service improvements (alpha release)

### [2.0.0-alpha4] - 2025-04-07
- Service improvements (alpha release)

### [2.0.0-alpha3] - 2025-04-07
- Service improvements (alpha release)

### [2.0.0-alpha2] - 2025-04-07
- Service improvements (alpha release)

### [2.0.0-alpha1] - 2025-04-07
- Alpha release (DO NOT USE)

### [1.3.0] - 2025-03-28
- Support for additional audio file formats in the API
- Alignment with formats supported by the official API

### [1.2.2] - 2025-03-28
- Fixed Docker support

### [1.2.1] - 2025-03-28
- Color change for indicator for status
- Voice preview on webpage for each voice

### [1.2.0] - 2025-03-26
- Enhanced stability and availability by implementing advanced request handling mechanisms
- Removed the proxy pool

### [1.1.2] - 2025-03-26
- Version display on webpage
- Last version of 1.1.x

### [1.1.1] - 2025-03-26
- Build fixes

### [1.1.0] - 2025-03-26
- Project restructuring for better future development experiences
- Added .env settings

### [1.0.0] - 2025-03-26
- First service release
