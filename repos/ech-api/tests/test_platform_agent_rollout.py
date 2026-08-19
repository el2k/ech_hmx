"""Tests for platform agent rollout helpers."""

from uuid import uuid4

from app.services.platform_agent_rollout import choose_platform_agent_id


def test_choose_platform_agent_id_returns_none_for_empty_values() -> None:
    """Empty or missing rollout data should not select an agent."""

    assert choose_platform_agent_id(None) is None
    assert choose_platform_agent_id([]) is None


def test_choose_platform_agent_id_keeps_single_value() -> None:
    """A single configured platform agent remains unchanged."""

    agent_id = uuid4()

    assert choose_platform_agent_id([agent_id]) == agent_id


def test_choose_platform_agent_id_uses_first_stored_value() -> None:
    """Legacy multi-agent arrays roll forward deterministically."""

    first = uuid4()
    second = uuid4()

    assert choose_platform_agent_id([first, second]) == first
