
"""
Internal data models for service integration and coordination logic.

本模块定义了 supervisor agent（主管代理）内部使用的数据模型，
用于表示来自外部服务的数据以及协调状态（coordination state）。
这些模型构成了整个 Agent 编排与执行系统的核心数据结构。
"""

from typing import Any, Dict, List, Optional
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, Field
from app.runtime.tools.models import LLMProviderCredentials


class AgentTool(BaseModel):
    """
    代理工具配置模型。

    描述一个 Agent 所绑定的工具（Tool）的完整配置信息，
    包括工具的基本属性、启用状态、权限、MCP 传输细节等。
    一个 Agent 可以绑定多个 AgentTool 实例，每个实例对应一个具体的工具。
    """

    # ==================== 基础字段 ====================
    tool_id: UUID = Field(..., description="工具的唯一标识符（UUID）")
    tool_name: str = Field(..., description="工具名称，用于在日志和 UI 中标识该工具")
    tool_type: str = Field(..., description="工具类型，取值为 MCP 或 FUNCTION")
    enabled: bool = Field(default=True, description="该工具是否对此 Agent 启用。False 时工具被忽略")
    permissions: List[str] = Field(default_factory=list, description="该工具对此 Agent 的权限列表（如 read/write/exec）")
    tool_config: Dict[str, Any] = Field(default_factory=dict, description="Agent 级别的工具配置，会覆盖工具默认配置")

    # ==================== MCP 专用字段 ====================
    # 以下字段仅在 tool_type 为 MCP 时才有意义，FUNCTION 类型工具不使用这些字段

    transport_type: Optional[str] = Field(
        None,
        description="MCP 传输层类型，取值为 http / stdio / sse。决定 Agent 如何与 MCP 服务通信"
    )
    endpoint: Optional[str] = Field(
        None,
        description="MCP 服务的端点地址（URL）或本地命令（stdio 模式下为可执行文件路径）"
    )
    base_config: Dict[str, Any] = Field(
        default_factory=dict,
        description="来自 Tool 模型的基础配置，包含工具的原始 schema 和默认参数"
    )
    tool_source_type: Optional[str] = Field(
        None,
        description="工具来源类型（LOCAL 或 STORE），用于路由决策——决定工具从本地注册表还是远程商店加载"
    )

    @property
    def input_schema(self) -> Dict[str, Any]:
        """
        获取工具的输入参数 Schema。

        优先从 base_config 中提取 inputSchema（OpenAPI 风格）或 input_schema（蛇形命名兼容），
        如果两者都不存在，则返回一个空的 object schema 作为兜底。
        此属性供工具调用时的参数校验和自动补全使用。
        """
        if self.base_config:
            # 兼容 inputSchema（驼峰）和 input_schema（蛇形）两种命名风格
            schema = self.base_config.get("inputSchema") or self.base_config.get("input_schema")
            if schema:
                return schema
        # 兜底：返回空对象 schema
        return {"type": "object", "properties": {}}

    class Config:
        """Pydantic 模型配置：禁止传入模型中未定义的额外字段，防止脏数据"""
        extra = "forbid"


class AgentCollection(BaseModel):
    """
    代理集合访问模型。

    描述一个 Agent 对某个知识库集合（Collection）的访问权限和元信息。
    Collection 是外部知识服务的抽象，Agent 通过此模型获得对特定集合的读取/写入能力。
    """

    id: UUID = Field(..., description="内部关联记录 ID，用于唯一标识此 Agent-Collection 绑定关系")
    collection_id: str = Field(..., description="外部集合的唯一标识符（UUID 字符串）")
    enabled: bool = Field(default=True, description="该集合是否对此 Agent 启用")
    display_name: str = Field(..., description="集合的可读展示名称，用于 UI 显示")
    description: Optional[str] = Field(None, description="集合的详细描述信息")
    collection_metadata: Dict[str, Any] = Field(default_factory=dict, description="集合的附加元数据（如标签、版本等）")

    class Config:
        """禁止传入额外字段"""
        extra = "forbid"


class AgentWorkflow(BaseModel):
    """
    代理工作流访问模型。

    描述一个 Agent 对某个工作流（Workflow）的访问权限。
    Workflow 是外部工作流服务的抽象，Agent 可通过此模型触发或调用已绑定的工作流。
    """

    id: UUID = Field(..., description="内部关联记录 ID")
    workflow_id: str = Field(..., description="外部工作流服务的唯一标识符")
    enabled: bool = Field(default=True, description="该工作流是否对此 Agent 启用")

    class Config:
        """禁止传入额外字段"""
        extra = "forbid"


class Agent(BaseModel):
    """
    AI 代理核心模型。

    描述一个完整的 AI Agent 的全部属性，包括：
    - 基本身份信息（id、name、project_id）
    - 大语言模型配置（model、config）
    - 能力扩展（tools、collections、workflows）
    - 远程代理支持（remote_agent_url、store_agent_id）
    - 运行时元数据（created_at、updated_at）

    这是整个模块中最重要的模型，其他模型大多围绕 Agent 构建。
    """

    # ==================== 身份与归属 ====================
    id: UUID = Field(..., description="Agent 的唯一标识符")
    project_id: Optional[str] = Field(None, description="所属项目的 ID。None 表示该 Agent 不属于任何项目（全局 Agent）")
    name: str = Field(..., description="Agent 的名称，用于用户识别")
    instruction: Optional[str] = Field(None, description="Agent 的系统指令（System Prompt），定义 Agent 的行为准则和角色")

    # ==================== 模型与配置 ====================
    model: str = Field(..., description="底层使用的 LLM 模型名称（如 gpt-4、claude-3 等）")
    config: Dict[str, Any] = Field(default_factory=dict, description="Agent 的运行配置，包括 temperature、max_tokens、是否启用 markdown 等")

    # ==================== 能力扩展 ====================
    tools: List[AgentTool] = Field(default_factory=list, description="该 Agent 绑定的工具列表")
    collections: List[AgentCollection] = Field(default_factory=list, description="该 Agent 可访问的知识集合列表")
    workflows: List[AgentWorkflow] = Field(default_factory=list, description="该 Agent 可调用的工作流列表")

    # ==================== 状态与分类 ====================
    is_default: bool = Field(default=False, description="是否为默认 Agent。系统默认 Agent 会在无明确指定时被选用")
    is_remote_store_agent: bool = Field(default=False, description="是否为远程商店中的 Agent。True 表示该 Agent 的定义来自远程商店")
    remote_agent_url: Optional[str] = Field(None, description="远程 AgentOS 服务器的 URL，当 is_remote_store_agent 为 True 时使用")
    store_agent_id: Optional[str] = Field(None, description="远程商店中该 Agent 的 ID，用于远程调用")
    agent_category: str = Field(default="normal", description="Agent 类别：normal（普通文本 Agent）或 computer_use（需要操控计算机的 Agent）")
    bound_device_id: Optional[str] = Field(None, description="绑定的设备 ID，用于设备控制类 MCP 连接（如远程桌面、机器人控制）")
    skills_enabled: bool = Field(default=True, description="是否启用技能发现（Skill Discovery）。启用后 Agent 可自动发现可用技能")

    # ==================== 时间戳 ====================
    created_at: datetime = Field(..., description="Agent 的创建时间")
    updated_at: datetime = Field(..., description="Agent 的最后更新时间")

    # ==================== 凭据 ====================
    llm_provider_credentials: Optional[LLMProviderCredentials] = Field(
        default=None,
        description="已解析的 LLM 提供商凭据（如 API Key）。在运行时动态解析，不持久化存储"
    )

    def get_capabilities(self) -> List[str]:
        """
        获取 Agent 的能力列表。

        能力来源有两个：
        1. 从已启用的工具（tools）中提取工具名称作为能力
        2. 从系统指令（instruction）中通过关键词匹配推断能力

        返回去重后的能力名称列表。
        此方法常用于 Agent 路由、能力发现和 UI 展示。
        """
        capabilities = []

        # 来源 1：从已启用的工具中提取能力
        for tool in self.tools:
            if tool.enabled:
                capabilities.append(tool.tool_name)

        # 来源 2：从系统指令中通过关键词匹配推断能力
        if self.instruction:
            instruction_lower = self.instruction.lower()
            capability_keywords = [
                "support",   # 技术支持
                "technical",  # 技术类
                "customer",   # 客服类
                "documentation",  # 文档类
                "search",     # 搜索类
                "analysis",   # 分析类
                "coding",     # 编程类
                "writing",    # 写作类
                "translation", # 翻译类
                "math",       # 数学类
            ]
            for keyword in capability_keywords:
                if keyword in instruction_lower:
                    capabilities.append(keyword)

        # 去重后返回
        return list(set(capabilities))

    class Config:
        """禁止传入额外字段"""
        extra = "forbid"


class AgentExecutionRequest(BaseModel):
    """
    Agent 执行请求模型。

    定义向 Agent 服务发起执行请求时所需的全部参数。
    该模型通常由上游协调器（Coordinator）或 API 网关构造并发送。
    """

    message: str = Field(..., description="要发送给 Agent 的用户消息（核心输入）")
    config: Dict[str, Any] = Field(default_factory=dict, description="本次执行覆盖的 Agent 配置（可临时覆盖默认配置）")
    session_id: Optional[str] = Field(None, description="会话 ID，用于多轮对话的上下文追踪")
    user_id: Optional[str] = Field(None, description="请求发起方的用户 ID，用于身份认证和审计")
    enable_memory: bool = Field(False, description="是否启用 Agent 记忆能力。启用后 Agent 可跨轮次保留上下文")

    class Config:
        """禁止传入额外字段"""
        extra = "forbid"


class AgentExecutionResponse(BaseModel):
    """
    Agent 执行响应模型。

    定义 Agent 服务返回的执行结果。包含对话历史、响应内容、工具执行结果和状态信息。
    """

    messages: Optional[List[Dict[str, Any]]] = Field(None, description="对话消息列表（包含用户消息和 Agent 回复）")
    content: Optional[str] = Field(None, description="Agent 的文本回复内容")
    tools: Optional[List[Dict[str, Any]]] = Field(None, description="工具执行结果列表，每个元素包含工具名、输入和输出")
    success: bool = Field(default=True, description="执行是否成功。False 时 error 字段会包含错误信息")
    error: Optional[str] = Field(None, description="执行失败时的错误描述")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="响应元数据（如耗时、模型版本等）")

    class Config:
        """禁止传入额外字段"""
        extra = "forbid"


class AgentExecutionContext(BaseModel):
    """
    Agent 执行上下文模型。

    封装单次 Agent 执行所需的完整运行时上下文。
    这是 supervisor agent 在执行 Agent 之前构建的"一次性"环境对象，
    包含了 Agent 本身、项目信息、用户消息、路由地址等所有必要信息。
    """

    agent: Agent = Field(..., description="本次执行要使用的 Agent 实例（已解析并验证）")
    project_id: str = Field(..., description="所属项目的 ID（从 Agent 或请求中解析得出）")
    message: str = Field(..., description="用户发送的原始消息")
    system_message: Optional[str] = Field(
        None,
        description="可选的系统消息，会追加到 Agent 已存储的系统指令之后，用于运行时动态注入额外指令"
    )
    expected_output: Optional[str] = Field(
        None,
        description="期望的输出格式/内容描述，可用于指导 Agent 的回复风格"
    )
    session_id: Optional[str] = Field(None, description="对话会话 ID，用于多轮对话追踪")
    user_id: Optional[str] = Field(None, description="最终用户的唯一标识符")
    request_id: str = Field(..., description="本次请求的唯一追踪 ID，用于日志和链路追踪")
    timeout: int = Field(..., ge=1, description="执行超时时间（秒），最小值为 1")
    mcp_url: Optional[str] = Field(None, description="MCP 运行时 URL，用于 Agent 与 MCP 服务通信")
    rag_url: Optional[str] = Field(None, description="RAG 运行时 URL，用于 Agent 的知识检索")
    enable_memory: bool = Field(False, description="是否启用对话记忆")
    ui_mode: str = Field("json_render", description="UI 渲染模式，决定 Agent 输出如何在前端展示")

    class Config:
        """禁止传入额外字段"""
        extra = "forbid"


class SubQuestion(BaseModel):
    """
    子问题模型。

    描述从复杂用户问题中拆解出的一个子问题。
    当用户的问题包含多个意图时，系统会将其分解为多个 SubQuestion，
    然后分别分配给不同的 Agent 处理。
    """

    id: str = Field(..., description="子问题的唯一标识符")
    question: str = Field(..., description="拆解后的子问题文本")
    intent: str = Field(..., description="该子问题所对应的具体意图描述")
    priority: int = Field(..., ge=1, le=10, description="优先级，1 为最高优先级，10 为最低")
    requires_context: bool = Field(default=False, description="该子问题是否需要依赖其他子问题的上下文。True 表示有依赖关系")
    context_dependencies: List[str] = Field(default_factory=list, description="依赖的子问题 ID 列表。如果 requires_context 为 True，此处列出所依赖的子问题 ID")

    class Config:
        """禁止传入额外字段"""
        extra = "forbid"


class QuestionDecomposition(BaseModel):
    """
    问题分解结果模型。

    封装 LLM 对复杂用户问题进行意图拆解后的完整结果。
    包括原始问题、复杂度评分、拆解后的子问题列表以及拆解推理过程。
    """

    original_question: str = Field(..., description="用户的原始问题")
    is_complex: bool = Field(..., description="该问题是否为复杂问题（包含多个意图）。False 时可直接路由给单个 Agent")
    complexity_score: float = Field(..., ge=0.0, le=1.0, description="复杂度评分，0 表示最简单，1 表示最复杂。用于决策是否需要拆解")
    sub_questions: List[SubQuestion] = Field(default_factory=list, description="拆解后的子问题列表")
    decomposition_reasoning: str = Field(..., description="拆解推理过程的自然语言描述，记录 LLM 的拆解逻辑")

    class Config:
        """禁止传入额外字段"""
        extra = "forbid"


class AgentAssignment(BaseModel):
    """
    Agent 分配模型。

    描述将一个子问题（SubQuestion）分配给某个 Agent 的结果。
    包含分配原因和置信度评分，用于后续的协调和审计。
    """

    sub_question_id: str = Field(..., description="被分配的子问题 ID")
    assigned_agent: Agent = Field(..., description="被分配到的 Agent 实例")
    assignment_reasoning: str = Field(..., description="分配决策的推理过程，说明为什么选择该 Agent")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="分配决策的置信度评分，0 表示完全不确信，1 表示非常确信")

    class Config:
        """禁止传入额外字段"""
        extra = "forbid"


class AgentSelection(BaseModel):
    """
    Agent 选择结果模型。

    封装 supervisor agent 完成 Agent 选择后的全部结果。
    这是多 Agent 协调流程的核心输出，包含选中的 Agent 列表、选择策略、
    问题分解结果、子问题分配以及协调规划结果。
    """

    selected_agents: List[Agent] = Field(..., description="被选中用于执行的所有 Agent 列表")
    selection_strategy: str = Field(..., description="本次选择所使用的策略名称（如 'priority_based'、'round_robin' 等）")
    selection_reasoning: str = Field(..., description="选择决策的推理过程")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="选择决策的整体置信度评分")

    # ==================== 多意图增强字段 ====================

    question_decomposition: Optional[QuestionDecomposition] = Field(
        None,
        description="问题分解结果。当 is_complex=True 时，包含完整的拆解信息"
    )
    agent_assignments: List[AgentAssignment] = Field(
        default_factory=list,
        description="子问题到 Agent 的具体分配映射。每个元素描述一个子问题被分配给了哪个 Agent"
    )

    # ==================== 协调规划结果 ====================
    coordination_result: Optional[Any] = Field(
        None,
        description="详细的协调规划结果（来自 LLM 的高级编排计划）。"
                   "包含 Agent 之间的执行顺序、依赖关系、数据传递方式等高级协调策略"
    )

    class Config:
        """禁止传入额外字段"""
        extra = "forbid"