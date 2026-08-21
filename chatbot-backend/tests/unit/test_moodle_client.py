from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from app.services.moodle_client import MoodleClient
from app.core.config import get_settings

@pytest.fixture
def moodle_client():
    return MoodleClient("http://moodle-test", "read-token", "write-token")

@pytest.mark.asyncio
async def test_get_user_courses_no_token():
    client = MoodleClient("http://moodle", "")
    res = await client.get_user_courses(1)
    assert res == []

@pytest.mark.asyncio
async def test_create_calendar_event_disabled_by_default(moodle_client, monkeypatch):
    # Por defecto calendar_write_enabled es False
    settings = get_settings()
    monkeypatch.setattr(settings, "calendar_write_enabled", False)
    
    res = await moodle_client.create_calendar_event(1, 1, "Examen", "Desc", 123456)
    assert "error" in res
    assert res["error"] == "Write operations are disabled."

@pytest.mark.asyncio
async def test_create_calendar_event_missing_write_token(moodle_client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "calendar_write_enabled", True)
    
    # Cliente sin token de escritura
    client_no_write = MoodleClient("http://moodle-test", "read-token", "")
    res = await client_no_write.create_calendar_event(1, 1, "Examen", "Desc", 123456)
    assert "error" in res
    assert res["error"] == "Missing write token."

@pytest.mark.asyncio
async def test_get_user_courses_success(moodle_client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [{"id": 1, "fullname": "Matemática"}]

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await moodle_client.get_user_courses(1)
        assert len(res) == 1
        assert res[0]["fullname"] == "Matemática"

@pytest.mark.asyncio
async def test_download_file(moodle_client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"fake-pdf-content"

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await moodle_client.download_file("http://moodle-test/file.pdf")
        assert res == b"fake-pdf-content"
