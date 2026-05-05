import importlib

import pytest

import ttsfm.utils as utils


def test_split_text_rejects_max_length_over_upstream_limit():
    with pytest.raises(ValueError, match="1000"):
        utils.split_text_by_length("hello", max_length=1001)


def test_split_text_preserves_sentence_punctuation():
    text = "First sentence! Second question? Final statement."
    chunks = utils.split_text_by_length(text, max_length=15)

    assert chunks[0].endswith("!"), chunks
    assert any(chunk.endswith("?") for chunk in chunks), chunks
    assert chunks[-1].endswith("."), chunks


def test_split_text_handles_oversized_sentence():
    long_sentence = " ".join(["word"] * 600)
    chunks = utils.split_text_by_length(long_sentence, max_length=120)

    assert all(len(chunk) <= 120 for chunk in chunks)
    assert sum(len(chunk.split()) for chunk in chunks) == 600


def test_split_text_handles_extremely_long_word():
    max_length = 50
    painful_word = "a" * 140
    text = f"start {painful_word} end"

    chunks = utils.split_text_by_length(text, max_length=max_length)

    assert any(painful_word[:max_length] in chunk for chunk in chunks)
    assert all(len(chunk) <= max_length for chunk in chunks)


def test_sanitize_text_retains_ampersands():
    text = "R&D and Fish & Chips &amp; Co. <b>Bold</b>"
    sanitized = utils.sanitize_text(text)

    assert "R&D" in sanitized
    assert "Fish & Chips" in sanitized
    assert "Bold" in sanitized
    assert "<" not in sanitized


def test_header_generation_deterministic_upgrade_flag(monkeypatch):
    module = importlib.reload(utils)

    headers_first = module.get_realistic_headers()
    headers_second = module.get_realistic_headers()

    assert "Upgrade-Insecure-Requests" in headers_first
    assert "Upgrade-Insecure-Requests" not in headers_second
    assert headers_first["Accept-Language"] != headers_second["Accept-Language"]


@pytest.mark.asyncio
async def test_async_batch_propagates_original_exception(monkeypatch):
    from ttsfm.async_client import AsyncTTSClient
    from ttsfm.exceptions import NetworkException
    from ttsfm.models import TTSRequest, Voice

    client = AsyncTTSClient()

    async def fail_request(_request):
        raise NetworkException("boom")

    monkeypatch.setattr(client, "_make_request", fail_request)

    request = TTSRequest(input="hello", voice=Voice.ALLOY)

    with pytest.raises(NetworkException):
        await client.generate_speech_batch([request])
