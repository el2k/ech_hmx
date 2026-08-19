"""仅Agent运行时灰度发布共用规则辅助工具。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Protocol, TypeVar, cast
from uuid import UUID


JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject = dict[str, JsonValue]

# 最小UTC时间基准值
_MIN_DATETIME = datetime.min.replace(tzinfo=timezone.utc)


class AgentLike(Protocol):
    """灰度发布‑默认Agent选择所需的最小字段协议。"""

    id: UUID
    created_at: datetime | None
    updated_at: datetime | None


class ProjectAgentLike(AgentLike, Protocol):
    """项目级默认Agent灰度发布所需Agent字段协议。"""

    is_default: bool
    team_id: UUID | None
    deleted_at: datetime | None


class TeamLike(Protocol):
    """项目级默认Agent灰度发布所需团队字段协议。"""

    id: UUID
    is_default: bool
    deleted_at: datetime | None


AgentLikeT = TypeVar("AgentLikeT", bound=AgentLike)


def merge_agent_config(
    agent_config: Mapping[str, JsonValue] | None,
    team_config: Mapping[str, JsonValue] | None,
) -> JsonObject:
    """深度合并运行时配置，Agent配置优先级高于团队配置。"""

    merged: JsonObject = {}
    team_mapping = team_config or {}
    agent_mapping = agent_config or {}

    # 先复制团队配置全部字段
    for key in team_mapping:
        merged[key] = _clone_json_value(team_mapping[key])

    # 再用Agent配置覆盖，嵌套对象递归深度合并
    for key, agent_value in agent_mapping.items():
        team_value = team_mapping.get(key)
        # 两边均为对象，则递归合并
        if isinstance(agent_value, Mapping) and isinstance(team_value, Mapping):
            merged[key] = merge_agent_config(
                _ensure_json_mapping(agent_value),
                _ensure_json_mapping(team_value),
            )
            continue
        # 非对象直接用Agent值覆盖
        merged[key] = _clone_json_value(agent_value)

    return merged


def choose_rollout_default_agent(candidates: Sequence[AgentLikeT]) -> AgentLikeT | None:
    """灰度发布场景下确定性选出唯一默认Agent。

    排序优先级：更新时间 > 创建时间 > Agent ID字符串，保证多实例下选择结果一致。
    """

    if not candidates:
        return None

    return max(
        candidates,
        key=lambda agent: (
            _normalize_datetime(agent.updated_at),
            _normalize_datetime(agent.created_at),
            str(agent.id),
        ),
    )


def choose_default_agent_for_project(
    agents: Sequence[ProjectAgentLike],
    teams: Sequence[TeamLike],
) -> ProjectAgentLike | None:
    """迁移后为项目选出默认Agent，无合适候选返回None。

    选择优先级：
    1. 标记为is_default的有效Agent
    2. 默认团队下的有效Agent
    3. 项目仅有1个有效Agent时直接选用该Agent
    4. 其余情况返回None
    """

    active_agents = [agent for agent in agents if agent.deleted_at is None]
    if not active_agents:
        return None

    # 优先取显式标记为默认的Agent
    explicit_defaults = [agent for agent in active_agents if agent.is_default]
    chosen_explicit_default = choose_rollout_default_agent(explicit_defaults)
    if chosen_explicit_default is not None:
        return chosen_explicit_default

    # 取默认团队ID集合
    default_team_ids = {
        team.id
        for team in teams
        if team.is_default and team.deleted_at is None
    }
    if default_team_ids:
        default_team_agents = [
            agent for agent in active_agents if agent.team_id in default_team_ids
        ]
        chosen_default_team_agent = choose_rollout_default_agent(default_team_agents)
        if chosen_default_team_agent is not None:
            return chosen_default_team_agent

    # 项目仅存一个有效Agent
    if len(active_agents) == 1:
        return active_agents[0]

    return None


def _normalize_datetime(value: datetime | None) -> datetime:
    """时间标准化：空值返回最小UTC时间；无时区信息补UTC时区。"""
    if value is None:
        return _MIN_DATETIME
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _ensure_json_mapping(value: Mapping[str, JsonValue]) -> JsonObject:
    """将任意Mapping转为JsonObject，同时做深度克隆。"""
    return cast(JsonObject, {key: _clone_json_value(item) for key, item in value.items()})


def _clone_json_value(value: JsonValue) -> JsonValue:
    """对JSON值做递归深拷贝，避免修改原始对象。"""
    if isinstance(value, Mapping):
        return {key: _clone_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clone_json_value(item) for item in value]
    return value