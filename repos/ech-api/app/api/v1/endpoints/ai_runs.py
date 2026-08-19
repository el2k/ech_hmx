# -*- coding: utf-8 -*-
"""AI Runs helper endpoints (cancel by client_msg_no)."""
# 模块说明：AI运行辅助端点，提供通过 client_msg_no 取消 Supervisor 运行的能力。
# 支持两种认证方式：访客端（Platform API Key）和员工端（JWT Token）。

from __future__ import annotations

from typing import Optional, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.database import get_db
from app.core.security import get_current_active_user
from app.models import Platform, Staff
from app.services.ai_client import ai_client
from app.services.run_registry import run_registry

# 获取当前模块的日志记录器
logger = get_logger("endpoints.ai_runs")
# 创建API路由实例
router = APIRouter()


# ------------------- 请求模型定义 -------------------

class CancelByClientNoRequest(BaseModel):
    """
    访客端取消请求模型（使用 Platform API Key 认证）。
    
    用于访客（网站用户）通过前端发起取消AI运行请求。
    """
    platform_api_key: str = Field(..., description="Platform API key (visitor-facing authentication)")
    # platform_api_key: 平台API密钥，用于验证访客身份
    # 游客端通过此密钥标识所属项目
    
    client_msg_no: str = Field(..., description="Correlation ID used in streaming, i.e., client_msg_no")
    # client_msg_no: 流式消息的关联ID，用于标识具体的AI运行会话
    # 这是客户端生成的消息ID，用于追踪整个对话流
    
    reason: Optional[str] = Field(None, description="Optional reason for cancellation (for auditing)")
    # reason: 取消原因（可选），用于审计日志记录


class StaffCancelRequest(BaseModel):
    """
    员工端取消请求模型（使用 JWT 认证）。
    
    用于客服人员通过管理后台取消AI运行。
    """
    client_msg_no: str = Field(..., description="Correlation ID used in streaming, i.e., client_msg_no")
    # client_msg_no: 流式消息的关联ID
    
    reason: Optional[str] = Field(None, description="Optional reason for cancellation (for auditing)")
    # reason: 取消原因（可选）


# ------------------- 端点1：访客端取消 -------------------

@router.post(
    "/cancel-by-client",
    status_code=202,
    summary="Cancel Supervisor Run by client_msg_no",
    description=(
        "Cancel a running supervisor agent execution by client_msg_no. "
        "If the run has not yet started (run_id unknown), the cancellation will be queued and sent immediately on start."
    ),
)
async def cancel_by_client_no(
    req: CancelByClientNoRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    访客端取消AI运行端点。
    
    认证方式：Platform API Key（非用户JWT，适用于未登录访客）
    
    处理逻辑：
        1. 验证 Platform API Key 有效性
        2. 通过 client_msg_no 查找运行记录
        3. 如果运行已开始（有 run_id），立即调用 AI 服务取消
        4. 如果运行尚未开始（无 run_id），标记为待取消，等待启动时取消
        5. 项目隔离：确保只能取消自己项目下的运行
    """
    # ==================== 第1步：认证 ====================
    # 通过 platform_api_key 验证访客身份（游客端认证）
    platform = (
        db.query(Platform)
        .filter(
            Platform.api_key == req.platform_api_key,      # API密钥匹配
            Platform.is_active.is_(True),                  # 平台处于激活状态
            Platform.deleted_at.is_(None),                 # 未被软删除
        )
        .first()
    )
    if not platform:
        # 认证失败返回401
        raise HTTPException(status_code=401, detail="Invalid platform API key")

    # ==================== 第2步：查找运行记录 ====================
    # 从运行注册表中获取与 client_msg_no 关联的运行信息
    entry = await run_registry.get(req.client_msg_no)
    
    # ==================== 第3步：项目隔离检查 ====================
    # 如果存在记录且有 project_id，确保请求方属于同一项目
    # 防止跨项目取消（安全隔离）
    if entry is not None and entry.project_id and str(entry.project_id) != str(platform.project_id):
        # 返回404而非403，避免泄露运行是否存在的信息（安全最佳实践）
        raise HTTPException(status_code=404, detail="Run not found for current project")

    # ==================== 第4步：根据运行状态处理 ====================
    forward_project_id: Optional[str] = None
    
    if entry and entry.run_id:
        # ---------- 情况A：运行已启动 ----------
        # 有 run_id 表示AI运行已经开始，立即发送取消请求
        forward_project_id = entry.project_id or str(platform.project_id)
        if not forward_project_id:
            # 缺少项目ID，无法取消
            raise HTTPException(status_code=500, detail="Missing project_id for cancellation")

        # 调试日志（生产环境应使用 logger.debug）
        print("Cancel-by-client: immediate cancel --> ", entry.run_id)
        
        try:
            # 调用 AI 客户端取消运行
            await ai_client.cancel_supervisor_run(
                project_id=forward_project_id,
                run_id=entry.run_id,
                reason=req.reason,
            )
        except HTTPException as e:
            # 上游服务返回错误（通常即使运行已完成，也会返回202）
            # 记录警告日志，将异常向上传播
            logger.warning(
                "Cancel-by-client encountered upstream error",
                extra={
                    "client_msg_no": req.client_msg_no,
                    "status_code": e.status_code,
                    "detail": e.detail,
                },
            )
            raise
        
        # 取消请求已发送
        return {"accepted": True, "status": "sent", "client_msg_no": req.client_msg_no}

    # ---------- 情况B：运行尚未启动 ----------
    # 没有 run_id 或没有 entry 记录
    # 标记为待取消，当 ai_processor 获取到 run_id 时会检查并立即取消
    await run_registry.mark_cancel_pending(
        req.client_msg_no,
        reason=req.reason,
        project_id=str(platform.project_id),
        api_key=None,
    )
    return {"accepted": True, "status": "pending", "client_msg_no": req.client_msg_no}


# ------------------- 端点2：员工端取消 -------------------

@router.post(
    "/cancel",
    status_code=202,
    summary="Cancel Supervisor Run by client_msg_no (Staff)",
    description=(
        "Cancel a running supervisor agent execution by client_msg_no. "
        "This endpoint is for staff (customer service agents) and requires JWT authentication. "
        "If the run has not yet started (run_id unknown), the cancellation will be queued and sent immediately on start."
    ),
)
async def cancel_run_by_staff(
    req: StaffCancelRequest,
    db: Session = Depends(get_db),
    current_user: Staff = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """
    员工端取消AI运行端点。
    
    认证方式：JWT Token（员工登录后访问）
    
    适用场景：
        - 客服人员在管理后台取消正在进行的AI对话
        - 管理员干预AI行为
    
    处理逻辑与访客端类似，但使用 JWT 认证，记录员工信息用于审计。
    """
    # ==================== 第1步：查找运行记录 ====================
    entry = await run_registry.get(req.client_msg_no)

    # ==================== 第2步：项目隔离检查 ====================
    # 使用当前员工所属项目进行隔离验证
    if entry is not None and entry.project_id and str(entry.project_id) != str(current_user.project_id):
        # 返回404防止泄露运行信息
        raise HTTPException(status_code=404, detail="Run not found for current project")

    # ==================== 第3步：根据运行状态处理 ====================
    forward_project_id: Optional[str] = None
    
    if entry and entry.run_id:
        # ---------- 情况A：运行已启动 ----------
        forward_project_id = entry.project_id or str(current_user.project_id)
        if not forward_project_id:
            raise HTTPException(status_code=500, detail="Missing project_id for cancellation")

        # 记录员工取消操作日志（审计追踪）
        logger.info(
            "Staff cancel: immediate cancel",
            extra={
                "client_msg_no": req.client_msg_no,
                "run_id": entry.run_id,
                "staff_id": str(current_user.id),
                "username": current_user.username,
            },
        )
        
        try:
            # 调用 AI 客户端取消运行
            await ai_client.cancel_supervisor_run(
                project_id=forward_project_id,
                run_id=entry.run_id,
                reason=req.reason,
            )
        except HTTPException as e:
            # 记录上游错误
            logger.warning(
                "Staff cancel encountered upstream error",
                extra={
                    "client_msg_no": req.client_msg_no,
                    "status_code": e.status_code,
                    "detail": e.detail,
                },
            )
            raise
        
        return {"accepted": True, "status": "sent", "client_msg_no": req.client_msg_no}

    # ---------- 情况B：运行尚未启动 ----------
    # 标记为待取消，记录员工信息便于追踪
    logger.info(
        "Staff cancel: marking pending",
        extra={
            "client_msg_no": req.client_msg_no,
            "staff_id": str(current_user.id),
            "username": current_user.username,
        },
    )
    
    await run_registry.mark_cancel_pending(
        req.client_msg_no,
        reason=req.reason,
        project_id=str(current_user.project_id),
        api_key=None,
    )
    return {"accepted": True, "status": "pending", "client_msg_no": req.client_msg_no}