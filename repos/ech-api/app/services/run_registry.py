# =============================================================================
# 模块：运行注册表 (Run Registry)
# =============================================================================
# 该模块提供了 client_msg_no 到 AI 运行元数据的映射注册表，主要用于：
# 1. 支持通过 client_msg_no 取消正在运行的 AI Supervisor
# 2. 记录运行 ID 与客户端消息编号的映射关系
# 3. 支持取消请求的延迟处理（当 run_id 尚未可用时标记待处理）
# 
# 设计目的：
# - 实现 AI 流式响应的取消功能
# - 支持多进程部署（通过 Redis 共享状态）
# - 处理 run_id 延迟获取的场景
# 
# 工作流程：
# 1. AI 处理器在收到 agent_execution_started 事件时记录映射（run_id 可用）
# 2. HTTP 端点可以通过 client_msg_no 请求取消
# 3. 如果 run_id 尚未可知，标记为 pending
# 4. 当 run_id 到达且检测到 pending 状态时，AI 处理器立即执行取消
# 
# 存储策略：
# - 如果配置了 REDIS_URL，使用 Redis 作为共享存储（多进程部署必需）
# - 否则回退到内存存储（仅单进程）
# =============================================================================

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, Tuple

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("run_registry")

# =============================================================================
# 常量定义
# =============================================================================

DEFAULT_TTL_SECONDS = 15 * 60  # 15 分钟，条目的默认存活时间
REDIS_KEY_PREFIX = "tgo:run_registry:"  # Redis 键前缀


# =============================================================================
# 运行条目数据类
# =============================================================================

@dataclass
class RunEntry:
    """
    运行条目，记录一次 AI 运行的相关信息。

    Attributes:
        client_msg_no: 客户端消息编号（唯一标识）
        project_id: 项目 ID
        api_key: API Key（用于权限验证）
        session_id: 会话 ID
        run_id: AI 运行 ID（在 agent_execution_started 事件中获取）
        pending_cancel: 是否有待处理的取消请求
        cancel_reason: 取消原因
        ts: 最后更新时间戳
    """
    client_msg_no: str
    project_id: Optional[str]
    api_key: Optional[str]
    session_id: Optional[str]
    run_id: Optional[str] = None
    pending_cancel: bool = False
    cancel_reason: Optional[str] = None
    ts: float = 0.0  # 最后更新时间戳

    def to_dict(self) -> Dict[str, Any]:
        """将数据类转换为字典。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RunEntry":
        """从字典创建数据类实例。"""
        return cls(
            client_msg_no=data.get("client_msg_no", ""),
            project_id=data.get("project_id"),
            api_key=data.get("api_key"),
            session_id=data.get("session_id"),
            run_id=data.get("run_id"),
            pending_cancel=data.get("pending_cancel", False),
            cancel_reason=data.get("cancel_reason"),
            ts=data.get("ts", 0.0),
        )


# =============================================================================
# 内存注册表实现（单进程）
# =============================================================================

class InMemoryRunRegistry:
    """
    内存注册表实现（仅适用于单进程部署）。

    特点：
    - 使用内存字典存储
    - 支持自动清理过期条目
    - 使用 asyncio.Lock 保证线程安全
    - 不适用于多进程部署
    """

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._by_client: Dict[str, RunEntry] = {}  # client_msg_no -> RunEntry
        self._lock = asyncio.Lock()

    async def _prune_locked(self) -> None:
        """
        清理过期的条目（需在持有锁的情况下调用）。

        检查所有条目的时间戳，删除超过 TTL 的条目。
        """
        now = time.time()
        expired = [k for k, v in self._by_client.items() if now - (v.ts or 0.0) > self._ttl]
        for k in expired:
            self._by_client.pop(k, None)

    async def get(self, client_msg_no: str) -> Optional[RunEntry]:
        """
        根据 client_msg_no 获取运行条目。

        Args:
            client_msg_no: 客户端消息编号

        Returns:
            Optional[RunEntry]: 找到的条目，不存在时返回 None
        """
        async with self._lock:
            await self._prune_locked()
            return self._by_client.get(client_msg_no)

    async def clear(self, client_msg_no: str) -> None:
        """
        清除指定 client_msg_no 的条目。

        Args:
            client_msg_no: 客户端消息编号
        """
        async with self._lock:
            self._by_client.pop(client_msg_no, None)

    async def mark_cancel_pending(
        self,
        client_msg_no: str,
        *,
        reason: Optional[str],
        project_id: Optional[str],
        api_key: Optional[str],
    ) -> None:
        """
        标记取消请求为待处理状态。

        当客户端请求取消但 run_id 尚未可知时调用此方法。

        Args:
            client_msg_no: 客户端消息编号
            reason: 取消原因
            project_id: 项目 ID
            api_key: API Key
        """
        async with self._lock:
            await self._prune_locked()
            entry = self._by_client.get(client_msg_no)
            now = time.time()

            if entry is None:
                # 创建新条目，标记为 pending_cancel
                entry = RunEntry(
                    client_msg_no=client_msg_no,
                    project_id=project_id,
                    api_key=api_key,
                    session_id=None,
                    run_id=None,
                    pending_cancel=True,
                    cancel_reason=reason,
                    ts=now,
                )
                self._by_client[client_msg_no] = entry
            else:
                # 更新已存在条目
                entry.pending_cancel = True
                entry.cancel_reason = reason
                if project_id:
                    entry.project_id = entry.project_id or project_id
                if api_key:
                    entry.api_key = entry.api_key or api_key
                entry.ts = now

    async def set_mapping_and_check_pending(
        self,
        *,
        client_msg_no: str,
        run_id: str,
        project_id: Optional[str],
        api_key: Optional[str],
        session_id: Optional[str],
    ) -> Tuple[bool, Optional[str]]:
        """
        设置 run_id 映射并检查是否有待处理的取消请求。

        当 AI 处理器收到 agent_execution_started 事件时调用此方法。

        Args:
            client_msg_no: 客户端消息编号
            run_id: AI 运行 ID
            project_id: 项目 ID
            api_key: API Key
            session_id: 会话 ID

        Returns:
            Tuple[bool, Optional[str]]:
                - bool: 是否有待处理的取消请求
                - Optional[str]: 取消原因（如果有）
        """
        async with self._lock:
            await self._prune_locked()
            now = time.time()
            entry = self._by_client.get(client_msg_no)

            if entry is None:
                # 创建新条目，无待处理取消
                entry = RunEntry(
                    client_msg_no=client_msg_no,
                    project_id=project_id,
                    api_key=api_key,
                    session_id=session_id,
                    run_id=run_id,
                    pending_cancel=False,
                    cancel_reason=None,
                    ts=now,
                )
                self._by_client[client_msg_no] = entry
                return (False, None)

            # 更新已存在条目
            entry.run_id = run_id
            entry.session_id = session_id or entry.session_id
            entry.project_id = entry.project_id or project_id
            entry.api_key = entry.api_key or api_key
            entry.ts = now

            # 检查是否有待处理的取消请求
            if entry.pending_cancel:
                reason = entry.cancel_reason
                entry.pending_cancel = False  # 清除待处理状态
                return (True, reason)

            return (False, None)


# =============================================================================
# Redis 注册表实现（多进程）
# =============================================================================

class RedisRunRegistry:
    """
    Redis 支持的注册表实现（适用于多进程部署）。

    特点：
    - 使用 Redis 作为共享存储
    - 支持多进程/多实例部署
    - 自动 TTL 过期
    - 使用 asyncio.Lock 保证并发安全
    """

    def __init__(self, redis_url: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._redis_url = redis_url
        self._redis: Any = None
        self._lock = asyncio.Lock()

    async def _get_redis(self) -> Any:
        """
        获取 Redis 连接（懒加载）。

        Returns:
            Any: Redis 客户端实例

        Raises:
            Exception: Redis 连接失败时抛出
        """
        if self._redis is None:
            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(
                    self._redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                )
                logger.info("Redis connection established for run_registry")
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                raise
        return self._redis

    def _key(self, client_msg_no: str) -> str:
        """生成 Redis 键名。"""
        return f"{REDIS_KEY_PREFIX}{client_msg_no}"

    async def get(self, client_msg_no: str) -> Optional[RunEntry]:
        """
        根据 client_msg_no 获取运行条目。

        Args:
            client_msg_no: 客户端消息编号

        Returns:
            Optional[RunEntry]: 找到的条目，不存在时返回 None
        """
        try:
            redis = await self._get_redis()
            data = await redis.get(self._key(client_msg_no))
            if data:
                return RunEntry.from_dict(json.loads(data))
            return None
        except Exception as e:
            logger.warning(f"Redis get failed: {e}")
            return None

    async def clear(self, client_msg_no: str) -> None:
        """
        清除指定 client_msg_no 的条目。

        Args:
            client_msg_no: 客户端消息编号
        """
        try:
            redis = await self._get_redis()
            await redis.delete(self._key(client_msg_no))
        except Exception as e:
            logger.warning(f"Redis delete failed: {e}")

    async def _save_entry(self, entry: RunEntry) -> None:
        """
        保存条目到 Redis（带 TTL）。

        Args:
            entry: 要保存的运行条目
        """
        redis = await self._get_redis()
        await redis.setex(
            self._key(entry.client_msg_no),
            self._ttl,
            json.dumps(entry.to_dict()),
        )

    async def mark_cancel_pending(
        self,
        client_msg_no: str,
        *,
        reason: Optional[str],
        project_id: Optional[str],
        api_key: Optional[str],
    ) -> None:
        """
        标记取消请求为待处理状态。

        当客户端请求取消但 run_id 尚未可知时调用此方法。

        Args:
            client_msg_no: 客户端消息编号
            reason: 取消原因
            project_id: 项目 ID
            api_key: API Key
        """
        try:
            async with self._lock:
                entry = await self.get(client_msg_no)
                now = time.time()

                if entry is None:
                    # 创建新条目，标记为 pending_cancel
                    entry = RunEntry(
                        client_msg_no=client_msg_no,
                        project_id=project_id,
                        api_key=api_key,
                        session_id=None,
                        run_id=None,
                        pending_cancel=True,
                        cancel_reason=reason,
                        ts=now,
                    )
                else:
                    # 更新已存在条目
                    entry.pending_cancel = True
                    entry.cancel_reason = reason
                    if project_id:
                        entry.project_id = entry.project_id or project_id
                    if api_key:
                        entry.api_key = entry.api_key or api_key
                    entry.ts = now

                await self._save_entry(entry)
                logger.debug(
                    "Marked cancel pending in Redis",
                    extra={"client_msg_no": client_msg_no, "reason": reason},
                )
        except Exception as e:
            logger.error(f"Redis mark_cancel_pending failed: {e}")
            raise

    async def set_mapping_and_check_pending(
        self,
        *,
        client_msg_no: str,
        run_id: str,
        project_id: Optional[str],
        api_key: Optional[str],
        session_id: Optional[str],
    ) -> Tuple[bool, Optional[str]]:
        """
        设置 run_id 映射并检查是否有待处理的取消请求。

        当 AI 处理器收到 agent_execution_started 事件时调用此方法。

        Args:
            client_msg_no: 客户端消息编号
            run_id: AI 运行 ID
            project_id: 项目 ID
            api_key: API Key
            session_id: 会话 ID

        Returns:
            Tuple[bool, Optional[str]]:
                - bool: 是否有待处理的取消请求
                - Optional[str]: 取消原因（如果有）
        """
        try:
            async with self._lock:
                entry = await self.get(client_msg_no)
                now = time.time()

                if entry is None:
                    # 创建新条目，无待处理取消
                    entry = RunEntry(
                        client_msg_no=client_msg_no,
                        project_id=project_id,
                        api_key=api_key,
                        session_id=session_id,
                        run_id=run_id,
                        pending_cancel=False,
                        cancel_reason=None,
                        ts=now,
                    )
                    await self._save_entry(entry)
                    return (False, None)

                # 更新已存在条目
                entry.run_id = run_id
                entry.session_id = session_id or entry.session_id
                entry.project_id = entry.project_id or project_id
                entry.api_key = entry.api_key or api_key
                entry.ts = now

                # 检查是否有待处理的取消请求
                if entry.pending_cancel:
                    reason = entry.cancel_reason
                    entry.pending_cancel = False
                    await self._save_entry(entry)
                    logger.info(
                        "Found pending cancel in Redis, will execute",
                        extra={"client_msg_no": client_msg_no, "run_id": run_id},
                    )
                    return (True, reason)

                await self._save_entry(entry)
                return (False, None)
        except Exception as e:
            logger.error(f"Redis set_mapping_and_check_pending failed: {e}")
            return (False, None)


# =============================================================================
# 注册表工厂函数
# =============================================================================

def _create_registry() -> InMemoryRunRegistry | RedisRunRegistry:
    """
    根据配置创建合适的注册表实例。

    如果配置了 REDIS_URL，使用 Redis 注册表（多进程支持）；
    否则使用内存注册表（仅单进程）。

    Returns:
        InMemoryRunRegistry | RedisRunRegistry: 注册表实例
    """
    redis_url = settings.REDIS_URL
    if redis_url:
        logger.info("Using Redis-backed run_registry", extra={"redis_url": redis_url[:20] + "..."})
        return RedisRunRegistry(redis_url)
    else:
        logger.warning(
            "REDIS_URL not configured, using in-memory run_registry. "
            "Cancel requests will NOT work across processes!"
        )
        return InMemoryRunRegistry()


# =============================================================================
# 全局单例实例
# =============================================================================

# 全局实例 - 如果配置了 Redis 则使用 Redis，否则使用内存存储
run_registry = _create_registry()
# 运行注册表是 AI 聊天体验的关键组件，它解决了一个看似简单但实际上很复杂的问题：让用户能够随时取消正在生成的 AI 响应。
# 如果没有它，用户可能会被迫等待不必要的长时间响应，或者取消请求因时序问题而失效。