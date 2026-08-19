# =============================================================================
# 模块：Store 同步服务 (Store Sync Service)
# =============================================================================
# 该模块提供了与 Store 服务进行资源状态同步的功能，主要包括：
# 1. 批量同步卸载模型到 Store
# 2. 根据提供商 ID 批量卸载所有关联模型
# 
# 设计目的：
# - 保持本地系统与 Store 服务的资源状态一致性
# - 当用户在本地删除模型时，同步通知 Store 更新安装状态
# - 支持异步后台处理，不阻塞主业务流程
# 
# 使用场景：
# - 用户删除 AI 模型时，同步更新 Store 中的安装状态
# - 删除整个 AI 提供商时，批量卸载所有关联模型
# =============================================================================

from typing import List, Union
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.utils.crypto import decrypt_str
from app.models.store_credential import StoreCredential
from app.services.store_client import store_client

logger = get_logger("store_sync")


# =============================================================================
# 函数1: 批量同步卸载模型到 Store
# =============================================================================

async def sync_uninstall_models_to_store(
    db: Session,
    project_id: Union[str, UUID],
    store_resource_ids: List[str]
) -> None:
    """
    异步通知 Store API 卸载模型。

    执行流程：
    1. 获取项目的 Store 凭证
    2. 解密 API Key
    3. 遍历每个 Store 资源 ID，调用 Store 的卸载 API
    4. 单个失败不影响其他模型的卸载

    使用场景：
    - 与 FastAPI BackgroundTasks 配合使用
    - 在删除模型后异步同步状态到 Store

    设计考量：
    - 使用后台任务执行，不阻塞主请求
    - 逐个调用 API，避免单点失败影响全部
    - 记录详细日志便于问题排查
    - 对每个资源的卸载操作独立处理

    Args:
        db: 数据库会话
        project_id: 项目 ID
        store_resource_ids: 需要卸载的 Store 资源 ID 列表

    Returns:
        None
    """
    # =====================================================================
    # 前置检查：如果没有需要卸载的资源，直接返回
    # =====================================================================
    if not store_resource_ids:
        return

    # =====================================================================
    # 步骤1: 获取项目的 Store 凭证
    # =====================================================================
    credential = db.scalar(
        select(StoreCredential).where(StoreCredential.project_id == project_id)
    )
    if not credential:
        logger.warning(f"Project {project_id} not bound to Store, skipping uninstall sync")
        return

    # =====================================================================
    # 步骤2: 解密 API Key
    # =====================================================================
    # StoreCredential 中存储的是加密的 API Key
    api_key = decrypt_str(credential.api_key_encrypted)
    if not api_key:
        logger.error(f"Failed to decrypt API Key for project {project_id}")
        return

    # =====================================================================
    # 步骤3: 逐个调用 Store API 卸载模型
    # =====================================================================
    for resource_id in store_resource_ids:
        try:
            logger.info(
                f"Syncing uninstall to Store: project={project_id}, resource={resource_id}"
            )
            # 调用 Store 客户端的卸载模型 API
            await store_client.uninstall_model(resource_id, api_key)
        except Exception as e:
            # 单个资源卸载失败不影响其他资源
            logger.error(f"Failed to sync uninstall to Store for {resource_id}: {str(e)}")


# =============================================================================
# 函数2: 批量卸载提供商的所有模型
# =============================================================================

async def sync_uninstall_all_provider_models(
    db: Session,
    project_id: Union[str, UUID],
    provider_id: UUID
) -> None:
    """
    获取提供商的所有带有 store_resource_id 的模型，并批量卸载它们。

    执行流程：
    1. 查询该提供商下所有有 store_resource_id 的模型
    2. 提取所有 store_resource_id
    3. 如果有资源 ID，调用批量卸载函数

    使用场景：
    - 用户删除整个 AI 提供商时
    - 需要清理该提供商在 Store 中的所有模型安装记录

    Args:
        db: 数据库会话
        project_id: 项目 ID
        provider_id: AI 提供商 ID

    Returns:
        None
    """
    # =====================================================================
    # 延迟导入避免循环依赖
    # =====================================================================
    from app.models.ai_model import AIModel

    # =====================================================================
    # 步骤1: 查询该提供商下有 store_resource_id 的模型
    # =====================================================================
    # 过滤条件：
    # - provider_id 匹配
    # - store_resource_id 不为空（表示该模型已从 Store 安装）
    # - 未被软删除
    models = db.scalars(
        select(AIModel).where(
            AIModel.provider_id == provider_id,
            AIModel.store_resource_id.is_not(None),
            AIModel.deleted_at.is_(None)
        )
    ).all()

    # =====================================================================
    # 步骤2: 提取资源 ID 列表
    # =====================================================================
    resource_ids = [m.store_resource_id for m in models]

    # =====================================================================
    # 步骤3: 如果有资源，执行批量卸载
    # =====================================================================
    if resource_ids:
        await sync_uninstall_models_to_store(db, project_id, resource_ids)