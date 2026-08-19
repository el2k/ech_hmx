# -*- coding: utf-8 -*-
"""AI Skills proxy endpoints (forwarded to tgo-ai service)."""
# 模块说明：AI技能代理端点，将请求转发到 tgo-ai 服务。
# 技能（Skill）是为 AI 员工定义的可复用专业指令集，相当于给AI添加"专业技能包"。

from typing import Any, Dict, List

from fastapi import APIRouter, Body, Depends, HTTPException, Response, status

from app.core.logging import get_logger
from app.core.security import get_authenticated_project
from app.schemas.skill import (
    SkillCreateRequest,
    SkillDetail,
    SkillImportRequest,
    SkillSummary,
    SkillToggleRequest,
    SkillToggleResponse,
    SkillUpdateRequest,
)
from app.services.ai_client import ai_client

logger = get_logger("endpoints.ai_skills")
router = APIRouter()


# ============================================================================
# 技能 CRUD 操作（创建、读取、更新、删除）
# ============================================================================

# AI功能，技能管理页，为 AI 员工定义可复用的专业指令集
# 技能类似于 AI 的"专业技能模块"，包含：
#   - SKILL.md：技能描述和使用说明
#   - 脚本文件（.py, .js 等）
#   - 参考文档和配置文件


@router.get(
    "",
    response_model=List[SkillSummary],
    summary="List all skills",
    description="List all skills visible to the current project (private + official).",
)
async def list_skills(
    auth_data: tuple[Any, str] = Depends(get_authenticated_project),
) -> List[SkillSummary]:
    """
    获取当前项目可见的所有技能列表。
    
    返回两种类型的技能：
        1. 私有技能（Project-private）：当前项目自定义创建
        2. 官方技能（Official）：系统预置的通用技能
    
    认证方式：get_authenticated_project 通过 API Key 验证项目身份
    
    Returns:
        List[SkillSummary]: 技能概要列表（仅包含名称、描述等摘要信息）
    """
    project, _ = auth_data  # 解包认证数据，获取项目对象
    project_id = str(project.id)
    # 调用 AI 客户端服务获取技能列表
    result = await ai_client.list_skills(project_id)
    # 将返回的字典列表转换为 SkillSummary 对象列表（Pydantic 自动验证）
    return [SkillSummary(**item) for item in result]


@router.post(
    "",
    response_model=SkillDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new skill",
    description="Create a new project-private skill.",
)
async def create_skill(
    data: SkillCreateRequest,
    auth_data: tuple[Any, str] = Depends(get_authenticated_project),
) -> SkillDetail:
    """
    创建一个新的私有技能。
    
    技能创建需要提供：
        - name: 技能名称（唯一标识）
        - description: 技能描述
        - instructions: 技能指令/提示词（核心内容）
        - 可选的脚本文件和参考文件
    
    创建后的技能仅当前项目可见和使用。
    
    Args:
        data: 技能创建请求体
        auth_data: 认证数据（项目信息）
    
    Returns:
        SkillDetail: 创建成功的技能详情（包含完整信息）
    """
    project, _ = auth_data
    project_id = str(project.id)
    # model_dump(exclude_none=True) 排除 None 值，只传递有效字段
    result = await ai_client.create_skill(project_id, data.model_dump(exclude_none=True))
    return SkillDetail(**result)


@router.get(
    "/{skill_name}",
    response_model=SkillDetail,
    summary="Get skill details",
    description="Get full detail of a skill including instructions and file listings.",
)
async def get_skill(
    skill_name: str,
    auth_data: tuple[Any, str] = Depends(get_authenticated_project),
) -> SkillDetail:
    """
    获取技能的完整详情。
    
    包含：
        - 技能基本信息（名称、描述等）
        - instructions（技能指令/提示词）
        - 文件列表（脚本、参考文档等）
        - 启用/禁用状态
    
    Args:
        skill_name: 技能名称（URL路径参数）
        auth_data: 认证数据
    
    Returns:
        SkillDetail: 完整的技能详情
    """
    project, _ = auth_data
    project_id = str(project.id)
    result = await ai_client.get_skill(project_id, skill_name)
    return SkillDetail(**result)


@router.patch(
    "/{skill_name}",
    response_model=SkillDetail,
    summary="Update a skill",
    description="Update SKILL.md content for a project-private skill.",
)
async def update_skill(
    skill_name: str,
    data: SkillUpdateRequest,
    auth_data: tuple[Any, str] = Depends(get_authenticated_project),
) -> SkillDetail:
    """
    更新技能内容（部分更新）。
    
    支持更新的字段：
        - description: 技能描述
        - instructions: 技能指令内容（SKILL.md 的核心）
        - 其他元数据
    
    使用 PATCH 方法实现部分更新，只传递需要修改的字段即可。
    
    Args:
        skill_name: 技能名称
        data: 更新请求体（包含需要更新的字段）
        auth_data: 认证数据
    
    Returns:
        SkillDetail: 更新后的技能详情
    """
    project, _ = auth_data
    project_id = str(project.id)
    result = await ai_client.update_skill(
        project_id, skill_name, data.model_dump(exclude_none=True)
    )
    return SkillDetail(**result)


@router.delete(
    "/{skill_name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a skill",
    description="Delete a project-private skill directory entirely.",
)
async def delete_skill(
    skill_name: str,
    auth_data: tuple[Any, str] = Depends(get_authenticated_project),
) -> Response:
    """
    删除一个私有技能（完全删除技能目录及其所有文件）。
    
    注意：
        - 只能删除当前项目的私有技能
        - 官方技能（Official）不可删除
        - 删除操作不可恢复
    
    Args:
        skill_name: 技能名称
        auth_data: 认证数据
    
    Returns:
        Response: 204 No Content（成功删除无返回内容）
    """
    project, _ = auth_data
    project_id = str(project.id)
    await ai_client.delete_skill(project_id, skill_name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ============================================================================
# 技能启用/禁用
# ============================================================================


@router.put(
    "/{skill_name}/toggle",
    response_model=SkillToggleResponse,
    summary="Toggle skill enabled/disabled",
    description="Enable or disable a skill for the current project.",
)
async def toggle_skill(
    skill_name: str,
    data: SkillToggleRequest,
    auth_data: tuple[Any, str] = Depends(get_authenticated_project),
) -> SkillToggleResponse:
    """
    切换技能的启用/禁用状态。
    
    使用场景：
        - 临时禁用某个技能而不删除
        - 在AI对话中控制哪些技能生效
        - 测试技能效果时快速开关
    
    技能被禁用后，AI在处理对话时将不会加载该技能的指令。
    
    Args:
        skill_name: 技能名称
        data: 切换请求（包含 enabled 布尔值）
        auth_data: 认证数据
    
    Returns:
        SkillToggleResponse: 切换后的状态信息
    """
    project, _ = auth_data
    project_id = str(project.id)
    result = await ai_client.toggle_skill(
        project_id, skill_name, data.model_dump()
    )
    return SkillToggleResponse(**result)


# ============================================================================
# 从 GitHub 导入技能
# ============================================================================


@router.post(
    "/import",
    response_model=SkillDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Import a skill from GitHub",
    description="Download a skill directory from a GitHub URL and create it as a project-private skill.",
)
async def import_skill(
    data: SkillImportRequest,
    auth_data: tuple[Any, str] = Depends(get_authenticated_project),
) -> SkillDetail:
    """
    从 GitHub 仓库导入技能。
    
    功能说明：
        1. 用户提供 GitHub 仓库 URL
        2. 系统下载技能目录（包含 SKILL.md 和相关文件）
        3. 自动创建为当前项目的私有技能
    
    适用场景：
        - 使用社区共享的优质技能
        - 从模板快速创建技能
        - 跨项目迁移技能
    
    Args:
        data: 导入请求（包含 GitHub URL）
        auth_data: 认证数据
    
    Returns:
        SkillDetail: 导入成功的技能详情
    """
    project, _ = auth_data
    project_id = str(project.id)
    result = await ai_client.import_skill(
        project_id, data.model_dump(exclude_none=True)
    )
    return SkillDetail(**result)


# ============================================================================
# 技能子文件管理（技能内部的文件）
# ============================================================================

# 技能目录结构示例：
#   my-skill/
#   ├── SKILL.md          # 技能主文件（指令+描述）
#   ├── scripts/
#   │   ├── main.py       # Python 脚本
#   │   └── helper.js     # JavaScript 脚本
#   └── references/
#       └── config.json   # 参考配置文件


@router.get(
    "/{skill_name}/files/{file_path:path}",
    summary="Read a skill sub-file",
    description="Read the content of a script or reference file within a skill.",
)
async def get_skill_file(
    skill_name: str,
    file_path: str,
    auth_data: tuple[Any, str] = Depends(get_authenticated_project),
) -> Response:
    """
    读取技能内的子文件内容。
    
    支持读取技能目录下的任意文件（脚本、配置、文档等）。
    file_path 支持多级路径，如 "scripts/main.py" 或 "references/config.json"。
    
    Args:
        skill_name: 技能名称
        file_path: 文件相对路径（相对于技能根目录）
        auth_data: 认证数据
    
    Returns:
        Response: 文件内容，以纯文本格式返回（UTF-8 编码）
    """
    project, _ = auth_data
    project_id = str(project.id)
    content = await ai_client.get_skill_file(project_id, skill_name, file_path)
    return Response(content=content, media_type="text/plain; charset=utf-8")


@router.put(
    "/{skill_name}/files/{file_path:path}",
    status_code=status.HTTP_200_OK,
    summary="Create or update a skill sub-file",
    description="Create or update a script or reference file within a project-private skill.",
)
async def put_skill_file(
    skill_name: str,
    file_path: str,
    content: str = Body(..., media_type="text/plain"),
    auth_data: tuple[Any, str] = Depends(get_authenticated_project),
) -> Dict[str, str]:
    """
    创建或更新技能内的子文件。
    
    功能：
        1. 如果文件已存在，覆盖更新
        2. 如果文件不存在，创建新文件
        3. 支持多级目录（自动创建父目录）
    
    Args:
        skill_name: 技能名称
        file_path: 文件相对路径（如 "scripts/helper.py"）
        content: 文件内容（纯文本）
        auth_data: 认证数据
    
    Returns:
        Dict: 操作状态和文件路径
    """
    project, _ = auth_data
    project_id = str(project.id)
    await ai_client.put_skill_file(project_id, skill_name, file_path, content)
    return {"status": "ok", "file_path": file_path}


@router.delete(
    "/{skill_name}/files/{file_path:path}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a skill sub-file",
    description="Delete a script or reference file from a project-private skill.",
)
async def delete_skill_file(
    skill_name: str,
    file_path: str,
    auth_data: tuple[Any, str] = Depends(get_authenticated_project),
) -> Response:
    """
    删除技能内的子文件。
    
    注意：删除子文件不会删除技能本身，仅删除指定的文件。
    如果删除 SKILL.md，技能将变为无效状态。
    
    Args:
        skill_name: 技能名称
        file_path: 文件相对路径
        auth_data: 认证数据
    
    Returns:
        Response: 204 No Content
    """
    project, _ = auth_data
    project_id = str(project.id)
    await ai_client.delete_skill_file(project_id, skill_name, file_path)
    return Response(status_code=status.HTTP_204_NO_CONTENT)