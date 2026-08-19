"""API tests for LLM Provider sync endpoints."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.models.project import Project


class TestLLMProvidersAPI:
    def test_sync_and_list(self, client: TestClient, test_project: Project) -> None:
        payload = {
            "providers": [
                {
                    "id": str(uuid.uuid4()),
                    "project_id": str(test_project.id),
                    "alias": "openai-prod",
                    "provider_kind": "openai",
                    "vendor": "openai",
                    "api_base_url": None,
                    "api_key": "sk_test_1234567890",
                    "organization": None,
                    "timeout": 30,
                    "is_active": True,
                },
                {
                    "id": str(uuid.uuid4()),
                    "project_id": str(test_project.id),
                    "alias": "deepseek",
                    "provider_kind": "openai_compatible",
                    "vendor": "deepseek",
                    "api_base_url": "https://api.deepseek.com/v1",
                    "api_key": "ds_test_abcdefg",
                    "organization": None,
                    "timeout": None,
                    "is_active": True,
                },
            ]
        }

        # Sync providers
        res = client.post("/api/v1/llm-providers/sync", json=payload)
        assert res.status_code == 200, res.text
        body = res.json()
        assert "data" in body
        listed = body["data"]
        assert {p["alias"] for p in listed} == {"openai-prod", "deepseek"}
        # API keys should be masked in response
        for p in listed:
            if p["alias"] == "openai-prod":
                assert p["api_key_masked"].endswith("7890")
            if p["alias"] == "deepseek":
                assert p["api_key_masked"].endswith("defg")

    def test_upsert_single(self, client: TestClient, test_project: Project) -> None:
        # Create via sync
        anthropic_id = uuid.uuid4()
        payload_create = {
            "providers": [
                {
                    "id": str(anthropic_id),
                    "project_id": str(test_project.id),
                    "alias": "anthropic",
                    "provider_kind": "anthropic",
                    "vendor": "anthropic",
                    "api_key": "ak_claude_123",
                    "is_active": True,
                }
            ]
        }
        res = client.post("/api/v1/llm-providers/sync", json=payload_create)
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        assert any(p["alias"] == "anthropic" for p in data)
        first = next(p for p in data if p["alias"] == "anthropic")
        assert first["api_key_masked"].endswith("_123")

        # Update via sync (re-use same id)
        payload_update = {
            "providers": [
                {
                    "id": str(anthropic_id),
                    "project_id": str(test_project.id),
                    "alias": "anthropic",
                    "provider_kind": "anthropic",
                    "vendor": "anthropic",
                    "api_key": "ak_claude_456",
                    "is_active": True,
                }
            ]
        }
        res = client.post("/api/v1/llm-providers/sync", json=payload_update)
        assert res.status_code == 200
        data2 = res.json()["data"]
        updated = next(p for p in data2 if p["alias"] == "anthropic")
        assert updated["api_key_masked"].endswith("_456")

