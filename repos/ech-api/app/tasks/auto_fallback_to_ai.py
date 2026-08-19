# =============================================================================
# 模块：AI 自动兜底定时任务 (Scheduled task for automatic AI fallback)
# =============================================================================
# 该模块提供了在辅助模式（assist mode）下，当客服响应超时时，
# 自动触发 AI 回复的兜底功能，主要包括：
# 1. 定期检查处于辅助模式的平台
# 2. 识别等待客服回复超时的访客
# 3. 自动调用 AI 生成回复
# 4. 管理重试次数防止无限循环
# 
# 设计目的：
# - 提升用户体验：当客服响应慢时，AI 及时介入避免访客等待
# - 减轻客服压力：在客服忙碌时由 AI 先处理部分问题
# - 平滑过渡：在辅助模式下，AI 和人工协作服务
# =============================================================================

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.core.database import SessionLocal
from app.models import Platform, Visitor, VisitorServiceStatus, VisitorSession, SessionStatus
from app.services.chat_service import handle_ai_response_non_stream
from app.services.wukongim_client import wukongim_client
from app.utils.encoding import build_visitor_channel_id, get_session_id
from app.utils.const import CHANNEL_TYPE_CUSTOMER_SERVICE

logger = logging.getLogger(__name__)

# =============================================================================
# 全局状态变量
# =============================================================================
_auto_fallback_task: Optional[asyncio.Task] = None  # 后台任务的句柄

# =============================================================================
# 常量定义
# =============================================================================
MAX_AI_FALLBACK_RETRIES = 3  # AI 兜底最大重试次数，超过后不再重试


# =============================================================================
# 任务生命周期管理
# =============================================================================

async def start_auto_fallback_to_ai_task(interval_seconds: int = 60):
    """
    启动自动 AI 兜底检查的周期性任务。

    在应用启动时调用此函数来启动定时任务。
    如果任务已在运行，则不重复启动。

    Args:
        interval_seconds: 检查间隔时间（秒），默认 60 秒
    """
    global _auto_fallback_task

    # 防止重复启动
    if _auto_fallback_task is not None:
        return

    # 定义内部循环函数
    async def _loop():
        while True:
            try:
                # 执行一次兜底检查
                await check_and_fallback_to_ai()
            except Exception as e:
                logger.error(f"Error in auto_fallback_to_ai loop: {e}")
            # 等待下一个检查周期
            await asyncio.sleep(interval_seconds)

    # 创建并启动异步任务
    _auto_fallback_task = asyncio.create_task(_loop())
    logger.info("Started auto fallback to AI periodic task")


async def stop_auto_fallback_to_ai_task():
    """
    停止自动 AI 兜底检查的周期性任务。

    在应用关闭时调用此函数来优雅地停止定时任务。
    """
    global _auto_fallback_task

    if _auto_fallback_task:
        # 取消任务
        _auto_fallback_task.cancel()
        try:
            # 等待任务被取消（会抛出 CancelledError）
            await _auto_fallback_task
        except asyncio.CancelledError:
            pass  # 任务被正常取消
        _auto_fallback_task = None
        logger.info("Stopped auto fallback to AI periodic task")


# =============================================================================
# 核心处理函数
# =============================================================================

async def check_and_fallback_to_ai():
    """
    检查并触发 AI 兜底的定时任务。

    执行流程：
    1. 查询所有处于辅助模式（assist）且配置了超时时间的平台
    2. 对每个平台，查找符合条件的访客：
       - 属于该平台
       - 服务状态为 ACTIVE（服务中）
       - 最后一条消息来自访客
       - 最后消息时间超过超时阈值
       - 有有效的消息编号（last_client_msg_no）
       - 重试次数未超过上限
       - AI 未被禁用
    3. 对每个符合条件的访客，从 WuKongIM 获取最后一条消息内容
    4. 调用 AI 生成回复
    5. 更新访客状态（重置重试计数或增加重试计数）

    设计考量：
    - 只在 assist（辅助）模式下生效，AI 模式和人工模式不触发
    - 使用重试机制防止单次失败导致永久放弃
    - 从 WuKongIM 获取原始消息，确保内容准确
    - 使用访客最后消息的 client_msg_no 精确定位消息

    Conditions for triggering AI fallback:
    - Visitor is in ACTIVE service status
    - Visitor's last message was from visitor (not AI/staff)
    - Visitor's last message timestamp exceeds platform's timeout
    - Visitor has a valid last_client_msg_no for message retrieval
    - Visitor's ai_fallback_retry_count < MAX_AI_FALLBACK_RETRIES
    - Visitor's ai_disabled is not explicitly True
    """
    db: Session = SessionLocal()
    try:
        # =====================================================================
        # 步骤1: 获取辅助模式且配置了超时时间的平台
        # =====================================================================
        # 只处理 ai_mode = "assist" 且 fallback_to_ai_timeout > 0 的平台
        platforms = db.query(Platform).filter(
            Platform.ai_mode == "assist",
            Platform.fallback_to_ai_timeout > 0,
            Platform.is_active.is_(True),
            Platform.deleted_at.is_(None)
        ).all()

        if not platforms:
            return

        # =====================================================================
        # 步骤2: 对每个平台查找需要兜底的访客
        # =====================================================================
        for platform in platforms:
            timeout_seconds = platform.fallback_to_ai_timeout
            cutoff_time = datetime.utcnow() - timedelta(seconds=timeout_seconds)

            # 查询符合条件的访客
            # 条件说明：
            # - service_status == ACTIVE: 正在服务中（已分配给客服）
            # - is_last_message_from_visitor: 最后一条消息是访客发的（等待客服回复）
            # - last_message_at < cutoff_time: 等待时间超过超时阈值
            # - last_client_msg_no IS NOT NULL: 有消息编号可以查询
            # - ai_fallback_retry_count < MAX: 重试次数未超限
            # - ai_disabled IS NOT True: AI 未被禁用
            visitors = db.query(Visitor).filter(
                Visitor.platform_id == platform.id,
                Visitor.service_status == VisitorServiceStatus.ACTIVE.value,
                Visitor.is_last_message_from_visitor.is_(True),
                Visitor.last_message_at < cutoff_time,
                Visitor.last_client_msg_no.isnot(None),
                Visitor.ai_fallback_retry_count < MAX_AI_FALLBACK_RETRIES,
                Visitor.deleted_at.is_(None),
                or_(Visitor.ai_disabled.is_(None), Visitor.ai_disabled.is_(False))
            ).all()

            for visitor in visitors:
                logger.info(f"Triggering AI fallback for visitor {visitor.id} on platform {platform.name}")

                # =============================================================
                # 步骤3: 从 WuKongIM 获取访客的最后一条消息
                # =============================================================
                channel_id = build_visitor_channel_id(visitor.id)
                channel_type = CHANNEL_TYPE_CUSTOMER_SERVICE

                try:
                    # 通过 client_msg_no 精确查询消息
                    last_msg = await wukongim_client.get_message_by_client_msg_no(
                        channel_id=channel_id,
                        channel_type=channel_type,
                        client_msg_no=visitor.last_client_msg_no
                    )

                    if not last_msg:
                        logger.warning(
                            f"No message found for visitor {visitor.id} "
                            f"with client_msg_no {visitor.last_client_msg_no}"
                        )
                        # 消息未找到，这是永久性错误，停止重试
                        visitor.ai_fallback_retry_count = MAX_AI_FALLBACK_RETRIES
                        db.add(visitor)
                        db.commit()
                        continue

                    # 提取消息内容
                    message_content = ""
                    if last_msg.payload:
                        message_content = last_msg.payload.get("content", "")

                    if not message_content:
                        logger.warning(
                            f"Last message for visitor {visitor.id} has no content "
                            f"or not a text message"
                        )
                        # 消息内容为空，停止重试
                        visitor.ai_fallback_retry_count = MAX_AI_FALLBACK_RETRIES
                        db.add(visitor)
                        db.commit()
                        continue

                    # =============================================================
                    # 步骤4: 准备 AI 交互参数
                    # =============================================================
                    response_client_msg_no = f"ai_fallback_{uuid4().hex}"

                    # 查找活跃会话获取分配的客服
                    # 从客服 UID 发送 AI 回复，让访客以为是客服在回复
                    session = db.query(VisitorSession).filter(
                        VisitorSession.visitor_id == visitor.id,
                        VisitorSession.status == SessionStatus.OPEN.value,
                        VisitorSession.staff_id.isnot(None)
                    ).first()

                    if session and session.staff_id:
                        # 使用客服的 UID 发送消息（模拟客服回复）
                        from_uid = f"{session.staff_id}-staff"
                    else:
                        # 如果没有客服分配，无法进行 AI 兜底（需要身份标识）
                        logger.debug(f"No staff assigned to visitor {visitor.id}, using fallback AI UID")
                        visitor.ai_fallback_retry_count = MAX_AI_FALLBACK_RETRIES
                        db.add(visitor)
                        db.commit()
                        continue

                    # =============================================================
                    # 步骤5: 调用 AI 生成回复（同步等待）
                    # =============================================================
                    agent_runtime_kwargs: dict[str, str] = {}
                    if platform.agent_id is not None:
                        agent_runtime_kwargs["agent_id"] = str(platform.agent_id)

                    try:
                        # 调用 AI 非流式接口，等待完整响应
                        ai_result = await handle_ai_response_non_stream(
                            project_id=str(platform.project_id),
                            visitor_id=str(visitor.id),
                            message=message_content,
                            channel_id=channel_id,
                            channel_type=channel_type,
                            client_msg_no=response_client_msg_no,
                            from_uid=from_uid,
                            session_id=get_session_id(from_uid, channel_id, channel_type),
                            **agent_runtime_kwargs,
                        )

                        # =============================================================
                        # 步骤6: 处理 AI 响应结果
                        # =============================================================
                        if ai_result:
                            # AI 成功生成回复，更新访客状态
                            # 更新 is_last_message_from_ai 和 last_client_msg_no
                            # 防止重复触发相同的消息
                            visitor.is_last_message_from_ai = True
                            visitor.is_last_message_from_visitor = False
                            visitor.last_client_msg_no = response_client_msg_no
                            visitor.ai_fallback_retry_count = 0  # 成功后重置重试计数
                            db.add(visitor)
                            db.commit()
                            logger.info(f"AI fallback completed for visitor {visitor.id}")
                        else:
                            # AI 返回了空结果（没有异常但没有内容）
                            logger.warning(
                                f"AI fallback returned no result for visitor {visitor.id}, "
                                f"incrementing retry count"
                            )
                            visitor.ai_fallback_retry_count += 1
                            db.add(visitor)
                            db.commit()

                    except Exception as ai_error:
                        # AI 请求失败，增加重试计数
                        logger.error(f"AI fallback failed for visitor {visitor.id}: {ai_error}")
                        visitor.ai_fallback_retry_count += 1
                        db.add(visitor)
                        db.commit()
                        continue

                except Exception as e:
                    logger.error(f"Failed to process AI fallback for visitor {visitor.id}: {e}")
                    db.rollback()
                    continue

    except Exception as e:
        logger.error(f"Error in check_and_fallback_to_ai task: {e}", exc_info=True)
    finally:
        db.close()