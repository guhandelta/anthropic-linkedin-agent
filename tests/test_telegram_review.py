import json
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch

import telegram_review


@pytest.fixture
def tmp_state(tmp_path: Path, monkeypatch):
    state_file = tmp_path / "drafts.json"
    monkeypatch.setattr(telegram_review, "STATE", state_file)
    return state_file


def test_get_and_set_status(tmp_state):
    assert telegram_review.get_status("draft-1") is None

    telegram_review.set_status("draft-1", "pending", topic="React 19")
    assert telegram_review.get_status("draft-1") == "pending"

    data = telegram_review._load()
    assert data["draft-1"]["topic"] == "React 19"


def test_call_success_and_failure(monkeypatch):
    reviewer = telegram_review.TelegramReviewer("test-token", "12345")

    # Mock successful call
    mock_resp_ok = MagicMock()
    mock_resp_ok.json.return_value = {"ok": True, "result": {"message_id": 999}}
    monkeypatch.setattr(telegram_review.requests, "post", MagicMock(return_value=mock_resp_ok))

    res = reviewer._call("sendMessage", text="Hello")
    assert res["message_id"] == 999

    # Mock failed call
    mock_resp_err = MagicMock()
    mock_resp_err.json.return_value = {"ok": False, "description": "Chat not found"}
    monkeypatch.setattr(telegram_review.requests, "post", MagicMock(return_value=mock_resp_err))

    with pytest.raises(RuntimeError, match="Telegram sendMessage failed"):
        reviewer._call("sendMessage", text="Hello")


def test_progress_tracker_and_update(monkeypatch):
    reviewer = telegram_review.TelegramReviewer("test-token", "12345")
    mock_call = MagicMock(return_value={"message_id": 555})
    monkeypatch.setattr(reviewer, "_call", mock_call)

    msg_id = reviewer.send_progress_tracker("Testing Pipeline")
    assert msg_id == 555
    mock_call.assert_called_with("sendMessage", chat_id="12345", text="⏳ **Testing Pipeline**\n\n🔄 Starting pipeline...")

    reviewer.update_progress(555, "Step 1 complete")
    mock_call.assert_called_with("editMessageText", chat_id="12345", message_id=555, text="Step 1 complete")


def test_send_draft_gif_and_png(tmp_path: Path, monkeypatch, tmp_state):
    reviewer = telegram_review.TelegramReviewer("test-token", "12345")
    monkeypatch.setattr(reviewer, "_skip_old_updates", MagicMock())
    mock_call = MagicMock(return_value={"message_id": 888})
    monkeypatch.setattr(reviewer, "_call", mock_call)

    # Test PNG draft
    png_path = tmp_path / "test.png"
    png_path.write_bytes(b"dummy png bytes")
    msg_id = reviewer.send_draft("draft-png", "TypeScript 5.8", "Full post text here", png_path)
    assert msg_id == 888
    assert telegram_review.get_status("draft-png") == "pending"

    # Test GIF draft
    gif_path = tmp_path / "test.gif"
    gif_path.write_bytes(b"dummy gif bytes")
    msg_id_gif = reviewer.send_draft("draft-gif", "Animated Flow", "Full post text here", gif_path)
    assert msg_id_gif == 888
    assert telegram_review.get_status("draft-gif") == "pending"


def test_send_text_draft(monkeypatch, tmp_state):
    reviewer = telegram_review.TelegramReviewer("test-token", "12345")
    monkeypatch.setattr(reviewer, "_skip_old_updates", MagicMock())
    mock_call = MagicMock(return_value={"message_id": 777})
    monkeypatch.setattr(reviewer, "_call", mock_call)

    msg_id = reviewer.send_text_draft("draft-txt", "Text Direct", "Just plain text content")
    assert msg_id == 777
    assert telegram_review.get_status("draft-txt") == "pending"


def test_long_review_text_is_sent_in_full_before_approval(monkeypatch, tmp_state):
    reviewer = telegram_review.TelegramReviewer("test-token", "12345")
    monkeypatch.setattr(reviewer, "_skip_old_updates", MagicMock())
    calls = []

    def fake_call(method, **kwargs):
        calls.append((method, kwargs))
        return {"message_id": len(calls)}

    monkeypatch.setattr(reviewer, "_call", fake_call)
    reviewer.send_text_draft("long-draft", "Technical topic", "x" * 8200)
    messages = [kwargs for method, kwargs in calls if method == "sendMessage"]
    assert len(messages) > 1
    assert sum(len(message["text"]) for message in messages) > 8200
    assert all("reply_markup" not in message for message in messages[:-1])
    assert "reply_markup" in messages[-1]


def test_prompt_direct_choice_infographic(monkeypatch):
    reviewer = telegram_review.TelegramReviewer("test-token", "12345")
    cid = "testcid1"
    mock_call = MagicMock()
    mock_call.side_effect = [
        {"message_id": 10},
        [{"update_id": 1, "callback_query": {"id": "cq1", "data": f"direct_info:{cid}",
                                              "from": {"id": 12345}, "message": {"chat": {"id": 12345}}}}],
        None,  # answerCallbackQuery
        None,  # editMessageReplyMarkup
    ]
    monkeypatch.setattr(reviewer, "_call", mock_call)
    monkeypatch.setattr(telegram_review.uuid, "uuid4", MagicMock(return_value=MagicMock(hex=cid)))

    choice = reviewer.prompt_direct_choice("Direct post content", timeout_s=10)
    assert choice == "infographic"


def test_prompt_direct_choice_text_only(monkeypatch):
    reviewer = telegram_review.TelegramReviewer("test-token", "12345")
    cid = "testcid2"
    mock_call = MagicMock()
    mock_call.side_effect = [
        {"message_id": 10},
        [{"update_id": 1, "callback_query": {"id": "cq1", "data": f"direct_text:{cid}",
                                              "from": {"id": 12345}, "message": {"chat": {"id": 12345}}}}],
        None,
        None,
    ]
    monkeypatch.setattr(reviewer, "_call", mock_call)
    monkeypatch.setattr(telegram_review.uuid, "uuid4", MagicMock(return_value=MagicMock(hex=cid)))

    choice = reviewer.prompt_direct_choice("Direct post content", timeout_s=10)
    assert choice == "text_only"


def test_prompt_direct_choice_cancel(monkeypatch):
    reviewer = telegram_review.TelegramReviewer("test-token", "12345")
    cid = "testcid3"
    mock_call = MagicMock()
    mock_call.side_effect = [
        {"message_id": 10},
        [{"update_id": 1, "callback_query": {"id": "cq1", "data": f"direct_cancel:{cid}",
                                              "from": {"id": 12345}, "message": {"chat": {"id": 12345}}}}],
        None,
        None,
    ]
    monkeypatch.setattr(reviewer, "_call", mock_call)
    monkeypatch.setattr(telegram_review.uuid, "uuid4", MagicMock(return_value=MagicMock(hex=cid)))

    choice = reviewer.prompt_direct_choice("Direct post content", timeout_s=10)
    assert choice == "cancel"


def test_wait_for_decision_approve(monkeypatch, tmp_state):
    reviewer = telegram_review.TelegramReviewer("test-token", "12345", timeout_s=10, remind_every_s=5)
    telegram_review.set_status("d1", "pending")

    mock_call = MagicMock()
    mock_call.side_effect = [
        # getUpdates returns approve callback
        [{"update_id": 100, "callback_query": {"id": "cq_app", "data": "approve:d1", "from": {"id": 12345}, "message": {"chat": {"id": 12345}}}}],
        None, # answerCallbackQuery
        None, # editMessageReplyMarkup
    ]
    monkeypatch.setattr(reviewer, "_call", mock_call)

    decision = reviewer.wait_for_decision("d1", 10)
    assert decision == {"action": "approved"}
    assert telegram_review.get_status("d1") == "approved"


def test_wait_for_decision_timeout(monkeypatch, tmp_state):
    reviewer = telegram_review.TelegramReviewer("test-token", "12345", timeout_s=0.1, remind_every_s=100)
    telegram_review.set_status("d_timeout", "pending")
    monkeypatch.setattr(reviewer, "_call", MagicMock(return_value=[]))

    decision = reviewer.wait_for_decision("d_timeout", 10)
    assert decision == {"action": "expired"}
    assert telegram_review.get_status("d_timeout") == "expired"


def test_download_photo(tmp_path: Path, monkeypatch):
    reviewer = telegram_review.TelegramReviewer("test-token", "12345")
    mock_call = MagicMock(return_value={"file_path": "photos/test.jpg"})
    monkeypatch.setattr(reviewer, "_call", mock_call)

    mock_get = MagicMock()
    mock_get.return_value.content = b"fake photo bytes"
    monkeypatch.setattr(telegram_review.requests, "get", mock_get)

    dest = tmp_path / "downloaded.jpg"
    res = reviewer.download_photo([{"file_id": "f123"}], dest)
    assert res == dest
    assert dest.read_bytes() == b"fake photo bytes"


def test_download_photo_empty_raises():
    reviewer = telegram_review.TelegramReviewer("test-token", "12345")
    with pytest.raises(ValueError, match="No photo found"):
        reviewer.download_photo([], Path("out.jpg"))


def test_set_bot_commands(monkeypatch):
    reviewer = telegram_review.TelegramReviewer("test-token", "12345")
    mock_call = MagicMock(return_value=True)
    monkeypatch.setattr(reviewer, "_call", mock_call)

    assert reviewer.set_bot_commands() is True
    assert mock_call.call_count >= 2
