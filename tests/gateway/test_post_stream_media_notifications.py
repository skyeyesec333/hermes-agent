"""Final streamed attachments notify like non-streamed attachments (#144897)."""

from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import Platform, PlatformConfig
from gateway.platforms.event import MessageEvent
from gateway.run import GatewayRunner
from gateway.session import SessionSource
from plugins.platforms.telegram import adapter as telegram


def _delivery(tmp_path, monkeypatch, kind):
    media = tmp_path / ("reply.ogg" if kind == "voice" else "reply.pdf")
    media.write_bytes(b"synthetic attachment")
    monkeypatch.setattr("gateway.platforms.base.MEDIA_DELIVERY_SAFE_ROOTS", (tmp_path,))
    monkeypatch.setattr(telegram, "_probe_voice_duration_seconds", lambda _path: 1)
    adapter = telegram.TelegramAdapter(PlatformConfig(enabled=True, token="test-token", extra={}))
    adapter._notifications_mode = "important"
    adapter._bot, adapter._app = AsyncMock(), MagicMock()
    send = AsyncMock(return_value=SimpleNamespace(message_id=1))
    setattr(adapter._bot, "send_voice" if kind == "voice" else "send_document", send)
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="123", chat_type="group", thread_id="42")
    event = MessageEvent(text="send the result", source=source, message_id="11")
    metadata = {"thread_id": "42", "hermes_profile": "secondary"}
    runner = SimpleNamespace(
        _delivery_adapter_for=lambda _source: adapter,
        _should_send_voice_reply=lambda *_args, **_kwargs: False,
        _thread_metadata_for_source=lambda *_args: metadata,
        _reply_anchor_for_event=lambda _event: None,
    )
    runner._deliver_media_from_response = MethodType(GatewayRunner._deliver_media_from_response, runner)
    response = ("[[audio_as_voice]]\n" if kind == "voice" else "") + f"MEDIA:{media}"
    return runner, adapter, source, event, metadata, response, send


@pytest.mark.asyncio
@pytest.mark.parametrize("lane", ["final", "queued"])
@pytest.mark.parametrize("kind", ["voice", "document"])
async def test_final_streamed_attachment_notifies_without_mutating_route(tmp_path, monkeypatch, lane, kind):
    """Use real extraction, final/queued callers and Telegram send code; mock only upload/probing."""
    runner, adapter, source, event, metadata, response, send = _delivery(tmp_path, monkeypatch, kind)
    if lane == "final":
        result = await GatewayRunner._hmwa_deliver_turn_response(
            runner, event, source, SimpleNamespace(session_id="session"), "session", 1,
            {"already_sent": True}, [], response, None, False,
        )
        assert result is None  # the streamed text must not be delivered again
    else:
        assert await GatewayRunner._deliver_queued_first_response(
            runner, response, source, adapter, metadata=metadata, text_already_delivered=True,
        )
    send.assert_awaited_once()
    assert not send.await_args.kwargs.get("disable_notification", False)
    assert send.await_args.kwargs["message_thread_id"] == 42
    assert metadata == {"thread_id": "42", "hermes_profile": "secondary"}


@pytest.mark.asyncio
@pytest.mark.parametrize("result_flags", [{"media_already_delivered": True}, {"failed": True}])
async def test_streamed_attachment_guards_still_skip_upload(tmp_path, monkeypatch, result_flags):
    runner, _adapter, source, event, _metadata, response, send = _delivery(tmp_path, monkeypatch, "voice")
    await GatewayRunner._hmwa_deliver_turn_response(
        runner, event, source, SimpleNamespace(session_id="session"), "session", 1,
        {"already_sent": True, **result_flags}, [], response, None, False,
    )
    send.assert_not_awaited()
