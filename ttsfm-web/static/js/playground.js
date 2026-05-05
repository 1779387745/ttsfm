import { fetchVoices, fetchFormats } from './api-client.js';

// TTSFM Playground with HTTP and WebSocket streaming support.
// Reworked to restore utility actions and populate generation metadata.

const PlaygroundApp = (() => {
    const SAMPLE_TEXTS = [
        'Hello! This is a quick demo of the TTSFM text-to-speech playground. It supports multiple voices and formats.',
        'Artificial intelligence is transforming the way we interact with technology, making speech interfaces natural and accessible.',
        'Need a sample script? Paste your marketing blurb, product description, or customer welcome message here and generate audio instantly.',
        'The quick brown fox jumps over the lazy dog. Pack my box with five dozen liquor jugs. These pangrams show every letter.'
    ];

    const state = {
        audioBlob: null,
        audioUrl: null,
        format: 'mp3',
        meta: null,
        wsClient: null,
        streamingMode: false,
        activeStreamId: null,
        defaultText: '',
        capabilities: null,  // System capabilities
        apiKeyRequired: false
    };

    const els = {};

    /** Per-chunk limit for this service (must not exceed upstream 1000). */
    const UPSTREAM_MAX_CHUNK = 1000;

    function getChunkMaxLength() {
        if (!els.maxLengthInput) {
            return UPSTREAM_MAX_CHUNK;
        }
        const n = parseInt(els.maxLengthInput.value, 10);
        if (Number.isNaN(n) || n < 1) {
            return 1;
        }
        return Math.min(UPSTREAM_MAX_CHUNK, n);
    }

    function init() {
        cacheDom();
        if (els.textInput) {
            state.defaultText = els.textInput.value;
        }

        attachCoreEvents();
        attachUtilityEvents();
        attachHotkeys();
        initializeTooltips();
        setupStreamingUi();

        if (els.apiKeyInput) {
            ['blur', 'change', 'paste'].forEach((evt) => {
                els.apiKeyInput.addEventListener(evt, () => {
                    if (state.apiKeyRequired) {
                        initWebSocket();
                    }
                });
            });
        }

        void (async () => {
            await checkAuthStatus();
            initWebSocket();
        })();

        loadCapabilities();  // Load system capabilities first
        loadVoices();

        if (document.getElementById('format-select')) {
            loadFormats();
        } else {
            state.format = 'mp3';
        }
        updateCharCount();
        updateAudioSummary();
        updateActionButtons(false);
    }

    function cacheDom() {
        els.form = document.getElementById('tts-form');
        els.textInput = document.getElementById('text-input');
        els.voiceSelect = document.getElementById('voice-select');
        els.formatSelect = document.getElementById('format-select');
        if (!els.formatSelect) {
            els.formatSelect = document.createElement('select');
            els.formatSelect.value = state.format;
        }
        els.instructionsInput = document.getElementById('instructions-input');
        els.apiKeyInput = document.getElementById('api-key-input');
        els.maxLengthInput = document.getElementById('max-length-input');
        els.validateLengthCheck = document.getElementById('validate-length-check');
        els.autoCombineCheck = document.getElementById('auto-combine-check');
        els.autoCombineStatus = document.getElementById('auto-combine-status');
        els.speedInput = document.getElementById('speed-input');
        els.speedValueDisplay = document.getElementById('speed-value-display');
        els.charCount = document.getElementById('char-count');
        els.lengthStatus = document.getElementById('length-status');
        els.generateBtn = document.getElementById('generate-btn');
        els.clearBtn = document.getElementById('clear-text-btn');
        els.validateBtn = document.getElementById('validate-text-btn');
        els.randomBtn = document.getElementById('random-text-btn');
        els.resetBtn = document.getElementById('reset-form-btn');
        els.downloadBtn = document.getElementById('download-btn');
        els.shareBtn = document.getElementById('share-btn');
        els.replayBtn = document.getElementById('replay-btn');
        els.audioResult = document.getElementById('audio-result');
        els.audioPlayer = document.getElementById('audio-player');
        els.audioInfo = document.getElementById('audio-info');
        els.audioDuration = document.getElementById('audio-duration');
        els.audioSize = document.getElementById('audio-size');
        els.audioVoice = document.getElementById('audio-voice');
        els.audioFormat = document.getElementById('audio-format');
        els.audioSpeed = document.getElementById('audio-speed');
        els.audioChunks = document.getElementById('audio-chunks');
        els.apiKeyToggle = document.getElementById('toggle-api-key-visibility');
    }

    function attachCoreEvents() {
        if (els.form) {
            els.form.addEventListener('submit', handleSubmit);
        }
        if (els.textInput) {
            els.textInput.addEventListener('input', updateCharCount);
        }
        if (els.maxLengthInput) {
            els.maxLengthInput.addEventListener('input', updateCharCount);
        }
        if (els.autoCombineCheck) {
            els.autoCombineCheck.addEventListener('change', updateCharCount);
        }
        if (els.validateLengthCheck) {
            els.validateLengthCheck.addEventListener('change', updateCharCount);
        }
        if (els.voiceSelect) {
            els.voiceSelect.addEventListener('change', () => updateAudioSummary());
        }
        if (els.formatSelect) {
            els.formatSelect.addEventListener('change', () => updateAudioSummary());
        }
        if (els.speedInput) {
            els.speedInput.addEventListener('input', updateSpeedDisplay);
        }
    }
    function attachUtilityEvents() {
        if (els.clearBtn) {
            els.clearBtn.addEventListener('click', clearText);
        }
        if (els.validateBtn) {
            els.validateBtn.addEventListener('click', validateText);
        }
        if (els.randomBtn) {
            els.randomBtn.addEventListener('click', loadRandomText);
        }
        if (els.resetBtn) {
            els.resetBtn.addEventListener('click', resetForm);
        }
        if (els.downloadBtn) {
            els.downloadBtn.addEventListener('click', downloadAudio);
        }
        if (els.shareBtn) {
            els.shareBtn.addEventListener('click', shareAudio);
        }
        if (els.replayBtn) {
            els.replayBtn.addEventListener('click', replayAudio);
        }
        if (els.apiKeyToggle) {
            els.apiKeyToggle.addEventListener('click', toggleApiKeyVisibility);
        }
    }

    function attachHotkeys() {
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
                event.preventDefault();
                if (els.generateBtn) {
                    els.generateBtn.click();
                }
            }
        });
    }

    function initializeTooltips() {
        if (typeof bootstrap === 'undefined') {
            return;
        }
        const triggers = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        triggers.forEach((el) => new bootstrap.Tooltip(el));
    }

    function setupStreamingUi() {
        if (!els.generateBtn) {
            return;
        }

        const controls = document.createElement('div');
        controls.className = 'streaming-controls mt-3';
        controls.innerHTML = `
            <div class="form-check form-switch">
                <input class="form-check-input" type="checkbox" id="stream-mode-toggle" disabled>
                <label class="form-check-label" for="stream-mode-toggle">
                    <i class="fas fa-bolt me-1"></i>${_('playground.enable_websocket_streaming')}
                    <small class="text-muted">${_('playground.realtime_audio_chunks')}</small>
                </label>
            </div>
            <div id="streaming-indicator" class="streaming-status mt-2"></div>
        `;
        els.generateBtn.parentElement.appendChild(controls);

        els.streamToggle = controls.querySelector('#stream-mode-toggle');
        els.streamingIndicator = controls.querySelector('#streaming-indicator');
        if (els.streamToggle) {
            els.streamToggle.addEventListener('change', (event) => {
                state.streamingMode = event.target.checked;
                updateGenerateButtonLabel();
            });
        }
        updateGenerateButtonLabel();
        updateStreamingStatus('disconnected');

        if (!els.audioResult || !els.audioResult.parentElement) {
            return;
        }

        const parent = els.audioResult.parentElement;

        const errorDiv = document.createElement('div');
        errorDiv.id = 'error-message';
        errorDiv.className = 'alert alert-danger';
        errorDiv.style.display = 'none';
        parent.insertBefore(errorDiv, els.audioResult);
        els.errorBox = errorDiv;

        const loadingDiv = document.createElement('div');
        loadingDiv.id = 'loading-section';
        loadingDiv.className = 'text-center';
        loadingDiv.style.display = 'none';
        loadingDiv.innerHTML = `
            <div class="spinner-border text-primary" role="status">
                <span class="visually-hidden">${_('common.loading')}</span>
            </div>
            <p class="mt-2">${_('common.generating_speech')}</p>
        `;
        parent.insertBefore(loadingDiv, els.audioResult);
        els.loadingBox = loadingDiv;

        const progressSection = document.createElement('div');
        progressSection.id = 'streaming-progress';
        progressSection.className = 'streaming-progress-section';
        progressSection.style.display = 'none';
        progressSection.innerHTML = `
            <div class="card border-primary">
                <div class="card-body">
                    <h5 class="card-title">
                        <i class="fas fa-stream me-2"></i>${_('playground.streaming_progress')}
                    </h5>
                    <div class="progress mb-3" style="height: 25px;">
                        <div class="progress-bar progress-bar-striped progress-bar-animated" id="stream-progress-bar" role="progressbar" style="width: 0%">
                            <span id="stream-progress-text">0%</span>
                        </div>
                    </div>
                    <div class="row text-center">
                        <div class="col-md-4">
                            <h6>${_('playground.chunks_heading')}</h6>
                            <p class="h5"><span id="chunks-count">0</span> / <span id="total-chunks">0</span></p>
                        </div>
                        <div class="col-md-4">
                            <h6>${_('playground.data_heading')}</h6>
                            <p class="h5" id="data-transferred">0 KB</p>
                        </div>
                        <div class="col-md-4">
                            <h6>${_('playground.time_heading')}</h6>
                            <p class="h5" id="stream-time">0.0s</p>
                        </div>
                    </div>
                    <div id="chunks-visualization" class="chunks-visual mt-3"></div>
                </div>
            </div>
        `;
        parent.insertBefore(progressSection, els.audioResult);
        els.streamingProgress = progressSection;
        els.streamProgressBar = progressSection.querySelector('#stream-progress-bar');
        els.streamProgressText = progressSection.querySelector('#stream-progress-text');
        els.streamChunks = progressSection.querySelector('#chunks-count');
        els.streamTotalChunks = progressSection.querySelector('#total-chunks');
        els.streamData = progressSection.querySelector('#data-transferred');
        els.streamTime = progressSection.querySelector('#stream-time');
        els.streamVisual = progressSection.querySelector('#chunks-visualization');
    }
    function initWebSocket() {
        if (typeof io === 'undefined' || typeof WebSocketTTSClient === 'undefined') {
            console.warn('Socket.IO client not available; streaming disabled.');
            return;
        }

        if (state.apiKeyRequired) {
            const key = (els.apiKeyInput?.value || '').trim();
            if (!key) {
                if (state.wsClient) {
                    state.wsClient.disconnect();
                    state.wsClient = null;
                }
                updateStreamingStatus('disconnected');
                return;
            }
        }

        if (state.wsClient) {
            state.wsClient.disconnect();
            state.wsClient = null;
        }

        const apiKey = (els.apiKeyInput?.value || '').trim();
        state.wsClient = new WebSocketTTSClient({
            socketUrl: window.location.origin,
            debug: false,
            apiKey,
            onConnect: () => {
                updateStreamingStatus('connected');
            },
            onDisconnect: () => {
                updateStreamingStatus('disconnected');
            },
            onError: (error) => {
                console.error('WebSocket error', error);
                updateStreamingStatus('error');
            }
        });
    }

    function updateGenerateButtonLabel() {
        if (!els.generateBtn) {
            return;
        }
        const label = els.generateBtn.querySelector('.btn-text');
        if (!label) {
            return;
        }
        if (state.streamingMode) {
            label.innerHTML = `<i class="fas fa-bolt me-2"></i>${_('playground.stream_speech')}`;
        } else {
            label.innerHTML = `<i class="fas fa-magic me-2"></i>${_('playground.generate_speech')}`;
        }
    }

    function handleSubmit(event) {
        event.preventDefault();
        event.stopPropagation();
        if (state.streamingMode && state.wsClient && state.wsClient.isConnected()) {
            generateStreaming();
        } else {
            generateHttp();
        }
        return false;
    }

    async function generateHttp() {
        const text = (els.textInput?.value || '').trim();
        const voice = els.voiceSelect?.value || 'alloy';
        const format = els.formatSelect?.value || state.format;
        const instructions = (els.instructionsInput?.value || '').trim();
        const apiKey = (els.apiKeyInput?.value || '').trim();
        const speed = els.speedInput?.value ? parseFloat(els.speedInput.value) : 1.0;

        if (!text) {
            showError('Please enter some text to convert.');
            return;
        }

        hideError();
        hideResults();
        showLoading();
        setFormDisabled(true);

        try {
            const headers = { 'Content-Type': 'application/json' };
            if (apiKey) {
                headers['Authorization'] = `Bearer ${apiKey}`;
            }
            const body = {
                model: 'gpt-4o-mini-tts',
                input: text,
                voice: voice,
                response_format: format
            };
            if (instructions) {
                body.instructions = instructions;
            }
            if (speed !== 1.0) {
                body.speed = speed;
            }
            body.max_length = getChunkMaxLength();
            if (els.autoCombineCheck) {
                body.auto_combine = els.autoCombineCheck.checked;
            }

            const response = await fetch('/v1/audio/speech', {
                method: 'POST',
                headers,
                body: JSON.stringify(body)
            });

            if (!response.ok) {
                let message = `Error: ${response.status} ${response.statusText}`;
                let hint = null;
                try {
                    const errorData = await response.json();
                    if (errorData.error?.message) {
                        message = errorData.error.message;
                    }
                    if (errorData.error?.hint) {
                        hint = errorData.error.hint;
                    }
                    // Add hint to message if available
                    if (hint) {
                        message += `\n\n💡 ${hint}`;
                    }
                } catch (error) {
                    // ignore parse errors
                }
                throw new Error(message);
            }

            const blob = await response.blob();
            state.audioBlob = blob;
            state.format = format;

            // Extract speed from response headers (what was actually applied)
            const requestedSpeed = response.headers.get('X-Requested-Speed');
            const speedApplied = response.headers.get('X-Speed-Applied');
            const actualSpeed = requestedSpeed ? parseFloat(requestedSpeed) : speed;

            const meta = buildGenerationMeta({
                voice,
                voiceLabel: getSelectedText(els.voiceSelect) || voice,
                format,
                formatLabel: (getSelectedText(els.formatSelect) || format).toUpperCase(),
                textLength: text.length,
                instructions,
                streaming: false,
                sizeBytes: blob.size,
                speed: actualSpeed,
                speedApplied: speedApplied === 'true',
                chunks: response.headers.get('X-Chunks-Combined') || null
            });

            showResults(blob, meta);
        } catch (error) {
            showError(error.message);
        } finally {
            hideLoading();
            setFormDisabled(false);
        }
    }

    function resetStreamingUi() {
        if (els.streamingProgress) {
            els.streamingProgress.style.display = 'block';
        }
        if (els.streamProgressBar) {
            els.streamProgressBar.style.width = '0%';
        }
        if (els.streamProgressText) {
            els.streamProgressText.textContent = '0%';
        }
        if (els.streamChunks) {
            els.streamChunks.textContent = '0';
        }
        if (els.streamTotalChunks) {
            els.streamTotalChunks.textContent = '0';
        }
        if (els.streamData) {
            els.streamData.textContent = '0 KB';
        }
        if (els.streamTime) {
            els.streamTime.textContent = '0.0s';
        }
        if (els.streamVisual) {
            els.streamVisual.innerHTML = '';
        }
    }
    async function generateStreaming() {
        const text = (els.textInput?.value || '').trim();
        const voice = els.voiceSelect?.value || 'alloy';
        const format = els.formatSelect?.value || state.format;
        const instructions = (els.instructionsInput?.value || '').trim();
        const speed = els.speedInput?.value ? parseFloat(els.speedInput.value) : 1.0;

        if (!text) {
            showError('Please enter some text to convert.');
            return;
        }

        if (!state.wsClient || !state.wsClient.isConnected()) {
            showError('WebSocket connection is not ready yet.');
            return;
        }

        hideError();
        hideResults();
        setFormDisabled(true);
        resetStreamingUi();
        updateStreamingStatus('streaming');

        const startTime = performance.now();
        try {
            const options = {
                voice,
                format,
                chunkSize: Math.min(512, getChunkMaxLength()),
                instructions: instructions || undefined,
                speed
            };
            await state.wsClient.generateSpeech(text, {
                ...options,
                onStart: (data) => {
                    state.activeStreamId = data.request_id;
                },
                onProgress: (progress) => {
                    updateStreamingProgress(progress.progress, progress.chunksCompleted, progress.totalChunks);
                    if (els.streamTime) {
                        const elapsed = (performance.now() - startTime) / 1000;
                        els.streamTime.textContent = `${elapsed.toFixed(1)}s`;
                    }
                },
                onChunk: (chunk) => {
                    if (els.streamVisual) {
                        const element = document.createElement('div');
                        element.className = 'chunk-indicator';
                        element.title = `${_('playground.chunk_title')} ${chunk.chunkIndex + 1} - ${(chunk.audioData.byteLength / 1024).toFixed(1)} KB`;
                        element.innerHTML = '<i class="fas fa-music"></i>';
                        els.streamVisual.appendChild(element);
                    }
                    if (els.streamData) {
                        const current = parseFloat(els.streamData.textContent) || 0;
                        const next = current + (chunk.audioData.byteLength / 1024);
                        els.streamData.textContent = `${next.toFixed(1)} KB`;
                    }
                },
                onComplete: (result) => {
                    const blob = new Blob([result.audioData], { type: `audio/${result.format}` });
                    state.audioBlob = blob;
                    state.format = result.format;

                    const meta = buildGenerationMeta({
                        voice,
                        voiceLabel: getSelectedText(els.voiceSelect) || voice,
                        format: result.format,
                        formatLabel: result.format.toUpperCase(),
                        textLength: text.length,
                        instructions,
                        streaming: true,
                        sizeBytes: result.audioData.byteLength,
                        chunks: result.chunks.length,
                        elapsedMs: performance.now() - startTime,
                        speed: speed
                    });

                    showResults(blob, meta);
                    showStreamingStats(meta);
                    updateStreamingStatus('connected');
                    setFormDisabled(false);
                },
                onError: (error) => {
                    showError(`Streaming error: ${error.message}`);
                    updateStreamingStatus('error');
                    setFormDisabled(false);
                }
            });
        } catch (error) {
            showError(`Failed to stream speech: ${error.message}`);
            updateStreamingStatus('error');
        } finally {
            state.activeStreamId = null;
        }
    }

    function updateStreamingProgress(progress, chunks, totalChunks) {
        if (els.streamProgressBar) {
            els.streamProgressBar.style.width = `${progress}%`;
        }
        if (els.streamProgressText) {
            els.streamProgressText.textContent = `${progress}%`;
        }
        if (els.streamChunks) {
            els.streamChunks.textContent = chunks;
        }
        if (els.streamTotalChunks) {
            els.streamTotalChunks.textContent = totalChunks;
        }
    }

    function showStreamingStats(meta) {
        if (!els.streamingProgress) {
            return;
        }
        const summary = document.createElement('div');
        summary.className = 'alert alert-success mt-3';

        const heading = document.createElement('h6');
        heading.innerHTML = `<i class="fas fa-check-circle me-2"></i>${_('playground.streaming_complete')}`;
        summary.appendChild(heading);

        const row = document.createElement('div');
        row.className = 'row mt-2';

        [
            { label: _('playground.chunks_label'), value: meta.chunks || 0 },
            { label: _('playground.total_size_label'), value: formatBytes(meta.sizeBytes || 0) },
            { label: _('playground.time_label'), value: meta.elapsedMs ? (meta.elapsedMs / 1000).toFixed(2) + 's' : '--' },
            { label: _('playground.format_label_colon'), value: (meta.format || state.format).toUpperCase() },
        ].forEach((stat) => {
            const col = document.createElement('div');
            col.className = 'col-md-3';

            const strong = document.createElement('strong');
            strong.textContent = stat.label;
            col.appendChild(strong);

            col.appendChild(document.createTextNode(` ${String(stat.value)}`));
            row.appendChild(col);
        });

        summary.appendChild(row);
        els.streamingProgress.appendChild(summary);
    }

    function updateStreamingStatus(status) {
        if (!els.streamingIndicator) {
            return;
        }
        els.streamingIndicator.className = 'streaming-status';
        switch (status) {
            case 'connected':
                els.streamingIndicator.classList.add('connected');
                els.streamingIndicator.innerHTML = `<i class="fas fa-bolt"></i> ${_('playground.streaming_ready')}`;
                if (els.streamToggle) {
                    els.streamToggle.disabled = false;
                }
                break;
            case 'streaming':
                els.streamingIndicator.classList.add('streaming');
                els.streamingIndicator.innerHTML = `<i class="fas fa-stream"></i> ${_('playground.streaming_active')}`;
                break;
            case 'error':
                els.streamingIndicator.classList.add('error');
                els.streamingIndicator.innerHTML = `<i class="fas fa-exclamation-triangle"></i> ${_('playground.connection_error')}`;
                if (els.streamToggle) {
                    els.streamToggle.disabled = true;
                    els.streamToggle.checked = false;
                }
                state.streamingMode = false;
                updateGenerateButtonLabel();
                break;
            default:
                els.streamingIndicator.classList.add('disconnected');
                els.streamingIndicator.innerHTML = `<i class="fas fa-plug"></i> ${_('playground.streaming_offline')}`;
                if (els.streamToggle) {
                    els.streamToggle.disabled = true;
                    els.streamToggle.checked = false;
                }
                state.streamingMode = false;
                updateGenerateButtonLabel();
                break;
        }
    }
    async function checkAuthStatus() {
        try {
            const response = await fetch('/api/auth-status');
            const data = await response.json();
            state.apiKeyRequired = data.api_key_required === true;
            const section = document.getElementById('api-key-section');
            if (!section) {
                return;
            }
            if (data.api_key_required) {
                section.style.display = 'block';
                if (els.apiKeyInput) {
                    els.apiKeyInput.required = true;
                }
            } else {
                section.style.display = 'none';
            }
        } catch (error) {
            console.warn('Could not check auth status:', error);
        }
    }

    async function loadCapabilities() {
        try {
            const response = await fetch('/api/capabilities');
            if (!response.ok) {
                console.warn('Failed to load capabilities, assuming full image');
                return;
            }
            const caps = await response.json();
            state.capabilities = caps;
            updateUIForCapabilities(caps);
        } catch (error) {
            console.error('Failed to load capabilities:', error);
        }
    }

    function updateUIForCapabilities(caps) {
        if (!caps) return;

        // Update speed slider if ffmpeg not available
        const speedSlider = document.getElementById('speed-slider');
        const speedValue = document.getElementById('speed-value');
        if (speedSlider && !caps.features.speed_adjustment) {
            speedSlider.disabled = true;
            speedSlider.title = 'Speed adjustment requires full Docker image';
            if (speedValue) {
                speedValue.insertAdjacentHTML('afterend',
                    '<small class="text-warning ms-2">⚠️ Requires full image</small>');
            }
        }

        // Filter format options based on availability
        const formatSelect = document.getElementById('format-select');
        if (formatSelect && caps.supported_formats) {
            Array.from(formatSelect.options).forEach(option => {
                if (!caps.supported_formats.includes(option.value)) {
                    option.disabled = true;
                    option.textContent += ' (requires full image)';
                }
            });
        }

        // Show image variant badge in navbar
        const variant = caps.image_variant;
        const badgeHtml = variant === 'full'
            ? '<span class="badge bg-success ms-2">Full Image</span>'
            : '<span class="badge bg-warning ms-2">Slim Image</span>';

        const navbar = document.querySelector('.navbar-brand');
        if (navbar && !document.querySelector('.image-variant-badge')) {
            const badge = document.createElement('span');
            badge.className = 'image-variant-badge';
            badge.innerHTML = badgeHtml;
            navbar.appendChild(badge);
        }
    }

    async function loadVoices({ refresh = false } = {}) {
        try {
            const data = await fetchVoices({ refresh });
            if (!els.voiceSelect) {
                return;
            }
            els.voiceSelect.innerHTML = '';
            data.voices.forEach((voice) => {
                const option = document.createElement('option');
                option.value = voice.id;
                option.textContent = voice.name;
                if (voice.id === 'alloy') {
                    option.selected = true;
                }
                els.voiceSelect.appendChild(option);
            });
            updateAudioSummary();
        } catch (error) {
            console.error('Failed to load voices:', error);
        }
    }

    async function loadFormats({ refresh = false } = {}) {
        try {
            if (!els.formatSelect) {
                return;
            }

            // If format select already has options (from HTML), don't reload
            if (els.formatSelect.options.length > 1 && !refresh) {
                updateAudioSummary();
                return;
            }

            const data = await fetchFormats({ refresh });
            els.formatSelect.innerHTML = '';
            data.formats.forEach((format) => {
                const option = document.createElement('option');
                option.value = format.id;
                option.textContent = `${format.name} - ${format.quality}`;
                if (format.id === 'mp3') {
                    option.selected = true;
                }
                els.formatSelect.appendChild(option);
            });
            updateAudioSummary();
        } catch (error) {
            console.error('Failed to load formats:', error);
        }
    }

    function updateCharCount() {
        const current = els.textInput ? els.textInput.value.length : 0;
        const max = getChunkMaxLength();
        if (els.charCount) {
            els.charCount.textContent = current;
            if (current > max) {
                els.charCount.className = 'text-danger fw-bold';
            } else if (current > max * 0.8) {
                els.charCount.className = 'text-warning fw-bold';
            } else {
                els.charCount.className = '';
            }
        }
        updateLengthStatus(current, max);
    }

    function updateSpeedDisplay() {
        if (!els.speedInput || !els.speedValueDisplay) {
            return;
        }
        const speed = parseFloat(els.speedInput.value);
        els.speedValueDisplay.textContent = `${speed.toFixed(2)}x`;
    }

    function updateLengthStatus(current, max) {
        if (!els.lengthStatus) {
            return;
        }
        const validateEnabled = !els.validateLengthCheck || els.validateLengthCheck.checked;
        if (!validateEnabled) {
            els.lengthStatus.textContent = '';
            els.lengthStatus.className = '';
        } else if (current === 0) {
            els.lengthStatus.textContent = 'Waiting for input...';
            els.lengthStatus.className = 'text-muted';
        } else {
            const remaining = max - current;
            if (remaining >= 0) {
                els.lengthStatus.textContent = `${remaining} characters remaining`;
                els.lengthStatus.className = remaining <= Math.max(50, max * 0.05) ? 'text-warning' : 'text-success';
            } else {
                els.lengthStatus.textContent = `${Math.abs(remaining)} characters over the limit`;
                els.lengthStatus.className = 'text-danger fw-bold';
            }
        }
        if (els.autoCombineStatus) {
            const shouldShow = els.autoCombineCheck && els.autoCombineCheck.checked && current > max;
            if (shouldShow) {
                els.autoCombineStatus.classList.remove('d-none');
            } else {
                els.autoCombineStatus.classList.add('d-none');
            }
        }
    }

    function clearText() {
        if (!els.textInput) {
            return;
        }
        els.textInput.value = '';
        updateCharCount();
        els.textInput.focus();
    }

    function loadRandomText() {
        if (!els.textInput) {
            return;
        }
        const sample = SAMPLE_TEXTS[Math.floor(Math.random() * SAMPLE_TEXTS.length)];
        els.textInput.value = sample;
        updateCharCount();
        els.textInput.focus();
    }

    function validateText() {
        if (!els.lengthStatus) {
            return;
        }
        const current = els.textInput ? els.textInput.value.length : 0;
        const max = getChunkMaxLength();
        updateLengthStatus(current, max);
        if (current === 0) {
            els.lengthStatus.textContent = 'Add some text to generate speech.';
            els.lengthStatus.className = 'text-warning';
        } else if (current <= max) {
            els.lengthStatus.textContent = 'Text length looks good!';
            els.lengthStatus.className = 'text-success fw-bold';
        }
    }

    function resetForm() {
        if (els.form) {
            els.form.reset();
        }
        if (els.textInput) {
            els.textInput.value = state.defaultText;
        }
        state.audioBlob = null;
        state.audioUrl = null;
        state.meta = null;
        hideResults();
        hideError();
        updateCharCount();
        updateAudioSummary();
        updateActionButtons(false);
        if (els.streamToggle) {
            els.streamToggle.checked = false;
        }
        state.streamingMode = false;
        updateGenerateButtonLabel();
        if (els.streamingProgress) {
            const summaries = els.streamingProgress.querySelectorAll('.alert');
            summaries.forEach((node) => node.remove());
            resetStreamingUi();
            els.streamingProgress.style.display = 'none';
        }
    }
    function showLoading() {
        if (els.loadingBox) {
            els.loadingBox.style.display = 'block';
        }
    }

    function hideLoading() {
        if (els.loadingBox) {
            els.loadingBox.style.display = 'none';
        }
    }

    function showError(message) {
        if (els.errorBox) {
            els.errorBox.style.display = 'block';
            els.errorBox.textContent = message;
        }
    }

    function hideError() {
        if (els.errorBox) {
            els.errorBox.style.display = 'none';
        }
    }

    function setFormDisabled(disabled) {
        [els.generateBtn, els.textInput, els.voiceSelect, els.formatSelect, els.instructionsInput, els.validateBtn, els.randomBtn, els.clearBtn].forEach((element) => {
            if (element) {
                element.disabled = disabled;
            }
        });
    }

    function showResults(blob, meta) {
        if (state.audioUrl) {
            URL.revokeObjectURL(state.audioUrl);
        }
        state.audioUrl = URL.createObjectURL(blob);
        state.meta = meta;

        if (els.audioPlayer) {
            els.audioPlayer.src = state.audioUrl;
            els.audioPlayer.load();
            els.audioPlayer.addEventListener('loadedmetadata', () => {
                if (isFinite(els.audioPlayer.duration)) {
                    state.meta.durationSeconds = els.audioPlayer.duration;
                    updateAudioSummary();
                }
            }, { once: true });
        }

        if (els.audioResult) {
            els.audioResult.classList.remove('d-none');
            els.audioResult.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }

        updateAudioSummary();
        updateActionButtons(true);
    }

    function hideResults() {
        if (els.audioResult) {
            els.audioResult.classList.add('d-none');
        }
        if (els.audioPlayer) {
            els.audioPlayer.pause();
            els.audioPlayer.src = '';
        }
        if (state.audioUrl) {
            URL.revokeObjectURL(state.audioUrl);
            state.audioUrl = null;
        }
        state.audioBlob = null;
        state.meta = null;
        updateAudioSummary();
        updateActionButtons(false);
    }

    function updateAudioSummary() {
        const meta = state.meta;
        if (!meta) {
            if (els.audioInfo) {
                els.audioInfo.textContent = '';
            }
            if (els.audioDuration) {
                els.audioDuration.textContent = '--';
            }
            if (els.audioSize) {
                els.audioSize.textContent = '--';
            }
            if (els.audioVoice) {
                els.audioVoice.textContent = '--';
            }
            if (els.audioFormat) {
                els.audioFormat.textContent = '--';
            }
            if (els.audioSpeed) {
                els.audioSpeed.textContent = '--';
            }
            if (els.audioChunks) {
                els.audioChunks.textContent = '--';
            }
            return;
        }

        if (els.audioDuration) {
            els.audioDuration.textContent = meta.durationSeconds ? formatDuration(meta.durationSeconds) : '--';
        }
        if (els.audioSize) {
            els.audioSize.textContent = formatBytes(meta.sizeBytes || (state.audioBlob ? state.audioBlob.size : 0));
        }
        if (els.audioVoice) {
            els.audioVoice.textContent = meta.voiceLabel || meta.voice || '--';
        }
        if (els.audioFormat) {
            const label = meta.formatLabel || meta.format || state.format;
            els.audioFormat.textContent = label ? label.toString().toUpperCase() : '--';
        }
        if (els.audioSpeed) {
            const speedValue = meta.speed !== undefined && meta.speed !== null ? meta.speed : 1.0;
            els.audioSpeed.textContent = `${speedValue}x`;
        }
        if (els.audioChunks) {
            els.audioChunks.textContent = meta.chunks || '1';
        }
        if (els.audioInfo) {
            const parts = [];
            if (meta.generatedAt) {
                parts.push(`${_('common.generated')} ${formatClock(meta.generatedAt)}`);
            }
            if (meta.streaming) {
                parts.push(_('common.streaming'));
            }
            if (typeof meta.textLength === 'number') {
                parts.push(`${meta.textLength} ${_('common.chars')}`);
            }
            if (meta.sizeBytes || (state.audioBlob && state.audioBlob.size)) {
                parts.push(formatBytes(meta.sizeBytes || state.audioBlob.size));
            }
            if (meta.durationSeconds) {
                parts.push(formatDuration(meta.durationSeconds));
            }
            els.audioInfo.textContent = parts.join(' | ');
        }
    }

    function updateActionButtons(enabled) {
        [els.downloadBtn, els.shareBtn, els.replayBtn].forEach((button) => {
            if (button) {
                button.disabled = !enabled;
            }
        });
    }
    function downloadAudio() {
        if (!state.audioBlob) {
            return;
        }
        const format = (state.meta?.format || state.format || 'mp3').replace(/[^a-z0-9]/gi, '');
        const fileName = buildDownloadFileName(format);
        const url = URL.createObjectURL(state.audioBlob);
        const link = document.createElement('a');
        link.href = url;
        link.download = fileName;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
    }

    function replayAudio() {
        if (!els.audioPlayer || !els.audioPlayer.src) {
            return;
        }
        try {
            els.audioPlayer.currentTime = 0;
            els.audioPlayer.play().catch(() => {});
        } catch (error) {
            console.warn('Unable to replay audio:', error);
        }
    }

    async function shareAudio() {
        if (!state.audioBlob) {
            return;
        }
        const format = state.meta?.format || state.format || 'mp3';
        const fileName = buildDownloadFileName(format);
        const file = new File([state.audioBlob], fileName, { type: `audio/${format}` });
        const shareText = buildShareText();

        if (navigator.canShare && navigator.canShare({ files: [file] })) {
            try {
                await navigator.share({ files: [file], title: 'TTSFM Audio', text: shareText });
                return;
            } catch (error) {
                if (error?.name === 'AbortError') {
                    return;
                }
                console.warn('Share failed, falling back to clipboard.', error);
            }
        }

        if (navigator.clipboard && window.isSecureContext) {
            try {
                await navigator.clipboard.writeText(shareText);
                if (els.audioInfo) {
                    els.audioInfo.textContent = `${shareText} (copied to clipboard)`;
                }
                return;
            } catch (error) {
                console.warn('Clipboard copy failed:', error);
            }
        }

        showError('Sharing is not supported in this browser. Please download the audio instead.');
    }

    function toggleApiKeyVisibility() {
        if (!els.apiKeyInput) {
            return;
        }
        const eyeIcon = document.getElementById('api-key-eye-icon');
        if (els.apiKeyInput.type === 'password') {
            els.apiKeyInput.type = 'text';
            if (eyeIcon) {
                eyeIcon.className = 'fas fa-eye-slash';
            }
        } else {
            els.apiKeyInput.type = 'password';
            if (eyeIcon) {
                eyeIcon.className = 'fas fa-eye';
            }
        }
    }

    function buildGenerationMeta(overrides) {
        return {
            voice: overrides.voice,
            voiceLabel: overrides.voiceLabel,
            format: overrides.format,
            formatLabel: overrides.formatLabel,
            textLength: overrides.textLength,
            instructions: overrides.instructions,
            streaming: overrides.streaming,
            sizeBytes: overrides.sizeBytes,
            chunks: overrides.chunks || 0,
            elapsedMs: overrides.elapsedMs,
            generatedAt: overrides.generatedAt || new Date(),
            speed: overrides.speed,
            speedApplied: overrides.speedApplied
        };
    }

    function buildDownloadFileName(format) {
        const voicePart = state.meta?.voice || state.meta?.voiceLabel || 'voice';
        const safeVoice = slugify(voicePart || 'voice');
        const timestamp = new Date().toISOString().replace(/[:T]/g, '-').split('.')[0];
        return `tts-${safeVoice}-${timestamp}.${format}`;
    }

    function buildShareText() {
        const meta = state.meta || {};
        const parts = ['TTSFM generation'];
        if (meta.voiceLabel || meta.voice) {
            parts.push(`Voice: ${meta.voiceLabel || meta.voice}`);
        }
        if (meta.format) {
            parts.push(`Format: ${meta.format.toUpperCase()}`);
        }
        if (meta.textLength) {
            parts.push(`Length: ${meta.textLength} characters`);
        }
        if (meta.durationSeconds) {
            parts.push(`Duration: ${formatDuration(meta.durationSeconds)}`);
        }
        return parts.join(' | ');
    }

    function formatBytes(bytes) {
        if (!bytes || Number.isNaN(bytes)) {
            return '0 KB';
        }
        if (bytes < 1024) {
            return `${bytes} B`;
        }
        if (bytes < 1024 * 1024) {
            return `${(bytes / 1024).toFixed(1)} KB`;
        }
        return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
    }

    function formatDuration(seconds) {
        if (!seconds || !isFinite(seconds)) {
            return '--';
        }
        if (seconds < 60) {
            return `${seconds.toFixed(1)}s`;
        }
        const minutes = Math.floor(seconds / 60);
        const remaining = Math.round(seconds % 60);
        return `${minutes}:${remaining.toString().padStart(2, '0')} min`;
    }

    function formatClock(date) {
        if (!(date instanceof Date)) {
            return '';
        }
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }

    function getSelectedText(select) {
        if (!select) {
            return '';
        }
        const option = select.options[select.selectedIndex];
        return option ? option.textContent : '';
    }

    function slugify(value) {
        return (value || '').toString().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'audio';
    }

    return { init };
})();

document.addEventListener('DOMContentLoaded', () => {
    PlaygroundApp.init();
});
// Streaming styles injected dynamically for visual feedback.
const style = document.createElement('style');
style.textContent = `
.streaming-controls {
    padding: 15px;
    background-color: #f8f9fa;
    border-radius: 8px;
}

.streaming-status {
    display: inline-block;
    padding: 5px 10px;
    border-radius: 20px;
    font-size: 0.875rem;
    font-weight: 500;
}

.streaming-status.connected {
    background-color: #d4edda;
    color: #155724;
}

.streaming-status.disconnected {
    background-color: #f8d7da;
    color: #721c24;
}

.streaming-status.error {
    background-color: #fff3cd;
    color: #856404;
}

.streaming-status.streaming {
    background-color: #cce5ff;
    color: #004085;
    animation: pulse 1.5s infinite;
}

@keyframes pulse {
    0% { opacity: 1; }
    50% { opacity: 0.7; }
    100% { opacity: 1; }
}

.streaming-progress-section {
    margin-bottom: 20px;
}

.chunks-visual {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
}

.chunk-indicator {
    width: 30px;
    height: 30px;
    background-color: #007bff;
    color: white;
    border-radius: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.75rem;
    animation: chunkAppear 0.3s ease-out;
}

@keyframes chunkAppear {
    from {
        transform: scale(0);
        opacity: 0;
    }
    to {
        transform: scale(1);
        opacity: 1;
    }
}
`;
document.head.appendChild(style);
