# -*- coding: utf-8 -*-
"""AI Tools endpoints - proxy to AI service."""
# 模块说明：AI工具代理端点，将工具管理请求转发到 tgo-ai 服务。
# 工具（Tool）是AI能够调用的外部能力扩展，使AI可以执行实际操作。

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.security import get_authenticated_project
from app.schemas.tools import ToolCreateRequest, ToolResponse, ToolType, ToolUpdateRequest
from app.services.ai_client import ai_client

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# 工具管理 - 让AI拥有"动手能力"
# ============================================================================

# 工具管理
# 通过添加 HTTP 接口或 MCP 协议工具，您可以让 AI 员工具备搜索、查询数据库、调用外部服务等无限可能。
#
# 工具类型说明：
#   - MCP (Model Context Protocol)：通过 MCP 协议连接的外部工具服务器
#   - FUNCTION：HTTP API 调用类型的函数工具
#   - ALL：查询所有类型（仅用于过滤）
#
# 工具的本质：让AI从"只能聊天"升级为"能执行操作"，例如：
#   - 查询数据库
#   - 调用第三方API
#   - 发送邮件/消息
#   - 执行计算/数据处理


@router.get("", response_model=List[ToolResponse])
async def list_tools(
    tool_type: Optional[ToolType] = Query(None, description="Filter by tool type (MCP, FUNCTION, or ALL)"),
    include_deleted: bool = Query(False, description="Include soft-deleted tools"),
    project_and_api_key=Depends(get_authenticated_project),
) -> List[ToolResponse]:
    """
    获取当前项目的所有工具列表。

    支持按工具类型过滤，并可选择是否包含已软删除的工具。

    代理到 AI 服务端点：GET /api/v1/tools

    Args:
        tool_type: 工具类型过滤（MCP / FUNCTION / ALL）
        include_deleted: 是否包含软删除的工具
        project_and_api_key: 认证数据（当前项目）

    Returns:
        List[ToolResponse]: 工具列表
    """
    project, _ = project_and_api_key
    
    # 将 'ALL' 映射为 None（下游服务用 None 表示查询所有类型）
    # ToolType.ALL 是前端便利选项，下游服务不需要这个值
    effective_tool_type = None if tool_type == ToolType.ALL else (tool_type.value if tool_type else None)
    
    logger.info(
        f"Listing tools for project {project.id}",
        extra={
            "project_id": str(project.id),
            "tool_type": tool_type,
            "effective_tool_type": effective_tool_type,
            "include_deleted": include_deleted,
        }
    )
    
    # 调用 AI 客户端服务获取工具列表
    result = await ai_client.list_tools(
        project_id=str(project.id),
        tool_type=effective_tool_type,
        include_deleted=include_deleted,
    )
    
    return result


@router.post("", response_model=ToolResponse, status_code=201)
async def create_tool(
    tool_data: ToolCreateRequest,
    project_and_api_key=Depends(get_authenticated_project),
) -> ToolResponse:
    """
    为当前项目创建一个新工具。

    代理到 AI 服务端点：POST /api/v1/tools

    工具创建需要指定：
        - name: 工具名称（唯一标识）
        - tool_type: 工具类型（MCP 或 FUNCTION）
        - 根据类型不同，需要不同的配置参数

    Args:
        tool_data: 工具创建请求体
        project_and_api_key: 认证数据

    Returns:
        ToolResponse: 创建成功的工具详情
    """
    project, _ = project_and_api_key

    logger.info(
        f"Creating tool for project {project.id}",
        extra={
            "project_id": str(project.id),
            "tool_name": tool_data.name,
            "tool_type": tool_data.tool_type,
        }
    )

    # 将请求数据转为字典，并从认证上下文注入 project_id
    tool_data_dict = tool_data.model_dump(exclude_none=True)
    tool_data_dict["project_id"] = str(project.id)  # 注入项目ID，确保工具属于当前项目

    # 调用 AI 客户端创建工具
    result = await ai_client.create_tool(tool_data=tool_data_dict)

    return result


@router.patch("/{tool_id}", response_model=ToolResponse)
async def update_tool(
    tool_id: UUID,
    tool_data: ToolUpdateRequest,
    project_and_api_key=Depends(get_authenticated_project),
) -> ToolResponse:
    """
    更新已有工具（部分更新）。

    代理到 AI 服务端点：PATCH /api/v1/tools/{tool_id}

    支持更新的字段：
        - name: 工具名称
        - description: 工具描述
        - 配置参数（根据工具类型不同）

    使用 PATCH 方法，只传递需要修改的字段即可。

    Args:
        tool_id: 工具ID（UUID格式）
        tool_data: 更新请求体（包含需要修改的字段）
        project_and_api_key: 认证数据

    Returns:
        ToolResponse: 更新后的工具详情
    """
    project, _ = project_and_api_key

    logger.info(
        f"Updating tool {tool_id} for project {project.id}",
        extra={
            "project_id": str(project.id),
            "tool_id": str(tool_id),
            "update_fields": list(tool_data.model_dump(exclude_none=True).keys()),
        }
    )

    # 转为字典，排除 None 值（只更新提供字段）
    tool_data_dict = tool_data.model_dump(exclude_none=True)

    # 调用 AI 客户端更新工具
    result = await ai_client.update_tool(
        project_id=str(project.id),
        tool_id=str(tool_id),
        tool_data=tool_data_dict,
    )

    return result


@router.delete("/{tool_id}", response_model=ToolResponse)
async def delete_tool(
    tool_id: UUID,
    project_and_api_key=Depends(get_authenticated_project),
) -> ToolResponse:
    """
    删除工具（软删除）。

    代理到 AI 服务端点：DELETE /api/v1/tools/{tool_id}

    软删除意味着：
        - 工具不会被物理删除
        - 标记为已删除状态（deleted_at 字段）
        - 可通过 include_deleted=True 参数查询到
        - 可以恢复（通过更新接口取消删除标记）

    软删除的好处：
        - 数据可恢复，防止误删
        - 保留审计痕迹
        - 关联数据不受影响

    Args:
        tool_id: 工具ID
        project_and_api_key: 认证数据

    Returns:
        ToolResponse: 删除后的工具状态（包含删除标记）
    """
    project, _ = project_and_api_key

    logger.info(
        f"Deleting tool {tool_id} for project {project.id}",
        extra={
            "project_id": str(project.id),
            "tool_id": str(tool_id),
        }
    )

    # 调用 AI 客户端删除工具
    result = await ai_client.delete_tool(
        project_id=str(project.id),
        tool_id=str(tool_id),
    )

    return result