"""Application configuration using Pydantic Settings."""

from typing import List, Union, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.runtime.supervisor.config import SupervisorRuntimeSettings
from app.runtime.tools.config import ToolsRuntimeSettings

class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database Configuration
    # 数据库配置
    database_url: str = Field(
        default="sqlite+aiosqlite:///./tgo_ai_service.db",
        description="Database URL (async driver)",
    )
    database_pool_size: int = Field(
        default=20, description="Database connection pool size"
    )
    database_max_overflow: int = Field(
        default=30, description="Database connection pool max overflow"
    )
    # database_pool_timeout 数据库连接池超时时间，单位为秒。这个参数用于控制数据库连接在等待获取连接时的最长等待时间。如果在指定的超时时间内无法获取到可用的数据库连接，操作将会失败并抛出异常。设置合理的超时时间可以帮助应用程序在高负载或数据库响应缓慢时更好地处理连接请求，避免长时间阻塞。
    database_pool_timeout: int = Field(
        default=30, description="Database connection pool timeout in seconds"
    )
    # database_pool_recycle 数据库连接池回收时间，单位为秒。这个参数用于控制数据库连接在被回收之前可以保持活动状态的最长时间。设置合理的回收时间可以帮助管理数据库连接的生命周期，避免长时间闲置的连接占用资源，同时也可以防止连接过期或失效。
    database_pool_recycle: int = Field(
        default=3600, description="Database connection pool recycle time in seconds"
    )

    # Application Configuration
    # 应用程序配置
    # scret_key 用于JWT令牌签名的密钥。这个密钥用于生成和验证JWT令牌，确保令牌的完整性和安全性。在生产环境中，应使用强随机生成的密钥，并妥善保管，避免泄露。
    secret_key: str = Field(
        default="your-super-secret-key-change-this-in-production",
        description="Secret key for JWT token signing",
    )
    # api_key_prefix API密钥的前缀。这个前缀用于标识和区分不同类型的API密钥，便于管理和验证。在生成和使用API密钥时，可以根据前缀来确定其用途或权限范围。
    api_key_prefix: str = Field(
        default="ak_", description="Prefix for API keys"
    )
    # algorithm JWT算法。指定用于签名和验证JWT令牌的算法类型，例如HS256、RS256等。选择合适的算法可以确保令牌的安全性和性能。
    algorithm: str = Field(default="HS256", description="JWT algorithm")
    # access_token_expire_minutes JWT令牌过期时间，单位为分钟。这个参数用于控制生成的JWT令牌的有效期，超过指定时间后令牌将失效，需要重新获取新的令牌。设置合理的过期时间可以提高安全性，防止令牌被长期滥用。
    access_token_expire_minutes: int = Field(
        default=30, description="JWT token expiration time in minutes"
    )

    # RAG Service Configuration
    # RAG服务配置
    rag_service_url: str = Field(
        default="http://localhost:8085",
        description="Base URL for the RAG service"
    )


    # MCP Service Configuration
    # MCP服务配置
    mcp_service_url: str = Field(
        default="http://localhost:8082",
        description="Base URL for the MCP service"
    )

    # Workflow Service Configuration
    # 工作流服务配置
    workflow_service_url: str = Field(
        default="http://localhost:8086",
        description="Base URL for the Workflow service"
    )


    # Agent Runtime Service Configuration
    # 智能体运行时服务配置
    agent_service_url: str = Field(
        default="http://localhost:8083",
        description="Base URL for the agent runtime service",
    )


    # API Service Configuration
    # API服务配置
    api_service_url: str = Field(
        default="http://localhost:8080",
        description="Base URL for the core API service (events ingestion)",
    )
    api_internal_service_url: str = Field(
        default="http://localhost:8001",
        description="Base URL for the core API internal service (no-auth internal endpoints)",
    )

    # Plugin Runtime Configuration
    # 插件运行时配置
    plugin_runtime_url: str = Field(
        default="http://localhost:8090",
        description="Base URL for the plugin runtime service",
    )

    # Store Configuration
    # 商店服务配置
    store_service_url: str = Field(
        default="https://store.example.com",
        description="Base URL for the Store service"
    )
    # store_api_key 商店服务的API密钥。这个密钥用于访问和操作商店服务的API接口，确保请求的合法性和安全性。在生产环境中，应使用强随机生成的密钥，并妥善保管，避免泄露。
    store_api_key: Optional[str] = Field(
        default=None,
        description="API Key for the Store service"
    )

    # Device Control MCP Configuration
    # 设备控制MCP配置
    device_control_mcp_endpoint: str = Field(
        default="http://tgo-device-control:8085/mcp/{device_id}",
        description="Device Control MCP endpoint URL template. {device_id} is replaced at runtime."
    )

    # Skills File Storage Configuration
    # 技能文件存储配置
    skills_base_dir: str = Field(
        default="/data/skills",
        description="Base directory for skill files storage"
    )
    # github_token GitHub令牌。用于技能导入的默认GitHub令牌（可选，增加速率限制）。这个令牌用于访问GitHub API，以便在导入技能时获取相关资源。提供有效的GitHub令牌可以提高API请求的速率限制，避免因频繁请求而被限制访问。
    github_token: Optional[str] = Field(
        default=None,
        description="Default GitHub token for skill import (optional, increases rate limit)"
    )

    # Server Configuration
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8081, description="Server port")
    reload: bool = Field(default=False, description="Enable auto-reload in development")
    environment: str = Field(default="development", description="Environment name")

    # CORS Configuration
    # CORS配置
    cors_origins: List[str] = Field(
        default=[
            "http://localhost:3000",
            "http://localhost:8080",
            "https://app.tgo-tech.com",
        ],
        description="Allowed CORS origins",
    )
    # cors_allow_credentials 是否允许CORS凭证。这个参数用于控制是否允许跨域请求携带凭证（如Cookies、HTTP认证信息等）。启用此选项可以在跨域请求中传递用户身份信息，但也需要确保安全性，避免潜在的跨站请求伪造（CSRF）攻击。
    cors_allow_credentials: bool = Field(
        default=True, description="Allow CORS credentials"
    )
    # cors_allow_methods 允许的CORS方法列表。这个参数用于指定允许跨域请求使用的HTTP方法，例如GET、POST、PUT、DELETE等。设置合理的允许方法可以确保跨域请求的安全性和功能性，避免不必要的请求被拒绝。
    cors_allow_methods: List[str] = Field(
        default=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        description="Allowed CORS methods",
    )
    # cors_allow_headers 允许的CORS请求头列表。这个参数用于指定允许跨域请求携带的HTTP请求头，例如Content-Type、Authorization等。设置合理的允许请求头可以确保跨域请求的安全性和功能性，避免不必要的请求被拒绝。
    cors_allow_headers: List[str] = Field(
        default=["*"], description="Allowed CORS headers"
    )

    # Logging Configuration
    # 日志配置
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(default="json", description="Log format (json or text)")

    # Rate Limiting
    # 速率限制配置
    rate_limit_enabled: bool = Field(
        default=True, description="Enable rate limiting"
    )
    # rate_limit_requests_per_minute 每分钟的请求速率限制。这个参数用于控制每个客户端在一分钟内允许的最大请求次数，以防止滥用和过载。启用速率限制可以提高服务的稳定性和安全性，确保公平使用资源。
    rate_limit_requests_per_minute: int = Field(
        default=100, description="Rate limit requests per minute"
    )

    # Feature Flags
    # 功能开关配置
    health_check_enabled: bool = Field(
        default=True, description="Enable health check endpoint"
    )
    # metrics_enabled 是否启用指标收集。这个参数用于控制是否启用应用程序的指标收集功能，以便监控性能、使用情况和健康状态。启用指标收集可以帮助开发和运维团队更好地了解系统运行状况，及时发现和解决问题。
    metrics_enabled: bool = Field(
        default=True, description="Enable metrics collection"
    )
    # metrics_path 指标端点路径。这个参数用于指定应用程序暴露指标数据的HTTP端点路径，通常用于与监控系统（如Prometheus）集成。通过访问该端点，可以获取应用程序的实时指标数据，用于性能分析和监控。
    metrics_path: str = Field(default="/metrics", description="Metrics endpoint path")
    # docs_enabled 是否启用API文档。这个参数用于控制是否启用应用程序的API文档生成功能，以便开发者和用户了解和使用API接口。启用API文档可以提高开发效率和用户体验，方便快速集成和调试。
    docs_enabled: bool = Field(
        default=True, description="Enable API documentation"
    )
    # redoc_enabled 是否启用ReDoc文档。这个参数用于控制是否启用ReDoc生成的API文档界面，提供更友好的用户体验和交互方式。启用ReDoc文档可以帮助开发者更直观地浏览和测试API接口，提高开发效率。
    redoc_enabled: bool = Field(
        default=True, description="Enable ReDoc documentation"
    )

    # Embedding sync retry scheduler configuration
    # embedding_sync_retry_scheduler 配置嵌入同步重试调度器。这个配置用于控制嵌入数据同步过程中的重试机制，以确保在网络或服务不稳定时能够自动重试同步操作，提高数据一致性和可靠性。
    embedding_sync_retry_enabled: bool = Field(
        default=True, description="Enable periodic retry for embedding config sync"
    )
    # embedding_sync_retry_interval_seconds 嵌入同步重试间隔时间（秒）。这个参数用于指定在嵌入数据同步失败后，系统等待多长时间再进行下一次重试操作。合理设置重试间隔可以平衡系统负载和数据同步的及时性。
    embedding_sync_retry_interval_seconds: int = Field(
        default=60, description="Interval in seconds between retry runs"
    )
    # embedding_sync_retry_max_attempts 嵌入同步最大重试次数。这个参数用于指定在嵌入数据同步失败后，系统最多尝试重试的次数。如果超过最大重试次数仍然失败，系统将停止重试并记录错误。合理设置最大重试次数可以防止无限循环重试，保护系统资源。
    embedding_sync_retry_max_attempts: int = Field(
        default=10, description="Maximum total retry attempts before giving up"
    )
    # embedding_sync_retry_stale_pending_minutes 嵌入同步过期待处理时间（分钟）。这个参数用于指定在嵌入数据同步过程中，如果某些记录长时间处于“待处理”状态，系统将认为这些记录已经过期并进行相应处理。合理设置过期时间可以确保数据同步的及时性和准确性。
    embedding_sync_retry_stale_pending_minutes: int = Field(
        default=10, description="Consider 'pending' records stale after this many minutes"
    )

    # Runtime configuration
    # Note: These nested settings will be loaded from environment variables
    # with the appropriate prefixes (SUPERVISOR_RUNTIME__ and TOOLS_RUNTIME__)
    # 运行时配置
    # 注意：这些嵌套设置将从环境变量中加载，使用适当的前缀（SUPERVISOR_RUNTIME__ 和 TOOLS_RUNTIME__）。
    # sypervisor_runtime 主管运行时配置。这个配置用于管理和控制应用程序的主管进程运行时行为，包括任务调度、资源管理和监控等功能。
    # 通过环境变量加载，可以灵活调整运行时参数以适应不同的部署环境。
    # tools_runtime 工具运行时配置。这个配置用于管理和控制应用程序中的各种工具和插件的运行时行为，包括功能启用、参数设置和资源分配等。
    # 通过环境变量加载，可以根据实际需求灵活调整工具的运行时参数，提高系统
    supervisor_runtime: SupervisorRuntimeSettings = Field(
        default_factory=lambda: SupervisorRuntimeSettings(_env_file=".env"),
        description="Supervisor运行时配置",
    )
    tools_runtime: ToolsRuntimeSettings = Field(
        default_factory=lambda: ToolsRuntimeSettings(_env_file=".env"),
        description="工具智能体运行时配置",
    )

    # Testing Configuration
    # 测试配置
    test_database_url: str = Field(
        default="postgresql+asyncpg://postgres:password@localhost:5432/tgo_ai_service_test",
        description="Test database URL"
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    # parse_cors_origins 解析CORS来源。这个方法用于在设置CORS配置时，将输入的字符串或列表格式的来源进行解析和标准化处理，确保CORS配置的正确性和一致性。
    def parse_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        """Parse CORS origins from string or list."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    @field_validator("cors_allow_methods", mode="before")
    @classmethod
    # parse_cors_methods 解析CORS方法。这个方法用于在设置CORS配置时，将输入的字符串或列表格式的方法进行解析和标准化处理，确保CORS配置的正确性和一致性。
    def parse_cors_methods(cls, v: Union[str, List[str]]) -> List[str]:
        """Parse CORS methods from string or list."""
        if isinstance(v, str):
            return [method.strip().upper() for method in v.split(",")]
        return v

    @field_validator("cors_allow_headers", mode="before")
    @classmethod
    # parse_cors_headers 解析CORS头部。这个方法用于在设置CORS配置时，将输入的字符串或列表格式的头部进行解析和标准化处理，确保CORS配置的正确性和一致性。
    def parse_cors_headers(cls, v: Union[str, List[str]]) -> List[str]:
        """Parse CORS headers from string or list."""
        if isinstance(v, str):
            return [header.strip() for header in v.split(",")]
        return v

    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.environment.lower() in ("development", "dev", "local")

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment.lower() in ("production", "prod")

    @property
    def is_testing(self) -> bool:
        """Check if running in testing environment."""
        return self.environment.lower() in ("testing", "test")

    @property
    def database_url_sync(self) -> str:
        """Get synchronous database URL for Alembic."""
        return str(self.database_url).replace("+asyncpg", "")

    def get_database_url(self, *, sync: bool = False) -> str:
        """Get database URL with optional sync mode for migrations."""
        if sync:
            return self.database_url_sync
        return str(self.database_url)


# Global settings instance
settings = Settings()
