# =============================================================================
# 模块：新用户引导进度服务 (Onboarding progress service)
# =============================================================================
# 该模块提供了检查新用户引导步骤完成状态的服务，主要包括：
# 1. 检查 AI 提供商是否已配置
# 2. 检查默认模型是否已配置
# 3. 检查 RAG 集合是否已创建
# 4. 检查 Agent 是否已创建
# 5. 汇总所有步骤状态并计算进度
# 
# 设计目的：
# - 为用户提供清晰的新手引导进度追踪
# - 帮助用户了解哪些配置步骤已完成
# - 引导用户完成项目的完整配置
# =============================================================================

from typing import Dict, List, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import AIProvider, ProjectAIConfig
from app.services.ai_client import AIServiceClient
from app.services.rag_client import RAGServiceClient

logger = get_logger("services.onboarding")


# =============================================================================
# 步骤1: 检查 AI 提供商
# =============================================================================

async def check_step_1_ai_provider(db: Session, project_id: UUID) -> bool:
    """
    检查项目是否至少有一个活跃的 AI 提供商。

    这是入门引导的第一步，用户需要先配置 AI 提供商才能使用 AI 功能。

    Args:
        db: 数据库会话
        project_id: 项目 ID

    Returns:
        bool: 至少有一个活跃的 AI 提供商返回 True
    """
    count = (
        db.query(AIProvider.id)
        .filter(
            AIProvider.project_id == project_id,
            AIProvider.is_active == True,  # noqa: E712 - SQLAlchemy 要求使用 == 比较布尔值
            AIProvider.deleted_at.is_(None),
        )
        .count()
    )
    return count > 0


# =============================================================================
# 步骤2: 检查默认模型配置
# =============================================================================

async def check_step_2_default_models(db: Session, project_id: UUID) -> bool:
    """
    检查项目是否已配置默认的聊天模型和嵌入模型。

    必要条件（四个字段都必须配置）：
    1. default_chat_provider_id - 默认聊天提供商
    2. default_chat_model - 默认聊天模型
    3. default_embedding_provider_id - 默认嵌入提供商
    4. default_embedding_model - 默认嵌入模型

    此外，还需验证两个提供商存在且处于活跃状态。

    Args:
        db: 数据库会话
        project_id: 项目 ID

    Returns:
        bool: 所有默认模型配置完整且有效返回 True
    """
    # 查询项目的 AI 配置
    cfg = (
        db.query(ProjectAIConfig)
        .filter(
            ProjectAIConfig.project_id == project_id,
            ProjectAIConfig.deleted_at.is_(None),
        )
        .first()
    )
    if not cfg:
        return False

    # =====================================================================
    # 验证所有四个字段是否都已设置
    # =====================================================================
    if not all([
        cfg.default_chat_provider_id,
        cfg.default_chat_model,
        cfg.default_embedding_provider_id,
        cfg.default_embedding_model,
    ]):
        return False

    # =====================================================================
    # 验证引用的提供商存在且处于活跃状态
    # =====================================================================
    provider_ids = [cfg.default_chat_provider_id, cfg.default_embedding_provider_id]
    valid_count = (
        db.query(AIProvider.id)
        .filter(
            AIProvider.id.in_(provider_ids),
            AIProvider.project_id == project_id,
            AIProvider.is_active == True,  # noqa: E712
            AIProvider.deleted_at.is_(None),
        )
        .count()
    )
    # 两个提供商都必须存在且活跃
    return valid_count == 2


# =============================================================================
# 步骤3: 检查 RAG 集合
# =============================================================================

async def check_step_3_rag_collection(project_id: UUID) -> bool:
    """
    检查项目是否至少有一个 RAG 集合。

    RAG (Retrieval-Augmented Generation) 集合用于知识库检索增强生成，
    是构建智能问答系统的重要组件。

    Args:
        project_id: 项目 ID

    Returns:
        bool: 至少有一个 RAG 集合返回 True

    Note:
        如果 RAG 服务不可用，返回 False 并记录警告日志
    """
    try:
        rag_client = RAGServiceClient()
        result = await rag_client.list_collections(
            project_id=str(project_id),
            limit=1,  # 只需要知道是否有至少一个
            offset=0,
        )
        total = result.get("pagination", {}).get("total", 0)
        return total > 0
    except Exception as e:
        # RAG 服务不可用时不阻塞引导流程
        logger.warning(
            "Failed to check RAG collections for onboarding",
            extra={"project_id": str(project_id), "error": str(e)},
        )
        return False


# =============================================================================
# 步骤4: 检查 Agent
# =============================================================================

async def check_step_4_agent_created(project_id: UUID) -> bool:
    """
    检查项目是否至少有一个 Agent。

    Agent 是 AI 应用的核心执行单元，负责处理用户请求和调用工具。

    Args:
        project_id: 项目 ID

    Returns:
        bool: 至少有一个 Agent 返回 True

    Note:
        如果 AI 服务不可用，返回 False 并记录警告日志
    """
    try:
        ai_client = AIServiceClient()
        result = await ai_client.list_agents(
            project_id=str(project_id),
            limit=1,  # 只需要知道是否有至少一个
            offset=0,
        )
        agents = result.get("data", [])
        return len(agents) > 0
    except Exception as e:
        # AI 服务不可用时不阻塞引导流程
        logger.warning(
            "Failed to check agents for onboarding",
            extra={"project_id": str(project_id), "error": str(e)},
        )
        return False


# =============================================================================
# 汇总所有步骤
# =============================================================================

async def check_all_steps(
    db: Session, project_id: UUID
) -> Tuple[List[bool], int, int]:
    """
    检查所有新用户引导步骤并返回状态。

    步骤说明：
    - 步骤1: 配置 AI 提供商
    - 步骤2: 配置默认模型
    - 步骤3: 创建 RAG 集合
    - 步骤4: 创建 Agent
    - 步骤5: 通知类型步骤（始终返回 False，仅作为用户提示）

    注意：步骤5 是 'notify' 类型，总是返回 False，
    因为它只是给用户的提醒，不是一个需要完成的操作。

    返回格式：
    - step_statuses: 五个步骤的完成状态列表
    - current_step: 当前需要完成的步骤（1-5）
    - progress_percentage: 进度百分比（基于步骤1-4计算）

    Args:
        db: 数据库会话
        project_id: 项目 ID

    Returns:
        Tuple[List[bool], int, int]: (步骤状态列表, 当前步骤, 进度百分比)
    """
    # =====================================================================
    # 并行检查所有步骤
    # =====================================================================
    step_1 = await check_step_1_ai_provider(db, project_id)
    step_2 = await check_step_2_default_models(db, project_id)
    step_3 = await check_step_3_rag_collection(project_id)
    step_4 = await check_step_4_agent_created(project_id)
    # 步骤5 是通知类型，不需要检查完成状态
    step_5 = False

    steps = [step_1, step_2, step_3, step_4, step_5]

    # =====================================================================
    # 计算当前步骤
    # =====================================================================
    # 找到第一个未完成的操作步骤（步骤1-4）
    # 如果步骤1-4都已完成，当前步骤为5（引导完成，进入通知状态）
    current_step = 5
    for i in range(4):  # 只检查步骤1-4
        if not steps[i]:
            current_step = i + 1
            break

    # =====================================================================
    # 计算进度百分比（基于步骤1-4）
    # =====================================================================
    completed_count = sum(1 for s in steps[:4] if s)
    progress_percentage = int((completed_count / 4) * 100)

    return steps, current_step, progress_percentage