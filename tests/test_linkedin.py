from pathlib import Path
import pytest
from unittest.mock import MagicMock

import linkedin


def test_linkedin_client_init_and_escape(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"sub": "user123"}
    mock_resp.raise_for_status = MagicMock()
    monkeypatch.setattr(linkedin.requests, "get", MagicMock(return_value=mock_resp))

    client = linkedin.LinkedInClient("test_token", "202610")
    assert client.author == "urn:li:person:user123"
    assert client.h["LinkedIn-Version"] == "202610"

    escaped = client._escape("Hello {world} @mention #tech")
    assert "\\{" in escaped
    assert "\\}" in escaped
    assert "\\@" in escaped


def test_upload_image(tmp_path: Path, monkeypatch):
    mock_resp_me = MagicMock()
    mock_resp_me.json.return_value = {"sub": "user123"}
    monkeypatch.setattr(linkedin.requests, "get", MagicMock(return_value=mock_resp_me))

    mock_post = MagicMock()
    mock_post.json.return_value = {
        "value": {
            "uploadUrl": "https://upload.linkedin.com/image",
            "image": "urn:li:image:img999",
        }
    }
    monkeypatch.setattr(linkedin.requests, "post", MagicMock(return_value=mock_post))
    monkeypatch.setattr(linkedin.requests, "put", MagicMock())

    client = linkedin.LinkedInClient("test_token", "202610")
    dummy_img = tmp_path / "img.png"
    dummy_img.write_bytes(b"test image")

    urn = client.upload_image(dummy_img)
    assert urn == "urn:li:image:img999"


def test_comment(monkeypatch):
    mock_resp_me = MagicMock()
    mock_resp_me.json.return_value = {"sub": "user123"}
    monkeypatch.setattr(linkedin.requests, "get", MagicMock(return_value=mock_resp_me))

    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_post_fn = MagicMock(return_value=mock_resp)
    monkeypatch.setattr(linkedin.requests, "post", mock_post_fn)

    client = linkedin.LinkedInClient("test_token", "202610")
    client.comment("urn:li:share:123", "Nice post!")
    assert mock_post_fn.called

    # Test error status
    mock_resp_err = MagicMock()
    mock_resp_err.status_code = 400
    mock_resp_err.text = "Bad Request"
    monkeypatch.setattr(linkedin.requests, "post", MagicMock(return_value=mock_resp_err))
    with pytest.raises(RuntimeError, match="Comment failed 400"):
        client.comment("urn:li:share:123", "Fail comment")


def test_post_text(monkeypatch):
    mock_resp_me = MagicMock()
    mock_resp_me.json.return_value = {"sub": "user123"}
    monkeypatch.setattr(linkedin.requests, "get", MagicMock(return_value=mock_resp_me))

    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.headers = {"x-restli-id": "urn:li:share:text123"}
    monkeypatch.setattr(linkedin.requests, "post", MagicMock(return_value=mock_resp))

    client = linkedin.LinkedInClient("test_token", "202610")
    post_urn = client.post_text("Hello LinkedIn world! #Dev")
    assert post_urn == "urn:li:share:text123"

    # Test post text failure
    mock_resp_fail = MagicMock()
    mock_resp_fail.status_code = 403
    mock_resp_fail.text = "Forbidden"
    monkeypatch.setattr(linkedin.requests, "post", MagicMock(return_value=mock_resp_fail))
    with pytest.raises(RuntimeError, match="LinkedIn post failed 403"):
        client.post_text("Will fail")


def test_post_with_image(tmp_path: Path, monkeypatch):
    mock_resp_me = MagicMock()
    mock_resp_me.json.return_value = {"sub": "user123"}
    monkeypatch.setattr(linkedin.requests, "get", MagicMock(return_value=mock_resp_me))

    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.headers = {"x-restli-id": "urn:li:share:imgpost123"}
    monkeypatch.setattr(linkedin.requests, "post", MagicMock(return_value=mock_resp))

    client = linkedin.LinkedInClient("test_token", "202610")
    monkeypatch.setattr(client, "upload_image", MagicMock(return_value="urn:li:image:test"))

    dummy_img = tmp_path / "pic.png"
    dummy_img.write_bytes(b"data")
    res = client.post_with_image("Post with graphic #Coding", dummy_img, alt_text="Alt description")
    assert res == "urn:li:share:imgpost123"

    # Test failure
    mock_resp_err = MagicMock()
    mock_resp_err.status_code = 500
    mock_resp_err.text = "Server Error"
    monkeypatch.setattr(linkedin.requests, "post", MagicMock(return_value=mock_resp_err))
    with pytest.raises(RuntimeError, match="LinkedIn post failed 500"):
        client.post_with_image("Post fail", dummy_img)
