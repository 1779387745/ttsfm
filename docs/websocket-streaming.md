# 🚀 WebSocket Streaming for TTSFM

Real-time audio streaming for text-to-speech generation using WebSockets.

## Overview

The WebSocket streaming feature provides:
- **Real-time audio chunk delivery** as they're generated
- **Progress tracking** with live updates
- **Lower perceived latency** - start receiving audio before complete generation
- **Cancellable operations** - stop mid-generation if needed

## Quick Start

### 1. Docker Deployment (Recommended)

```bash
# Build with WebSocket support
docker build -t ttsfm-websocket .

# Run with WebSocket enabled
docker run -p 8000:8000 \
  -e DEBUG=false \
  ttsfm-websocket
```

### 2. Test WebSocket Connection

Visit `http://localhost:8000/websocket-demo` for an interactive demo.

### 3. Client Usage

```javascript
// Initialize WebSocket client
const client = new WebSocketTTSClient({
    socketUrl: 'http://localhost:8000',
    debug: true
});

// Generate speech with streaming
const result = await client.generateSpeech('Hello, WebSocket world!', {
    voice: 'alloy',
    format: 'mp3',
    onProgress: (progress) => {
        console.log(`Progress: ${progress.progress}%`);
    },
    onChunk: (chunk) => {
        console.log(`Received chunk ${chunk.chunkIndex + 1}`);
        // Process audio chunk in real-time
    },
    onComplete: (result) => {
        console.log('Generation complete!');
        // Play or download the combined audio
    }
});
```

## API Reference

### WebSocket Events

#### Client → Server

**`generate_stream`**
```javascript
{
    text: string,          // Text to convert
    voice: string,         // Voice ID (alloy, echo, etc.)
    format: string,        // Audio format (mp3, wav, opus)
    chunk_size: number,    // Optional, default 1024
    instructions: string,  // Optional, same semantics as REST / OpenAI API
    speed: number,         // Optional, 0.25–4.0 (applied server-side when supported)
    api_key: string        // Optional; required when REQUIRE_API_KEY=true
}
```

**`cancel_stream`**
```javascript
{
    request_id: string     // Request ID to cancel
}
```

#### Server → Client

**`stream_started`**
```javascript
{
    request_id: string,
    timestamp: number
}
```

**`audio_chunk`**
```javascript
{
    request_id: string,
    chunk_index: number,
    total_chunks: number,
    audio_data: string,    // Base64-encoded audio bytes
    encoding: string,      // "base64"
    format: string,
    duration: number,
    generation_time: number,
    chunk_text: string     // Preview of chunk text
}
```

**`stream_progress`**
```javascript
{
    request_id: string,
    progress: number,      // 0-100
    total_chunks: number,
    chunks_completed: number,
    status: string
}
```

**`stream_complete`**
```javascript
{
    request_id: string,
    total_chunks: number,
    status: 'completed',
    timestamp: number
}
```

**`stream_error`**
```javascript
{
    request_id: string,
    error: string,
    timestamp: number
}
```

## Performance Considerations

1. **Chunk Size**: Smaller chunks (512-1024 chars) provide more frequent updates but increase overhead
2. **Network Latency**: WebSocket reduces latency compared to HTTP polling
3. **Audio Buffering**: Client should buffer chunks for smooth playback
4. **Concurrent Streams**: Server supports multiple concurrent streaming sessions

## Browser Support

- Chrome/Edge: Full support
- Firefox: Full support
- Safari: Full support (iOS 11.3+)
- IE11: Not supported (use polling fallback)

## Troubleshooting

See also [WebSocket troubleshooting](websocket-troubleshooting.md) for auth, CORS, and proxy notes.

### Connection Issues
```javascript
// Check WebSocket status
fetch('/api/websocket/status')
    .then(res => res.json())
    .then(data => console.log('WebSocket status:', data));
```

### Debug Mode
```javascript
const client = new WebSocketTTSClient({
    debug: true  // Enable console logging
});
```

### Common Issues

1. **"WebSocket connection failed"**
   - Check if port 8000 is accessible
   - Ensure eventlet is installed: `pip install eventlet>=0.33.3`
   - Try polling transport as fallback

2. **"Chunks arriving out of order"**
   - Client automatically sorts chunks by index
   - Check network stability

3. **"Audio playback stuttering"**
   - Increase chunk size for better buffering
   - Check client-side audio buffer implementation

## Advanced Usage

### Custom Chunk Processing
```javascript
client.generateSpeech(text, {
    onChunk: async (chunk) => {
        // Custom processing per chunk
        const processed = await processAudioChunk(chunk.audioData);
        audioQueue.push(processed);
        
        // Start playback after first chunk
        if (chunk.chunkIndex === 0) {
            startStreamingPlayback(audioQueue);
        }
    }
});
```

### Progress Visualization
```javascript
client.generateSpeech(text, {
    onProgress: (progress) => {
        // Update UI progress bar
        progressBar.style.width = `${progress.progress}%`;
        statusText.textContent = `Processing chunk ${progress.chunksCompleted}/${progress.totalChunks}`;
    }
});
```

## Security

- When `REQUIRE_API_KEY=true`, connections are rejected unless a valid key is supplied on the Socket.IO handshake (`auth.api_key`) and each `generate_stream` payload must include the same key (defense in depth). Plaintext keys from the environment are compared in constant time; Argon2-hashed entries in `TTSFM_API_KEY_HASHES` still use Argon2 verification.
- Set `TTSFM_CORS_ORIGINS` to a comma-separated allowlist when you need credentialed cross-origin access; wildcard `*` is not used together with credentials in that configuration.
- SSL/TLS recommended for production deployments

## Deployment Notes

For production deployment with your existing setup:

```bash
# Build new image with WebSocket support
docker build -t ttsfm-websocket:latest .

# Deploy to your server (192.168.1.150)
docker stop ttsfm-container
docker rm ttsfm-container
docker run -d \
  --name ttsfm-container \
  -p 8000:8000 \
  -e REQUIRE_API_KEY=true \
  -e TTSFM_API_KEY=your-secret-key \
  -e DEBUG=false \
  ttsfm-websocket:latest
```

## Performance Metrics

Based on testing with openai.fm backend:
- First chunk delivery: ~0.5-1s
- Streaming overhead: ~10-15% vs batch processing
- Concurrent connections: 100+ (limited by server resources)
- Memory usage: ~50MB per active stream

*Built by a grumpy senior engineer who thinks HTTP was good enough*