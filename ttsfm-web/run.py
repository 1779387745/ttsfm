#!/usr/bin/env python
"""
Run script for TTSFM web application with async driver initialization.

``TTSFM_SOCKETIO_ASYNC_MODE`` selects the monkey-patch / worker model before Flask loads:
``eventlet`` (default in production), ``threading`` (typical for DEBUG), or ``gevent``.
For gevent, install the optional extra: ``pip install -e ".[web,web-gevent]"``.

Eventlet remains the default non-debug driver for compatibility; it is deprecated upstream
— prefer gevent for new deployments when you can validate your stack end-to-end.
"""

import os

from dotenv import load_dotenv

load_dotenv()

_mode = os.environ.get("TTSFM_SOCKETIO_ASYNC_MODE", "").strip().lower()
_debug = os.environ.get("DEBUG", "false").lower() == "true"
if not _mode:
    _mode = "threading" if _debug else "eventlet"

if _mode == "gevent":
    from gevent import monkey

    monkey.patch_all()
elif _mode == "eventlet":
    import eventlet

    eventlet.monkey_patch()
# threading: no monkey patch

from app import DEBUG, HOST, PORT, app, socketio  # noqa: E402

if __name__ == "__main__":
    print(f"Starting TTSFM with WebSocket support on {HOST}:{PORT} (async_mode={_mode})")
    socketio.run(app, host=HOST, port=PORT, debug=DEBUG, allow_unsafe_werkzeug=True)
