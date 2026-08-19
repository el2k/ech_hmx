"""Workflow Service client for external workflow data retrieval.
# 本模块：工作流微服务HTTP异步客户端
# 工作流定义、状态、版本全部托管在独立Workflow微服务；本业务库仅存储workflow_id，通过HTTP远程拉取工作流元数据
"""

import uuid
from typing import Dict, List, Optional

import httpx
from pydantic import BaseModel, Field

from app.config import settings
from app.exceptions import NotFoundError, ValidationError


class WorkflowData(BaseModel):
    """Workflow data from Workflow service.
    # Workflow微服务返回的工作流元数据模型
    # 业务数据库只保存 workflow_id，工作流名称、标签、版本、状态等全部由远程Workflow服务提供
    """
    id: str = Field(description="Workflow ID")                     # 工作流唯一标识ID（字符串）
    name: str = Field(description="Workflow name")                 # 工作流名称
    description: Optional[str] = Field(default=None, description="Workflow description") # 工作流描述
    tags: List[str] = Field(default_factory=list, description="Workflow tags") # 工作流标签列表，无标签默认为空列表
    status: str = Field(description="Current status")             # 工作流当前状态（如 draft / published / archived）
    version: int = Field(description="Version number")             # 工作流版本号，支持多版本
    updated_at: str = Field(description="Last update time")       # 最后更新时间戳字符串


class WorkflowBatchResponse(BaseModel):
    """Response model for batch workflow retrieval.
    # 批量查询工作流返回模型（定义了但当前代码并未使用）
    # 对比RAG客户端：RAG接口返回 {workflows:[], not_found:[]}；而Workflow接口直接返回工作流数组，没有not_found字段
    """
    workflows: List[WorkflowData] = Field(description="Found workflows")
    not_found: List[str] = Field(description="Workflow IDs that were not found")


class WorkflowServiceClient:
    """Client for interacting with the external Workflow service.
    # Workflow微服务异步HTTP客户端，封装与工作流微服务的通信、异常包装
    """

    def __init__(self):
        """Initialize the Workflow service client.
        # 初始化客户端：读取配置中工作流服务地址，设置HTTP超时
        """
        self.base_url = settings.workflow_service_url  # Workflow微服务根地址，来自配置
        self.timeout = 30.0                            # 请求超时30秒，工作流查询可能耗时较高

    async def get_workflows_batch(
        self,
        workflow_ids: List[str],
        project_id: str
    ) -> List[WorkflowData]:
        """
        Retrieve multiple workflows by their IDs from the Workflow service.
        # 批量获取工作流元数据，调用 GET /v1/workflows/batch
        # 注意：接口为GET请求，workflow_ids放在query参数；该接口直接返回存在的工作流数组，**不会返回不存在的ID**

        Args:
            workflow_ids: List of workflow ID strings 待查询的工作流ID列表
            project_id: Project ID 项目ID，租户隔离，Workflow服务按project_id做数据隔离

        Returns:
            List of WorkflowData 仅返回真实存在的工作流；传入ID部分不存在时，返回结果会比入参数量少
        """
        # 边界处理：空ID列表直接返回空数组，不发起网络请求
        if not workflow_ids:
            return []

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # 调试打印：生产环境建议移除，避免日志泄露业务参数
            print(f"Getting workflows from {self.base_url}/v1/workflows/batch")
            print(f"Project ID: {project_id}")
            print(f"Workflow IDs: {workflow_ids}")
            try:
                # GET请求，project_id、workflow_ids全部放在URL query参数
                response = await client.get(
                    f"{self.base_url}/v1/workflows/batch",
                    params={
                        "project_id": project_id,
                        "workflow_ids": workflow_ids
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    # API直接返回工作流对象数组，逐个解析为Pydantic模型返回
                    return [WorkflowData(**item) for item in data]
                elif response.status_code == 422:
                    # 请求参数校验失败，把远端detail封装到业务ValidationError
                    error_data = response.json()
                    raise ValidationError(
                        f"Invalid workflow IDs: {error_data.get('detail', 'Unknown validation error')}",
                        "workflows",
                        {"status_code": response.status_code, "detail": error_data}
                    )
                else:
                    # 其余状态码抛出HTTPStatusError，被下方异常捕获
                    response.raise_for_status()
                    return [] # raise_for_status会抛异常，本行理论不可达

            except httpx.RequestError as e:
                # 网络异常：超时、DNS、连接失败，包装为NotFoundError（服务不可用）
                raise NotFoundError(
                    "Workflow Service",
                    f"Unable to connect to Workflow service: {str(e)}"
                )
            except httpx.HTTPStatusError as e:
                # HTTP状态码异常，统一包装为参数校验异常
                raise ValidationError(
                    f"Workflow service error: {e.response.status_code}",
                    "workflows",
                    {"status_code": e.response.status_code}
                )

    async def validate_workflows_exist(
        self,
        workflow_ids: List[str],
        project_id: str
    ) -> None:
        """
        Validate that workflows exist in the Workflow service.
        # 校验一批工作流ID是否全部存在，用于Agent绑定工作流时做合法性校验
        # 原理：拿返回结果里的id集合，和入参做差集，差集即为缺失ID，有缺失直接抛NotFoundError

        Args:
            workflow_ids: List of workflow ID strings to validate
            project_id: Project ID

        Raises:
            NotFoundError: If any workflow is not found 任意一个ID不存在抛出异常
            ValidationError: If validation fails 网络/接口参数错误抛出校验异常
        """
        # 空列表无需校验直接返回
        if not workflow_ids:
            return

        workflows = await self.get_workflows_batch(workflow_ids, project_id)
        # 提取查询到的全部工作流ID，存入集合用于快速比对
        found_ids = {w.id for w in workflows}
        # 集合差集：入参ID - 查询到的ID = 找不到的工作流ID
        missing_ids = set(workflow_ids) - found_ids

        if missing_ids:
            raise NotFoundError(
                "Workflow",
                f"Workflows not found: {', '.join(missing_ids)}"
            )


# 全局单例客户端实例，业务代码直接导入 workflow_service_client 使用
workflow_service_client = WorkflowServiceClient()