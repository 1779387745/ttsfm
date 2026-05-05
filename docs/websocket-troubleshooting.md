# WebSocket streaming — troubleshooting

This page complements [WebSocket streaming](websocket-streaming.md) with practical fixes for common deployment issues.

## Connection failures

1. **Confirm the server is reachable**  
   Open `http://<host>:<port>/api/websocket/status` and check `websocket_enabled` and `active_sessions`.

2. **Firewall / reverse proxy**  
   Ensure WebSocket upgrades and long-lived connections are allowed on the path `/socket.io/`. Some proxies default to short read timeouts; raise them for streaming workloads.

3. **Transports**  
   The bundled client tries polling first, then upgrades to WebSocket. If WebSocket is blocked, polling should still work but may be slower.

## Authentication (`REQUIRE_API_KEY=true`)

- The browser client sends the key in the Socket.IO `auth` payload (`api_key`) and on each `generate_stream` event (`api_key` field). Enter the API key in the playground before enabling streaming, or refresh after changing the key so the socket reconnects with the new credentials.
- REST endpoints continue to accept `Authorization: Bearer …` and `X-API-Key` as documented.

## Encoding

Audio chunks use **Base64** in the `audio_data` field (`encoding: "base64"`). See the server-to-client section in [websocket-streaming.md](websocket-streaming.md).

## Async driver (`eventlet` / `threading` / `gevent`)

The Socket.IO server uses Flask-SocketIO’s ``async_mode``. Configure with ``TTSFM_SOCKETIO_ASYNC_MODE``:

| Value | When to use |
|-------|----------------|
| ``threading`` | Local ``DEBUG=true`` (default there); no monkey-patching in ``run.py``. |
| ``eventlet`` | Default in non-debug installs; legacy production path. |
| ``gevent`` | Preferred long-term; install ``pip install -e ".[web,web-gevent]"`` and set this value. |

``python ttsfm-web/run.py`` applies the matching monkey-patch **before** importing the Flask app. If you start the app another way, ensure the driver matches how you patch the stdlib.

## Further reading

- [WebSocket streaming](websocket-streaming.md) — API events, security notes, and deployment examples.
