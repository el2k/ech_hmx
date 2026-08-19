# -*- coding: utf-8 -*-
"""Workflow service proxy endpoints."""
# 模块说明：工作流服务代理端点，将工作流管理请求转发到工作流服务。
# 工作流（Workflow）是 AI 自动化任务的编排引擎，允许用户通过拖拽节点构建自动化流程。

from typing import List, Optional, Union

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.api.common_responses import CREATE_RESPONSES, CRUD_RESPONSES, LIST_RESPONSES
from app.core.security import get_current_active_user
from app.models import Staff
from app.schemas.ai_workflows import (
    PaginatedWorkflowSummaryResponse,
    WorkflowCreate,
    WorkflowDuplicateRequest,
    WorkflowExecuteRequest,
    WorkflowExecution,
    WorkflowExecutionCancelResponse,
    WorkflowInDB,
    WorkflowSyncResponse,
    WorkflowUpdate,
    WorkflowValidationResponse,
    WorkflowValidateRequest,
    WorkflowVariablesResponse,
)
from app.services.workflow_client import workflow_client

router = APIRouter()


# ============================================================================
# 工作流基础 CRUD 操作
# ============================================================================


@router.get(
    "",
    response_model=PaginatedWorkflowSummaryResponse,
    responses=LIST_RESPONSES,
    summary="List Workflows",
)
async def list_workflows(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    tags: Optional[List[str]] = Query(None),
    sort_by: str = Query("updated_at"),
    sort_order: str = Query("desc"),
    current_user: Staff = Depends(get_current_active_user),
) -> PaginatedWorkflowSummaryResponse:
    """
    获取当前项目的工作流列表（分页）。

    支持多种过滤和排序条件：
        - status: 按状态过滤（draft / published / archived）
        - search: 按名称或描述搜索
        - tags: 按标签过滤
        - sort_by: 排序字段（created_at / updated_at / name）
        - sort_order: 排序方向（asc / desc）

    Args:
        skip: 分页偏移量
        limit: 每页数量（最大100）
        status: 工作流状态过滤
        search: 搜索关键词
        tags: 标签列表过滤
        sort_by: 排序字段
        sort_order: 排序方向
        current_user: 当前登录员工

    Returns:
        PaginatedWorkflowSummaryResponse: 分页的工作流摘要列表
    """
    data = await workflow_client.list_workflows(
        project_id=str(current_user.project_id),
        skip=skip,
        limit=limit,
        status=status,
        search=search,
        tags=tags,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return PaginatedWorkflowSummaryResponse.model_validate(data)


@router.post(
    "",
    response_model=WorkflowInDB,
    responses=CREATE_RESPONSES,
    status_code=201,
    summary="Create Workflow",
)
async def create_workflow(
    workflow_data: WorkflowCreate,
    current_user: Staff = Depends(get_current_active_user),
) -> WorkflowInDB:
    """
    创建新工作流。

    工作流由节点（Nodes）和边（Edges）组成的 DAG（有向无环图）：
        - 节点：工作流中的执行单元（如 AI 对话、API 调用、条件判断、代码执行等）
        - 边：定义节点之间的执行顺序和数据流向

    Args:
        workflow_data: 工作流创建数据（包含名称、描述、节点、边等）
        current_user: 当前登录员工

    Returns:
        WorkflowInDB: 创建成功的工作流详情
    """
    data = await workflow_client.create_workflow(
        str(current_user.project_id), workflow_data.model_dump(by_alias=True)
    )
    return WorkflowInDB.model_validate(data)


@router.get(
    "/{workflow_id}",
    response_model=WorkflowInDB,
    responses=CRUD_RESPONSES,
    summary="Get Workflow",
)
async def get_workflow(
    workflow_id: str,
    current_user: Staff = Depends(get_current_active_user),
) -> WorkflowInDB:
    """
    获取工作流详情。

    包含完整的工作流定义：节点列表、边列表、变量定义等。

    Args:
        workflow_id: 工作流ID
        current_user: 当前登录员工

    Returns:
        WorkflowInDB: 工作流完整详情
    """
    data = await workflow_client.get_workflow(workflow_id, str(current_user.project_id))
    return WorkflowInDB.model_validate(data)


@router.put(
    "/{workflow_id}",
    response_model=WorkflowInDB,
    responses=CRUD_RESPONSES,
    summary="Update Workflow",
)
async def update_workflow(
    workflow_id: str,
    workflow_data: WorkflowUpdate,
    current_user: Staff = Depends(get_current_active_user),
) -> WorkflowInDB:
    """
    更新工作流（全量更新）。

    工作流更新通常涉及：
        - 修改节点配置
        - 调整节点连接（边）
        - 更新工作流变量
        - 修改名称/描述/标签

    Args:
        workflow_id: 工作流ID
        workflow_data: 更新数据
        current_user: 当前登录员工

    Returns:
        WorkflowInDB: 更新后的工作流详情
    """
    data = await workflow_client.update_workflow(
        workflow_id,
        str(current_user.project_id),
        workflow_data.model_dump(by_alias=True, exclude_none=True),
    )
    return WorkflowInDB.model_validate(data)


@router.delete(
    "/{workflow_id}",
    responses=CRUD_RESPONSES,
    status_code=204,
    summary="Delete Workflow",
)
async def delete_workflow(
    workflow_id: str,
    current_user: Staff = Depends(get_current_active_user),
) -> None:
    """
    删除工作流（硬删除）。

    警告：删除操作不可恢复，删除前应确认工作流不再需要。

    Args:
        workflow_id: 工作流ID
        current_user: 当前登录员工
    """
    await workflow_client.delete_workflow(workflow_id, str(current_user.project_id))


# ============================================================================
# 工作流高级操作
# ============================================================================


@router.post(
    "/{workflow_id}/duplicate",
    response_model=WorkflowInDB,
    responses=CRUD_RESPONSES,
    summary="Duplicate Workflow",
)
async def duplicate_workflow(
    workflow_id: str,
    request: Optional[WorkflowDuplicateRequest] = None,
    current_user: Staff = Depends(get_current_active_user),
) -> WorkflowInDB:
    """
    复制工作流。

    使用场景：
        - 基于现有工作流创建新版本
        - 快速创建相似工作流
        - 在工作流开发中保留备份

    可以选择是否同时复制执行历史。

    Args:
        workflow_id: 要复制的工作流ID
        request: 复制请求（可指定新名称、是否复制执行历史等）
        current_user: 当前登录员工

    Returns:
        WorkflowInDB: 新创建的工作流副本
    """
    payload = request.model_dump(by_alias=True, exclude_none=True) if request else None
    data = await workflow_client.duplicate_workflow(
        workflow_id, str(current_user.project_id), payload
    )
    return WorkflowInDB.model_validate(data)


@router.post(
    "/validate",
    response_model=WorkflowValidationResponse,
    responses=CRUD_RESPONSES,
    summary="Validate Workflow Generic",
)
async def validate_workflow_generic(
    request: WorkflowValidateRequest,
    current_user: Staff = Depends(get_current_active_user),
) -> WorkflowValidationResponse:
    """
    验证任意工作流图（通用验证）。

    在保存工作流之前，可以先调用此接口验证工作流定义是否有效：
        - 节点配置是否完整
        - 边连接是否形成有效 DAG
        - 数据类型是否匹配
        - 必需字段是否填写

    此接口接收完整的工作流定义（节点+边），不依赖于已保存的工作流ID。

    Args:
        request: 工作流验证请求（包含节点和边定义）
        current_user: 当前登录员工

    Returns:
        WorkflowValidationResponse: 验证结果（通过/失败 + 错误详情）
    """
    data = await workflow_client.validate_workflow_generic(
        str(current_user.project_id), request.model_dump(by_alias=True)
    )
    return WorkflowValidationResponse.model_validate(data)


@router.post(
    "/{workflow_id}/validate",
    response_model=WorkflowValidationResponse,
    responses=CRUD_RESPONSES,
    summary="Validate Workflow",
)
async def validate_workflow(
    workflow_id: str,
    current_user: Staff = Depends(get_current_active_user),
) -> WorkflowValidationResponse:
    """
    验证已存在的工作流。

    在发布工作流之前，建议先验证工作流是否有效。
    与通用验证不同，此接口根据工作流ID从数据库加载定义进行验证。

    Args:
        workflow_id: 工作流ID
        current_user: 当前登录员工

    Returns:
        WorkflowValidationResponse: 验证结果
    """
    data = await workflow_client.validate_workflow(workflow_id, str(current_user.project_id))
    return WorkflowValidationResponse.model_validate(data)


@router.post(
    "/{workflow_id}/publish",
    response_model=WorkflowInDB,
    responses=CRUD_RESPONSES,
    summary="Publish Workflow",
)
async def publish_workflow(
    workflow_id: str,
    current_user: Staff = Depends(get_current_active_user),
) -> WorkflowInDB:
    """
    发布工作流。

    工作流状态流转：
        draft（草稿）→ published（已发布）→ archived（已归档）

    发布后的工作流：
        - 可以被其他用户/系统调用
        - 可以用于创建执行实例
        - 通常锁定编辑（或进入版本管理）

    Args:
        workflow_id: 工作流ID
        current_user: 当前登录员工

    Returns:
        WorkflowInDB: 发布后的工作流详情
    """
    data = await workflow_client.publish_workflow(workflow_id, str(current_user.project_id))
    return WorkflowInDB.model_validate(data)


@router.get(
    "/{workflow_id}/variables",
    response_model=WorkflowVariablesResponse,
    responses=CRUD_RESPONSES,
    summary="Get Workflow Variables",
)
async def get_workflow_variables(
    workflow_id: str,
    current_user: Staff = Depends(get_current_active_user),
) -> WorkflowVariablesResponse:
    """
    获取工作流的可用变量列表。

    变量是工作流执行时的输入/输出参数：
        - 输入变量：执行工作流时需要传入的数据
        - 输出变量：工作流执行完成后返回的数据

    此接口用于前端动态渲染执行表单。

    Args:
        workflow_id: 工作流ID
        current_user: 当前登录员工

    Returns:
        WorkflowVariablesResponse: 变量定义列表
    """
    data = await workflow_client.get_workflow_variables(
        workflow_id, str(current_user.project_id)
    )
    return WorkflowVariablesResponse.model_validate(data)


# ============================================================================
# 工作流执行
# ============================================================================


@router.post(
    "/{workflow_id}/execute",
    summary="Execute Workflow",
    response_model=None,
    description="""
Execute a workflow using one of three supported modes:

1. **Synchronous Mode (Default, `stream=False`, `async=False`)**:
   Executes the workflow immediately and returns the final output. Ideal for short-lived tasks.

2. **Asynchronous Mode (`async=True`)**:
   Creates an execution record and triggers a background Celery task. Returns the execution record immediately.

3. **Streaming Mode (`stream=True`)**:
   Returns a Server-Sent Events (SSE) stream, pushing real-time events as the workflow progresses.

### Streaming Mode Events (SSE):
When `stream=True`, the response header includes `Content-Type: text/event-stream`.
Each message starts with `data: ` followed by a JSON string and ends with `\\n\\n`.

- **workflow_started**: Workflow execution initialized.
- **node_started**: A specific node has started executing.
- **node_finished**: A specific node has finished (success or failure).
- **workflow_finished**: Entire workflow has finished.
""",
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "schema": {
                        "oneOf": [
                            {"$ref": "#/components/schemas/WorkflowSyncResponse"},
                            {"$ref": "#/components/schemas/WorkflowExecution"},
                        ]
                    },
                    "examples": {
                        "sync_mode": {
                            "summary": "Synchronous Mode (Default)",
                            "description": "Returns final output and metadata.",
                            "value": {
                                "success": True,
                                "output": {"answer": "Paris is the capital of France."},
                                "metadata": {
                                    "duration": 1.234,
                                    "startTime": "2026-01-03T06:16:44.478Z",
                                    "endTime": "2026-01-03T06:16:45.712Z",
                                },
                            },
                        },
                        "async_mode": {
                            "summary": "Asynchronous Mode (async=true)",
                            "description": "Returns the execution record with 'pending' status.",
                            "value": {
                                 "id": "d73d5f18-3cc0-400f-ab18-c0a5f05625f5",
                                "project_id": "proj-123",
                                "workflow_id": "wf-456",
                                "status": "pending",
                                "input": {"query": "What is the capital of France?"},
                                "output": None,
                                "error": None,
                                "started_at": "2026-01-03T06:16:44.478Z",
                                "completed_at": None,
                                "duration": None,
                                "node_executions": []
                            },
                        },
                    },
                },
                "text/event-stream": {
                    "description": "Streaming Mode (stream=true)",
                    "example": (
                        "data: {\"event\": \"workflow_started\", \"workflow_run_id\": \"uuid-1\", \"task_id\": \"stream-uuid-1\", \"data\": {\"id\": \"uuid-1\", \"workflow_id\": \"wf-1\", \"inputs\": {}, \"created_at\": 1735790000}}\n\n"
                        "data: {\"event\": \"node_started\", \"workflow_run_id\": \"uuid-1\", \"task_id\": \"stream-uuid-1\", \"data\": {\"id\": \"node-exec-1\", \"node_id\": \"node-1\", \"node_type\": \"llm\", \"title\": \"AI Chat\", \"index\": 1, \"created_at\": 1735790001}}\n\n"
                        "data: {\"event\": \"node_finished\", \"workflow_run_id\": \"uuid-1\", \"task_id\": \"stream-uuid-1\", \"data\": {\"id\": \"node-exec-1\", \"node_id\": \"node-1\", \"node_type\": \"llm\", \"inputs\": {}, \"outputs\": {\"text\": \"Hello\"}, \"status\": \"succeeded\", \"error\": null, \"elapsed_time\": 0.5, \"finished_at\": 1735790002}}\n\n"
                        "data: {\"event\": \"workflow_finished\", \"workflow_run_id\": \"uuid-1\", \"task_id\": \"stream-uuid-1\", \"data\": {\"id\": \"uuid-1\", \"workflow_id\": \"wf-1\", \"status\": \"succeeded\", \"outputs\": {\"result\": \"Hello\"}, \"error\": null, \"elapsed_time\": 0.6, \"total_steps\": 1, \"finished_at\": 1735790002}}\n\n"
                    ),
                },
            },
        },
        404: {"description": "Workflow not found"},
    },
)
async def execute_workflow(
    workflow_id: str,
    request: WorkflowExecuteRequest,
    current_user: Staff = Depends(get_current_active_user),
) -> Union[WorkflowSyncResponse, WorkflowExecution, StreamingResponse]:
    """
    执行工作流。

    支持三种执行模式：

    1. **同步模式**（默认，stream=False, async=False）：
        立即执行并返回最终结果。适用于短时任务（<30秒）。

    2. **异步模式**（async=True）：
        创建执行记录并触发后台 Celery 任务，立即返回执行记录。
        适用于长时间运行的任务，通过 /executions/{execution_id} 查询状态。

    3. **流式模式**（stream=True）：
        返回 Server-Sent Events (SSE) 流，实时推送工作流执行进度。
        适用于需要实时反馈的场景（如聊天应用）。

    Args:
        workflow_id: 工作流ID
        request: 执行请求（包含输入变量和执行模式）
        current_user: 当前登录员工

    Returns:
        根据模式返回不同响应：
            - 同步模式：WorkflowSyncResponse（最终结果）
            - 异步模式：WorkflowExecution（执行记录）
            - 流式模式：StreamingResponse（SSE 流）
    """
    # 调用工作流客户端执行工作流
    res = await workflow_client.execute_workflow(
        workflow_id, str(current_user.project_id), request.model_dump(by_alias=True)
    )

    # 流式模式：返回 SSE 流
    if request.stream:
        return StreamingResponse(res, media_type="text/event-stream")

    # 判断是同步还是异步模式
    if request.async_mode:
        return WorkflowExecution.model_validate(res)
    else:
        return WorkflowSyncResponse.model_validate(res)


# ============================================================================
# 执行记录管理
# ============================================================================


@router.get(
    "/executions/{execution_id}",
    response_model=WorkflowExecution,
    summary="Get Execution Status",
)
async def get_execution(
    execution_id: str,
    current_user: Staff = Depends(get_current_active_user),
) -> WorkflowExecution:
    """
    获取工作流执行状态。

    用于异步模式下查询执行进度和结果。

    执行状态：
        - pending: 等待执行
        - running: 正在执行
        - succeeded: 执行成功
        - failed: 执行失败
        - cancelled: 已取消

    Args:
        execution_id: 执行记录ID
        current_user: 当前登录员工

    Returns:
        WorkflowExecution: 执行记录详情（包含状态、输出、错误信息等）
    """
    data = await workflow_client.get_execution(execution_id, str(current_user.project_id))
    return WorkflowExecution.model_validate(data)


@router.get(
    "/{workflow_id}/executions",
    response_model=List[WorkflowExecution],
    summary="List Workflow Executions",
)
async def list_workflow_executions(
    workflow_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: Staff = Depends(get_current_active_user),
) -> List[WorkflowExecution]:
    """
    获取工作流的所有执行历史记录。

    用于工作流的运行监控和审计：
        - 查看历史执行情况
        - 分析执行成功率
        - 排查失败原因

    Args:
        workflow_id: 工作流ID
        skip: 分页偏移量
        limit: 每页数量（最大100）
        current_user: 当前登录员工

    Returns:
        List[WorkflowExecution]: 执行记录列表
    """
    data = await workflow_client.list_workflow_executions(
        workflow_id, str(current_user.project_id), skip=skip, limit=limit
    )
    return [WorkflowExecution.model_validate(item) for item in data]


@router.post(
    "/executions/{execution_id}/cancel",
    response_model=WorkflowExecutionCancelResponse,
    responses=CRUD_RESPONSES,
    summary="Cancel Execution",
)
async def cancel_execution(
    execution_id: str,
    current_user: Staff = Depends(get_current_active_user),
) -> WorkflowExecutionCancelResponse:
    """
    取消正在执行的工作流。

    使用场景：
        - 用户主动终止长时间运行的任务
        - 管理员干预异常执行
        - 清理积压的执行任务

    取消操作会尝试优雅地停止工作流执行：
        - 正在运行的节点会收到取消信号
        - 尚未开始的节点不会启动
        - 执行状态标记为 cancelled

    Args:
        execution_id: 执行记录ID
        current_user: 当前登录员工

    Returns:
        WorkflowExecutionCancelResponse: 取消操作结果
    """
    data = await workflow_client.cancel_execution(execution_id, str(current_user.project_id))
    return WorkflowExecutionCancelResponse.model_validate(data)