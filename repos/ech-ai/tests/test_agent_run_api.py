import uuid
from unittest.mock import AsyncMock, Mock

from app.dependencies import get_supervisor_runtime_service
from app.main import app


def test_run_rejects_team_fields(client, test_project) -> None:
    response = client.post(
        f"/api/v1/agents/run?project_id={test_project.id}",
        json={
            "message": "hello",
            "team_id": "123e4567-e89b-12d3-a456-426614174000",
        },
    )

    assert response.status_code == 422


def test_run_non_stream_success_uses_result_field(client, test_project) -> None:
    agent_id = uuid.uuid4()
    fake_runtime_service = Mock()
    fake_runtime_service.run = AsyncMock(
        return_value={
            "success": True,
            "message": "Agent run completed",
            "result": {
                "agent_id": str(agent_id),
                "agent_name": "Support Agent",
                "question": "hi",
                "content": "ok",
                "tools_used": None,
                "execution_time": 0.1,
                "success": True,
                "error": None,
            },
            "content": "ok",
            "metadata": {
                "agent_id": str(agent_id),
                "agent_name": "Support Agent",
                "total_execution_time": 0.1,
                "session_id": None,
            },
            "error": None,
        }
    )
    app.dependency_overrides[get_supervisor_runtime_service] = lambda: fake_runtime_service

    try:
        response = client.post(
            f"/api/v1/agents/run?project_id={test_project.id}",
            json={"message": "hi", "stream": False},
        )
    finally:
        del app.dependency_overrides[get_supervisor_runtime_service]

    assert response.status_code == 200
    body = response.json()
    assert body["result"]["agent_id"] == str(agent_id)
    assert "results" not in body


def test_run_failure_response_uses_null_result(client, test_project) -> None:
    fake_runtime_service = Mock()
    fake_runtime_service.run = AsyncMock(
        return_value={
            "success": False,
            "message": "Default agent not configured for project",
            "result": None,
            "content": "",
            "metadata": None,
            "error": "Default agent not configured for project",
        }
    )
    app.dependency_overrides[get_supervisor_runtime_service] = lambda: fake_runtime_service

    try:
        response = client.post(
            f"/api/v1/agents/run?project_id={test_project.id}",
            json={"message": "hi", "stream": False},
        )
    finally:
        del app.dependency_overrides[get_supervisor_runtime_service]

    assert response.status_code == 200
    body = response.json()
    assert body["result"] is None
    assert body["metadata"] is None
    assert body["content"] == ""
