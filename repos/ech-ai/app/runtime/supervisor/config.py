"""Supervisor runtime configuration settings."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 定义 SupervisorRuntimeSettings 类，用于管理 Supervisor 运行时的配置
class QueryAnalysisSettings(BaseSettings):
    """LLM settings for query analysis."""
    # LLM 设置为了查询分析，使用 Pydantic 的 BaseSettings 进行配置管理
    # model_config 定义了环境变量的前缀、嵌套分隔符、大小写敏感性和额外字段的处理方式
    # env_prefix="SUPERVISOR_RUNTIME__COORDINATION__QUERY_ANALYSIS__",
    # env_nested_delimiter="__" 表示嵌套的环境变量使用双下划线分隔
    # case_sensitive=False 表示环境变量不区分大小写
    # extra="ignore" 表示忽略未定义的额外字段
    model_config = SettingsConfigDict(
        env_prefix="SUPERVISOR_RUNTIME__COORDINATION__QUERY_ANALYSIS__",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    model_name: str = Field(default="anthropic:claude-3-sonnet-20240229")
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2000, ge=100)
    timeout: int = Field(default=30, ge=1)
    max_retries: int = Field(default=3, ge=0)
    retry_delay: float = Field(default=1.0, ge=0.1)
    system_prompt: str = Field(
        default="You are an expert AI coordination system. Always respond with valid JSON only."
    )
    prompt_template: str = Field(default="unified_coordination")
    validate_response: bool = True
    require_all_fields: bool = True
    confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)

# 工作流规划设置类，用于定义工作流规划相关的配置
class WorkflowPlanningSettings(BaseSettings):
    """Workflow planning configuration."""

    model_config = SettingsConfigDict(
        env_prefix="SUPERVISOR_RUNTIME__COORDINATION__WORKFLOW_PLANNING__",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )
    # 定义工作流规划相关的配置参数，包括最大并行代理数、最大顺序深度、最大层级数、默认超时时间、优化启用、并行优先、负载均衡、最大依赖深度、循环检测和冲突解决等
    max_parallel_agents: int = Field(default=10, ge=1) # 意义：同一时间最多同时跑多少个子 Agent 任务。
    max_sequential_depth: int = Field(default=5, ge=1)  # 意义：串行链式任务最大嵌套层数。A 做完→B 做完→C 做完，这条链条最多走 5 层。
    max_hierarchical_levels: int = Field(default=3, ge=1) # 意义：任务分层拆解的层级上限，任务拆解的树结构层级，可以包含并行 + 串行。限制任务树不要拆得过于细碎。
    default_timeout: int = Field(default=300, ge=1) # 意义：默认的任务超时时间，单位秒。超过这个时间，任务会被认为失败。
    enable_optimization: bool = True # 意义：是否启用工作流优化策略，优化任务执行顺序和资源利用。
    prefer_parallel: bool = True # 意义：是否优先选择并行执行任务，提升整体执行效率。
    balance_load: bool = True   # 意义：是否启用负载均衡策略，合理分配任务到不同的 Agent，避免某些 Agent 过载。
    max_dependency_depth: int = Field(default=10, ge=1) # 意义：任务依赖关系的最大深度，防止过深的依赖链导致执行复杂度过高。
    detect_cycles: bool = True # 意义：是否启用循环依赖检测，防止任务之间形成死循环。
    resolve_conflicts: bool = True # 意义：是否启用冲突解决机制，处理任务之间的资源或数据冲突，确保任务顺利执行。

# 执行引擎设置类，用于定义执行引擎相关的配置
class ExecutionSettings(BaseSettings):
    """Execution engine configuration."""

    model_config = SettingsConfigDict(
        env_prefix="SUPERVISOR_RUNTIME__COORDINATION__EXECUTION__",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )
    # 定义执行引擎相关的配置参数，包括默认超时时间、代理超时时间、最大并发执行数、最大重试次数、重试延迟、指数退避、进度监控启用、执行详情日志记录、指标收集、内存限制和 CPU 限制等
    default_timeout: int = Field(default=300, ge=1)
    agent_timeout: int = Field(default=60, ge=1)
    max_concurrent_executions: int = Field(default=20, ge=1)
    max_retries: int = Field(default=2, ge=0)
    retry_delay: float = Field(default=2.0, ge=0.1)
    exponential_backoff: bool = True
    enable_progress_monitoring: bool = True
    log_execution_details: bool = True
    collect_metrics: bool = True
    memory_limit_mb: int = Field(default=1024, ge=128)
    cpu_limit_percent: float = Field(default=80.0, ge=0.0, le=100.0)

# 结果整合设置类，用于定义结果整合相关的配置
class ResultConsolidationSettings(BaseSettings):
    """LLM settings for result consolidation."""

    model_config = SettingsConfigDict(
        env_prefix="SUPERVISOR_RUNTIME__COORDINATION__RESULT_CONSOLIDATION__",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )
    # 定义结果整合相关的配置参数，包括模型名称、温度、最大令牌数、超时时间、默认策略、冲突检测启用、共识构建启用、置信度阈值、共识阈值、最大冲突数、最大响应长度、是否包含来源和是否包含置信度等
    model_name: str = Field(default="anthropic:claude-3-sonnet-20240229")
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    max_tokens: int = Field(default=3000, ge=100)
    timeout: int = Field(default=45, ge=1)
    default_strategy: str = Field(default="synthesis")
    enable_conflict_detection: bool = True
    enable_consensus_building: bool = True
    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    consensus_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    max_conflicts: int = Field(default=5, ge=0)
    max_response_length: int = Field(default=2000, ge=100)
    include_sources: bool = True
    include_confidence: bool = True

# 协调设置类，用于定义高层次的协调配置
class CoordinationSettings(BaseSettings):
    """High-level coordination configuration surface."""

    model_config = SettingsConfigDict(
        env_prefix="SUPERVISOR_RUNTIME__COORDINATION__",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )
    # 定义高层次的协调配置参数，包括最大并发代理数、默认超时时间、是否启用共识、共识阈值、查询分析设置、工作流规划设置、执行设置和结果整合设置等
    max_concurrent_agents: int = Field(default=5, ge=1)
    default_timeout: int = Field(default=60, ge=5)
    enable_consensus: bool = False
    consensus_threshold: float = Field(default=0.7, ge=0.5, le=1.0)

    query_analysis: QueryAnalysisSettings = Field(default_factory=QueryAnalysisSettings)
    workflow_planning: WorkflowPlanningSettings = Field(default_factory=WorkflowPlanningSettings)
    execution: ExecutionSettings = Field(default_factory=ExecutionSettings)
    result_consolidation: ResultConsolidationSettings = Field(default_factory=ResultConsolidationSettings)
    # 定义其他配置参数，包括是否启用缓存、缓存的 TTL、是否启用指标、日志级别、最大并发请求数、请求超时时间和是否启用速率限制等
    enable_caching: bool = True
    cache_ttl: int = Field(default=3600, ge=1)
    enable_metrics: bool = True
    log_level: str = Field(default="INFO")
    max_concurrent_requests: int = Field(default=50, ge=1)
    request_timeout: int = Field(default=600, ge=1)
    enable_rate_limiting: bool = True

# 定义 SupervisorRuntimeSettings 类，用于管理 Supervisor 运行时的配置
class SupervisorRuntimeSettings(BaseSettings):
    """Supervisor runtime configuration entry point."""

    model_config = SettingsConfigDict(
        env_prefix="SUPERVISOR_RUNTIME__",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )
    # 定义 Supervisor 运行时的配置参数，包括协调设置、是否启用流式处理等
    coordination: CoordinationSettings = Field(default_factory=CoordinationSettings)
    enable_streaming: bool = True
