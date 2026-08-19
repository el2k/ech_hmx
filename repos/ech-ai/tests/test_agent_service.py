import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.agent import AgentCreate
from app.services.agent_service import AgentService


@pytest.mark.asyncio
async def test_create_agent_replaces_existing_default(
    db_session: AsyncSession,
    test_project,
) -> None:
    service = AgentService(db_session)

    first = await service.create_agent(
        test_project.id,
        AgentCreate(name="First", model="openai:gpt-4o", is_default=True),
    )
    second = await service.create_agent(
        test_project.id,
        AgentCreate(name="Second", model="openai:gpt-4o", is_default=True),
    )

    refreshed_first = await service.get_agent(test_project.id, first.id)
    refreshed_second = await service.get_agent(test_project.id, second.id)

    assert refreshed_first.is_default is False
    assert refreshed_second.is_default is True


@pytest.mark.asyncio
async def test_get_default_agent_returns_project_default(
    db_session: AsyncSession,
    test_project,
) -> None:
    service = AgentService(db_session)
    created = await service.create_agent(
        test_project.id,
        AgentCreate(name="Default", model="openai:gpt-4o", is_default=True),
    )

    default_agent = await service.get_default_agent(test_project.id)

    assert default_agent.id == created.id
