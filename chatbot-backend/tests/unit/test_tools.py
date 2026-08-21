from unittest.mock import AsyncMock, patch
import pytest
from app.rag.tools import ToolExecutor

@pytest.mark.asyncio
async def test_get_pending_assignments_success():
    mock_client = AsyncMock()
    mock_client.get_course_assignments.return_value = {
        "courses": [
            {
                "fullname": "Curso 1",
                "assignments": [
                    {"name": "Tarea 1", "duedate": 1000}
                ]
            }
        ]
    }
    with patch("app.rag.tools.get_moodle_client", return_value=mock_client):
        result = await ToolExecutor.get_pending_assignments(1)
        assert "Curso 1: Tarea 1" in result
        assert "1000" in result

@pytest.mark.asyncio
async def test_get_pending_assignments_empty():
    mock_client = AsyncMock()
    mock_client.get_course_assignments.return_value = {"courses": []}
    with patch("app.rag.tools.get_moodle_client", return_value=mock_client):
        result = await ToolExecutor.get_pending_assignments(1)
        assert "No tienes tareas pendientes" in result

@pytest.mark.asyncio
async def test_get_my_grades_success():
    mock_client = AsyncMock()
    mock_client.get_user_grades.return_value = {
        "usergrades": [
            {
                "gradeitems": [
                    {"itemname": "Parcial", "gradeformatted": "8.50"}
                ]
            }
        ]
    }
    with patch("app.rag.tools.get_moodle_client", return_value=mock_client):
        result = await ToolExecutor.get_my_grades(1, 1)
        assert "Parcial: 8.50" in result
