def test_create_agent_rejects_team_id_field(client, test_project) -> None:
    response = client.post(
        f"/api/v1/agents?project_id={test_project.id}",
        json={
            "name": "Agent A",
            "model": "openai:gpt-4o",
            "team_id": "123e4567-e89b-12d3-a456-426614174000",
        },
    )

    assert response.status_code == 422


def test_agent_list_openapi_has_no_team_id_parameter(client) -> None:
    schema = client.get("/openapi.json").json()
    parameters = schema["paths"]["/api/v1/agents"]["get"].get("parameters", [])

    assert all(parameter["name"] != "team_id" for parameter in parameters)
