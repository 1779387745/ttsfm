import types

import pytest

from ttsfm.async_client import AsyncTTSClient
from ttsfm.client import TTSClient
from ttsfm.models import AudioFormat, TTSResponse


def _mk_response(data: bytes) -> TTSResponse:
    return TTSResponse(
        audio_data=data,
        content_type="audio/mpeg",
        format=AudioFormat.MP3,
        size=len(data),
    )


class _DummyResponse:
    def __init__(self, content_type: str, content: bytes, url: str = "https://example.test/audio"):
        self.status_code = 200
        self.headers = {"content-type": content_type}
        self.content = content
        self.url = url
        self.text = ""

    def json(self):  # pragma: no cover - not used on success path
        return {}


def test_sync_request_normalizes_non_mp3_format(monkeypatch):
    client = TTSClient()
    captured = {}

    def fake_post(self, url, data=None, headers=None, timeout=None, verify=None):
        captured["data"] = data
        return _DummyResponse("audio/wav", b"RIFF" + b"\x00" * 64, url)

    monkeypatch.setattr(client.session, "post", types.MethodType(fake_post, client.session))

    response = client.generate_speech(text="hello", voice="alloy", response_format=AudioFormat.FLAC)

    assert captured["data"]["response_format"] == "wav"
    assert response.format is AudioFormat.WAV


def test_sync_request_preserves_mp3_format(monkeypatch):
    client = TTSClient()
    captured = {}

    def fake_post(self, url, data=None, headers=None, timeout=None, verify=None):
        captured["data"] = data
        return _DummyResponse("audio/mpeg", b"ID3" + b"\x00" * 64, url)

    monkeypatch.setattr(client.session, "post", types.MethodType(fake_post, client.session))

    response = client.generate_speech(text="hello", voice="alloy", response_format=AudioFormat.MP3)

    assert captured["data"]["response_format"] == "mp3"
    assert response.format is AudioFormat.MP3


def test_sync_long_text_auto_combine(monkeypatch):
    client = TTSClient()

    monkeypatch.setattr(
        client,
        "generate_speech_batch",
        lambda **kwargs: [_mk_response(b"one"), _mk_response(b"two")],
    )

    combined_flag = {}

    def fake_combine(responses):
        combined_flag["called"] = True
        return _mk_response(b"onetwo")

    monkeypatch.setattr("ttsfm.client.combine_responses", fake_combine)

    result = client.generate_speech_long_text(
        text="dummy",
        auto_combine=True,
    )

    assert combined_flag["called"] is True
    assert isinstance(result, TTSResponse)
    assert result.audio_data == b"onetwo"


def test_sync_long_text_returns_list_without_auto_combine(monkeypatch):
    client = TTSClient()

    responses = [_mk_response(b"one")]
    monkeypatch.setattr(client, "generate_speech_batch", lambda **_: responses)

    result = client.generate_speech_long_text(text="dummy", auto_combine=False)

    assert result is responses


def test_sync_generate_speech_batch_uses_parallel_sessions(monkeypatch):
    parallel_hits = {"n": 0}
    spawn_hits = {"n": 0}
    orig_spawn = TTSClient._spawn_worker_session

    def counting_spawn(self):
        spawn_hits["n"] += 1
        return orig_spawn(self)

    def fake_make(self, request, http_session=None):
        if http_session is not None:
            parallel_hits["n"] += 1
        return _mk_response(request.input.encode())

    monkeypatch.setattr(TTSClient, "_make_request", fake_make)
    monkeypatch.setattr(TTSClient, "_spawn_worker_session", counting_spawn)
    client = TTSClient()
    text = "x" * 2000
    parts = client.generate_speech_batch(
        text=text,
        max_length=400,
        preserve_words=False,
        max_concurrent_chunks=2,
    )
    assert len(parts) == 5
    assert parallel_hits["n"] == 5
    assert 1 <= spawn_hits["n"] <= 2


@pytest.mark.asyncio
async def test_async_long_text_auto_combine(monkeypatch):
    client = AsyncTTSClient()

    async def fake_batch(**kwargs):
        return [_mk_response(b"one"), _mk_response(b"two")]

    monkeypatch.setattr(client, "generate_speech_batch", fake_batch)

    def fake_combine(responses):
        return _mk_response(b"onetwo")

    monkeypatch.setattr("ttsfm.async_client.combine_responses", fake_combine)

    result = await client.generate_speech_long_text(
        text="dummy",
        auto_combine=True,
    )

    assert isinstance(result, TTSResponse)
    assert result.audio_data == b"onetwo"
