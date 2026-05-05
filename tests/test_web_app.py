import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

WEB_DIR = Path(__file__).resolve().parents[1] / "ttsfm-web"
MODULE_NAME = "ttsfm_web.app"


def load_web_app(monkeypatch, **env):
    env = {"DEBUG": "true", **env}
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)

    sys.modules.pop(MODULE_NAME, None)
    sys.modules.pop("ttsfm_web", None)
    sys.modules.pop("websocket_handler", None)

    web_dir_str = str(WEB_DIR)
    if web_dir_str not in sys.path:
        sys.path.insert(0, web_dir_str)

    pkg_spec = importlib.util.spec_from_loader("ttsfm_web", loader=None)
    pkg = importlib.util.module_from_spec(pkg_spec)
    pkg.__path__ = [web_dir_str]  # type: ignore[attr-defined]
    sys.modules.setdefault("ttsfm_web", pkg)

    spec = importlib.util.spec_from_file_location(MODULE_NAME, WEB_DIR / "app.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def test_voices_endpoint_returns_data(monkeypatch):
    module = load_web_app(monkeypatch, REQUIRE_API_KEY="false", TTSFM_API_KEY=None)
    client = module.app.test_client()
    response = client.get("/api/voices")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["count"] == len(payload["voices"])


def test_combine_audio_chunks_uses_format_hint(monkeypatch):
    load_web_app(monkeypatch, REQUIRE_API_KEY="false", TTSFM_API_KEY=None)

    from ttsfm import audio as audio_module

    class DummySegment:
        def __init__(self, tag: str):
            self.tag = tag

        def __iadd__(self, other: "DummySegment"):
            self.tag += other.tag
            return self

        def export(self, buffer, format: str):
            buffer.write(f"{format}:{self.tag}".encode())

    class DummyAudioSegment:
        formats = []

        @classmethod
        def from_mp3(cls, buffer):
            cls.formats.append("mp3")
            return DummySegment("mp3")

        @classmethod
        def from_wav(cls, buffer):
            cls.formats.append("wav")
            return DummySegment("wav")

    monkeypatch.setattr(audio_module, "AudioSegment", DummyAudioSegment)

    output = audio_module.combine_audio_chunks([b"one", b"two"], "opus")

    assert output == b"wav:wavwav"
    assert DummyAudioSegment.formats == ["wav", "wav"]


@pytest.mark.parametrize(
    "header_name, header_value",
    [
        ("Authorization", "Bearer super-secret"),
        ("X-API-Key", "super-secret"),
    ],
)
def test_api_key_hash_verification(monkeypatch, header_name, header_value):
    module = load_web_app(monkeypatch, REQUIRE_API_KEY="true", TTSFM_API_KEY="super-secret")
    client = module.app.test_client()

    denied = client.post("/api/validate-text", json={"text": "hello"})
    assert denied.status_code == 401

    headers = {header_name: header_value}
    response = client.post("/api/validate-text", json={"text": "hello"}, headers=headers)
    assert response.status_code == 200
