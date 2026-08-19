"""Application configuration using Pydantic Settings."""
# 模块说明：基于 Pydantic Settings 实现的应用配置管理，支持从 .env 文件/环境变量加载配置


# 导入类型注解：List 列表类型，Optional 可选类型（可以为 None）
from typing import List, Optional

# 从 pydantic 导入字段定义工具 Field，以及 PostgreSQL DSN 类型校验器 PostgresDsn
from pydantic import Field, PostgresDsn
# 从 pydantic_settings 导入配置基类与配置字典模型
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""
    # 应用全局配置类，继承自 BaseSettings，自动具备环境变量加载、类型校验能力

    # ========== 配置加载规则 ==========
    model_config = SettingsConfigDict(
        env_file=".env",                # 指定从项目根目录的 .env 文件读取环境变量
        env_file_encoding="utf-8",      # .env 文件的编码格式为 utf-8
        case_sensitive=True,            # 环境变量名称严格区分大小写（本配置全部采用大写下划线风格）
        extra="ignore",                 # 忽略 .env/环境变量中未在本类定义的多余字段，不抛出异常
    )

    # ========== 项目基础信息 ==========
    # Project Information
    PROJECT_NAME: str = Field(
        default="TGO-Tech API Service", # 默认项目名称
        description="Name of the project"
    )
    PROJECT_DESCRIPTION: str = Field(
        default="Core Business Logic Microservice", # 默认项目描述
        description="Description of the project"
    )
    PROJECT_VERSION: str = Field(
        default="0.1.0",                # 默认项目版本号
        description="Version of the project"
    )

    # ========== API 路由配置 ==========
    # API Configuration
    API_V1_STR: str = Field(
        default="/v1",                  # v1 版本接口的统一路由前缀
        description="API v1 prefix"
    )
    API_BASE_URL: str = Field(
        default="http://localhost:8000",# 服务对外暴露的根地址，用于构造回调链接、跳转链接等
        description="Public-facing base URL for this TGO API service (used to construct callback URLs)"
    )

    # ========== 安全与鉴权配置 ==========
    # Security
    SECRET_KEY: str = Field(
        ...,                            # ... 表示该字段必填，无默认值，必须从环境变量传入
        description="Secret key for JWT token generation",
        min_length=32                   # 校验：密钥长度至少 32 位，保障加密强度
    )
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=30,                     # Access Token 有效期，默认 30 分钟
        description="Access token expiration time in minutes",
        gt=0                            # 校验：数值必须大于 0
    )
    ALGORITHM: str = Field(
        default="HS256",                # JWT 签名使用的算法，默认 HS256
        description="JWT algorithm"
    )

    # ========== 数据库连接配置 ==========
    # Database
    DATABASE_URL: PostgresDsn = Field(
        ...,                            # 必填项：PostgreSQL 数据库连接地址
        description="PostgreSQL database URL"
    )
    DATABASE_POOL_SIZE: int = Field(
        default=10,                     # 数据库连接池常驻连接数
        description="Database connection pool size",
        gt=0
    )
    DATABASE_MAX_OVERFLOW: int = Field(
        default=20,                     # 连接池峰值可额外创建的连接数（总最大连接数 = pool_size + max_overflow）
        description="Database connection pool max overflow",
        gt=0
    )
    DATABASE_POOL_TIMEOUT: int = Field(
        default=30,                     # 从连接池获取连接的超时时间，单位秒
        description="Database connection pool timeout in seconds",
        gt=0
    )
    DATABASE_POOL_RECYCLE: int = Field(
        default=3600,                   # 连接回收周期，单位秒；超过该时长的连接会被销毁重建，避免连接失效
        description="Database connection pool recycle time in seconds",
        gt=0
    )

    # ========== 跨域 CORS 配置（对外接口） ==========
    # CORS
    BACKEND_CORS_ORIGINS: List[str] = Field(
        # default_factory：用工厂函数生成可变默认值，避免 Python 可变默认值的共享陷阱
        default_factory=lambda: [
            "*",                        # 默认允许所有来源跨域访问（生产环境建议收紧）
        ],
        description="List of allowed CORS origins"
    )

    # ========== 内部服务端口配置 ==========
    # Internal Service Configuration
    INTERNAL_SERVICE_HOST: str = Field(
        default="127.0.0.1",            # 内部服务监听地址；127.0.0.1 仅本地可访问，Docker 部署用 0.0.0.0
        description="Host for internal services (127.0.0.1 for localhost only, 0.0.0.0 for all interfaces in Docker)"
    )
    INTERNAL_SERVICE_PORT: int = Field(
        default=8001,                   # 内部服务端口，该端口接口不做鉴权，仅限内网访问
        description="Port for internal services (no authentication required)",
        gt=0
    )
    INTERNAL_CORS_ORIGINS: List[str] = Field(
        default_factory=lambda: [
            "*",
        ],
        description="List of allowed CORS origins for internal services"
    )

    # ========== RAG 检索增强服务配置 ==========
    # RAG Service settings
    RAG_SERVICE_URL: str = Field(
        default="http://localhost:8001",# RAG 服务的访问地址
        description="URL of the RAG service"
    )
    RAG_SERVICE_TIMEOUT: int = Field(
        default=30,                     # RAG 服务请求超时时间，单位秒
        description="Timeout for RAG service requests in seconds"
    )
    RAG_SERVICE_API_KEY: Optional[str] = Field(
        default=None,                   # 可选：RAG 服务鉴权密钥，不需要则留空
        description="API key for RAG service authentication (if required)"
    )

    # ========== AI 大模型服务配置 ==========
    # AI Service settings
    AI_SERVICE_URL: str = Field(
        default="http://localhost:8002",# AI 推理服务的访问地址
        description="URL of the AI service"
    )
    AI_SERVICE_TIMEOUT: int = Field(
        default=120,                    # AI 服务超时较长，适配大模型长生成场景
        description="Timeout for AI service requests in seconds"
    )
    AI_SERVICE_API_KEY: Optional[str] = Field(
        default=None,
        description="API key for AI service authentication (if required)"
    )

    # ========== 工作流引擎服务配置 ==========
    # Workflow Service settings
    WORKFLOW_SERVICE_URL: str = Field(
        default="http://localhost:8004",# 工作流编排服务地址
        description="URL of the Workflow service"
    )
    WORKFLOW_SERVICE_TIMEOUT: int = Field(
        default=60,
        description="Timeout for Workflow service requests in seconds"
    )
    WORKFLOW_SERVICE_API_KEY: Optional[str] = Field(
        default=None,
        description="API key for Workflow service authentication (if required)"
    )

    # ========== AI 提供商数据同步配置 ==========
    # AI Provider sync settings
    AI_PROVIDER_SYNC_RETRY_COUNT: int = Field(
        default=3,                      # 同步失败的重试次数（不含首次请求）
        description="Retry count for AIProvider sync failures (excludes initial attempt)",
        ge=0,                           # 校验：大于等于 0
    )
    AI_PROVIDER_SYNC_RETRY_DELAY: int = Field(
        default=2,                      # 指数退避初始延迟，单位秒；重试间隔按 2,4,8... 递增
        description="Initial delay in seconds for exponential backoff (2,4,8,...)",
        gt=0,
    )
    AI_PROVIDER_SYNC_INTERVAL_MINUTES: int = Field(
        default=5,                      # 全量同步的周期，每 5 分钟执行一次
        description="Periodic sync interval in minutes",
        gt=0,
    )
    AI_PROVIDER_SYNC_ENABLED: bool = Field(
        default=True,                   # 是否开启 AI 提供商后台同步任务
        description="Enable periodic background sync for AIProviders",
    )

    # ========== 项目 AI 配置同步配置 ==========
    # Project AI Config sync settings
    PROJECT_AI_CONFIG_SYNC_RETRY_COUNT: int = Field(
        default=3,
        description="Retry count for ProjectAIConfig sync failures (excludes initial attempt)",
        ge=0,
    )
    PROJECT_AI_CONFIG_SYNC_RETRY_DELAY: int = Field(
        default=2,
        description="Initial delay in seconds for ProjectAIConfig exponential backoff (2,4,8,...)",
        gt=0,
    )
    PROJECT_AI_CONFIG_SYNC_INTERVAL_MINUTES: int = Field(
        default=5,
        description="Periodic sync interval in minutes for ProjectAIConfig",
        gt=0,
    )
    PROJECT_AI_CONFIG_SYNC_ENABLED: bool = Field(
        default=True,
        description="Enable periodic background sync for ProjectAIConfig",
    )

    # ========== 任务队列处理配置 ==========
    # Queue Processing settings (event-driven with fallback)
    QUEUE_DEFAULT_TIMEOUT_MINUTES: int = Field(
        default=60*24,                  # 队列任务默认超时时间 24 小时；单项目未配置时生效
        description="Default queue wait timeout in minutes if not configured per project",
        gt=0,
    )
    QUEUE_CLEANUP_INTERVAL_SECONDS: int = Field(
        default=300,                    # 过期队列条目清理周期，默认 5 分钟
        description="Interval in seconds for expired queue entries cleanup (default 5 minutes)",
        gt=0,
    )
    QUEUE_FALLBACK_INTERVAL_SECONDS: int = Field(
        default=120,                    # 兜底轮询周期；事件驱动失效时，每 2 分钟扫描一次遗漏任务
        description="Interval in seconds for fallback queue processing (default 2 minutes)",
        gt=0,
    )
    QUEUE_FALLBACK_ENABLED: bool = Field(
        default=True,                   # 是否开启兜底轮询处理
        description="Enable fallback periodic processing for missed queue entries",
    )
    QUEUE_PROCESS_BATCH_SIZE: int = Field(
        default=50,                     # 每批最多处理的队列任务数量
        description="Maximum number of queue entries to process per batch",
        gt=0,
    )
    QUEUE_PROCESS_MAX_WORKERS: int = Field(
        default=5,                      # 队列处理的最大并发 worker 数
        description="Maximum number of concurrent workers for queue processing",
        gt=0,
    )

    # ========== 会话超时管理配置 ==========
    # Session timeout settings
    SESSION_TIMEOUT_CHECK_ENABLED: bool = Field(
        default=True,                   # 是否开启会话超时定时检查
        description="Enable periodic check for timed-out sessions",
    )
    SESSION_TIMEOUT_CHECK_INTERVAL_SECONDS: int = Field(
        default=300,                    # 超时检查周期，默认 5 分钟
        description="Interval in seconds between session timeout checks (default 5 minutes)",
        gt=0,
    )
    SESSION_DEFAULT_TIMEOUT_HOURS: int = Field(
        default=48,                     # 默认会话超时时长 48 小时；规则未配置时生效
        description="Default session timeout in hours if not configured in VisitorAssignmentRule",
        gt=0,
    )
    SESSION_TIMEOUT_BATCH_SIZE: int = Field(
        default=50,                     # 每批处理的超时会话数量
        description="Number of timed-out sessions to process per batch",
        gt=0,
    )

    # ========== 访客分配规则默认值 ==========
    # Visitor Assignment Rule defaults
    ASSIGNMENT_RULE_DEFAULT_TIMEZONE: str = Field(
        default="Asia/Shanghai",        # 默认时区：上海
        description="Default timezone for visitor assignment rules",
    )
    ASSIGNMENT_RULE_DEFAULT_WEEKDAYS: str = Field(
        default="1,2,3,4,5,6,7",        # 默认服务日：周一到周日全周；1=周一，7=周日
        description="Default service weekdays (comma-separated, 1=Monday to 7=Sunday)",
    )
    ASSIGNMENT_RULE_DEFAULT_START_TIME: str = Field(
        default="00:00",                # 默认服务开始时间
        description="Default service start time (HH:MM format)",
    )
    ASSIGNMENT_RULE_DEFAULT_END_TIME: str = Field(
        default="23:59",                # 默认服务结束时间
        description="Default service end time (HH:MM format, 23:59 for end of day)",
    )
    ASSIGNMENT_RULE_DEFAULT_MAX_CONCURRENT_CHATS: int = Field(
        default=50,                     # 单客服默认最大并发会话数
        description="Default maximum concurrent chats per staff",
        gt=0,
    )
    ASSIGNMENT_RULE_DEFAULT_AUTO_CLOSE_HOURS: int = Field(
        default=48,                     # 会话默认自动关闭时长 48 小时
        description="Default auto-close hours for sessions",
        gt=0,
    )

    # ========== 平台服务配置 ==========
    # Platform Service settings (TGO Platform Service)
    PLATFORM_SERVICE_URL: str = Field(
        default="http://localhost:8003",# 平台管理服务地址
        description="URL of the TGO Platform Service",
    )
    PLATFORM_SERVICE_TIMEOUT: int = Field(
        default=15,
        description="Timeout for Platform Service requests in seconds",
        gt=0,
    )
    PLATFORM_SERVICE_API_KEY: Optional[str] = Field(
        default=None,
        description="API key for Platform Service authentication (if required)",
    )

    # ========== 平台同步监控配置 ==========
    # Platform sync monitor settings
    PLATFORM_SYNC_RETRY_INTERVAL_SECONDS: int = Field(
        default=15,                     # 平台同步失败重试基础间隔，指数退避
        description="Base retry interval for platform sync (exponential backoff)",
        gt=1,
    )
    PLATFORM_SYNC_BATCH_LIMIT: int = Field(
        default=50,                     # 每次重试循环最多扫描的平台数量
        description="Max number of platforms to scan per retry cycle",
        gt=0,
    )

    # ========== 门店服务配置 ==========
    # Store settings
    STORE_SERVICE_URL: str = Field(
        default="http://localhost:8095",# 门店服务地址
        description="URL of the Store service"
    )
    STORE_TIMEOUT: int = Field(
        default=30,
        description="Timeout for Store service requests in seconds"
    )
    STORE_WEB_URL: str = Field(
        default="http://localhost:3002",# 门店前端页面地址，用于 OAuth 跳转回调
        description="URL of the Store Web frontend (for OAuth redirect)"
    )

    # ========== 悟空即时通讯服务配置 ==========
    # WuKongIM Service settings
    WUKONGIM_SERVICE_URL: str = Field(
        default="http://localhost:5001",# WuKongIM 即时通讯服务地址
        description="URL of the WuKongIM service"
    )
    WUKONGIM_SERVICE_TIMEOUT: int = Field(
        default=10,
        description="Timeout for WuKongIM service requests in seconds"
    )
    WUKONGIM_ENABLED: bool = Field(
        default=True,                   # 是否开启悟空 IM 集成
        description="Enable WuKongIM integration for instant messaging"
    )
    WUKONGIM_DEVICE_FLAG: int = Field(
        default=1,                      # 设备标识：0=APP 1=Web 2=PC
        description="WuKongIM device flag (0=app, 1=web, 2=pc)"
    )
    WUKONGIM_DEVICE_LEVEL: int = Field(
        default=1,                      # 设备级别：0=辅设备 1=主设备
        description="WuKongIM device level (0=secondary, 1=primary)"
    )

    # ========== 日志配置 ==========
    # Logging
    LOG_LEVEL: str = Field(
        default="INFO",                 # 日志级别：DEBUG/INFO/WARNING/ERROR
        description="Logging level"
    )
    LOG_FORMAT: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s", # 日志输出格式
        description="Logging format"
    )

    # ========== Redis 缓存配置 ==========
    # Redis (for caching and sessions)
    REDIS_URL: Optional[str] = Field(
        default=None,                   # Redis 连接地址；为空则不启用 Redis，使用内存缓存/会话
        description="Redis URL for caching and sessions"
    )

    # ========== IP 地理定位配置 ==========
    # GeoIP settings (for IP to location lookup)
    # Supports two providers: geoip2 (MaxMind GeoLite2) and ip2region
    GEOIP_PROVIDER: str = Field(
        default="ip2region",            # GeoIP 实现方案：geoip2(MaxMind) / ip2region(开源本地库)
        description="GeoIP provider: 'geoip2' (MaxMind) or 'ip2region' (lionsoul2014)"
    )
    GEOIP_DATABASE_PATH: Optional[str] = Field(
        default="resources/geoip",      # GeoIP 数据库文件/目录路径
        description="Path to GeoLite2-City.mmdb (geoip2) or ip2region directory/file (ip2region)"
    )
    GEOIP_ENABLED: bool = Field(
        default=True,                   # 是否开启 IP 地理位置解析
        description="Enable IP geolocation lookup (requires GEOIP_DATABASE_PATH)"
    )

    # ========== 接口限流配置 ==========
    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = Field(
        default=True,                   # 总开关：是否开启接口限流
        description="Enable rate limiting"
    )
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = Field(
        default=100,                    # 每分钟最多请求数
        description="Rate limit requests per minute",
        gt=0
    )

    # ========== 分页默认配置 ==========
    # Pagination
    DEFAULT_PAGE_SIZE: int = Field(
        default=20,                     # 默认每页条数
        description="Default page size for paginated responses",
        gt=0,
        le=100                          # 校验：小于等于 100
    )
    MAX_PAGE_SIZE: int = Field(
        default=100,                    # 单页最大条数，防止恶意拉取大量数据
        description="Maximum page size for paginated responses",
        gt=0
    )

    # ========== 访客在线状态同步配置 ==========
    # Visitor online status sync settings
    VISITOR_ONLINE_SYNC_ENABLED: bool = Field(
        default=True,                   # 是否定时同步访客在线状态到悟空 IM
        description="Enable periodic sync of visitor online status with WuKongIM",
    )
    VISITOR_ONLINE_SYNC_INTERVAL_SECONDS: int = Field(
        default=60,                     # 同步周期，默认 1 分钟
        description="Interval in seconds for visitor online status sync (default 1 minute)",
        gt=0,
    )
    VISITOR_ONLINE_SYNC_BATCH_SIZE: int = Field(
        default=100,                    # 每批同步的访客数量
        description="Number of visitors to check per batch in online status sync",
        gt=0,
    )

    # ========== 未知平台兜底配置 ==========
    # Unknown Platform Fallback
    UNKNOWN_PLATFORM_ID: str = Field(
        default="00000000-0000-0000-0000-000000000000", # 平台数据缺失时的兜底平台 UUID
        description="UUID for the unknown/fallback platform when platform data is missing"
    )
    UNKNOWN_PLATFORM_NAME: str = Field(
        default="未知平台",             # 兜底平台的展示名称
        description="Display name for the unknown/fallback platform"
    )

    # ========== 文件上传（旧版兼容） ==========
    # File Upload (legacy)
    MAX_FILE_SIZE: int = Field(
        default=10 * 1024 * 1024,      # 单文件最大字节数，默认 10MB
        description="Maximum file upload size in bytes",
        gt=0
    )
    ALLOWED_FILE_TYPES: List[str] = Field(
        # 原配置已注释，默认空列表表示不限制类型
        default_factory=lambda: [],
        description="Allowed file MIME types"
    )

    # ========== 聊天文件上传配置（新版推荐） ==========
    # Chat Upload Settings (preferred)
    UPLOAD_BASE_DIR: str = Field(
        default="./uploads",            # 文件上传根目录
        description="Base directory for file uploads",
    )
    MAX_UPLOAD_SIZE_MB: int = Field(
        default=10,                     # 单文件最大 MB 数
        description="Maximum upload file size in MB",
        gt=0,
    )
    ALLOWED_UPLOAD_EXTENSIONS: List[str] = Field(
        # 原配置已注释，默认空列表表示不限制后缀
        default_factory=lambda: [],
        description="Allowed file extensions for uploads",
    )

    # ========== 平台 Logo 上传配置 ==========
    # Platform Logo Upload Settings
    PLATFORM_LOGO_UPLOAD_DIR: str = Field(
        default="./uploads/platform_logos", # 平台 Logo 存储目录
        description="Base directory for platform logo uploads",
    )
    PLATFORM_LOGO_MAX_SIZE_MB: int = Field(
        default=5,                      # Logo 最大 5MB
        description="Maximum size for platform logo uploads in MB",
        gt=0,
    )
    PLATFORM_LOGO_ALLOWED_TYPES: List[str] = Field(
        default_factory=lambda: [
            "image/png",
            "image/jpeg",
            "image/jpg",
            "image/svg+xml",
            "image/gif",
        ],                              # 允许的图片 MIME 类型
        description="Allowed MIME types for platform logo uploads",
    )

    # ========== 存储方式配置 ==========
    # Storage Settings
    STORAGE_TYPE: str = Field(
        default="local",                # 存储类型：local 本地 / oss 阿里云 OSS / minio 对象存储
        description="Storage type: local, oss, minio",
    )
    
    # 阿里云 OSS 配置
    # Aliyun OSS Settings
    OSS_ENDPOINT: Optional[str] = Field(
        default=None,                   # OSS 地域节点
        description="Aliyun OSS endpoint (e.g., oss-cn-hangzhou.aliyuncs.com)",
    )
    OSS_BUCKET_NAME: Optional[str] = Field(
        default=None,                   # OSS 桶名称
        description="Aliyun OSS bucket name",
    )
    OSS_BUCKET_URL: Optional[str] = Field(
        default=None,                   # OSS 访问域名（可绑定自定义域名）
        description="Aliyun OSS bucket URL or Custom Domain (e.g., https://bucket.oss-cn.com)",
    )
    OSS_ACCESS_KEY_ID: Optional[str] = Field(
        default=None,                   # OSS 访问密钥 ID
        description="Aliyun OSS access key ID",
    )
    OSS_ACCESS_KEY_SECRET: Optional[str] = Field(
        default=None,                   # OSS 访问密钥 Secret
        description="Aliyun OSS access key secret",
    )

    # MinIO 对象存储配置
    # MinIO Settings
    MINIO_URL: Optional[str] = Field(
        default=None,                   # MinIO 服务地址
        description="MinIO base URL (e.g., http://localhost:9000)",
    )
    MINIO_ACCESS_KEY_ID: Optional[str] = Field(
        default=None,
        description="MinIO access key ID",
    )
    MINIO_SECRET_ACCESS_KEY: Optional[str] = Field(
        default=None,
        description="MinIO secret access key",
    )
    MINIO_BUCKET_NAME: Optional[str] = Field(
        default=None,
        description="MinIO bucket name",
    )
    MINIO_UPLOAD_URL: Optional[str] = Field(
        default=None,                   # 内网上传地址（与公网下载地址分离时使用）
        description="MinIO upload URL (if different from MINIO_URL, e.g., for internal network)",
    )
    MINIO_DOWNLOAD_URL: Optional[str] = Field(
        default=None,                   # 公网下载地址
        description="MinIO download URL (if different from MINIO_URL, e.g., for public domain)",
    )

    # ========== 插件系统配置 ==========
    PLUGIN_ENABLED: bool = Field(
        default=True,                   # 是否启用插件系统
        description="Enable plugin system",
    )
    PLUGIN_RUNTIME_URL: str = Field(
        default="http://localhost:8090",# 插件运行时服务地址
        description="URL of the tgo-plugin-runtime service",
    )
    PLUGIN_RUNTIME_TIMEOUT: int = Field(
        default=35,
        description="Timeout in seconds for plugin runtime requests",
        gt=0,
    )

    # ========== 设备控制服务配置 ==========
    # Device Control Service
    DEVICE_CONTROL_SERVICE_URL: str = Field(
        default="http://localhost:8085",# 设备控制服务地址
        description="URL of the tgo-device-control service",
    )
    DEVICE_CONTROL_SERVICE_TIMEOUT: int = Field(
        default=60,
        description="Timeout in seconds for device control requests",
        gt=0,
    )

    # ========== AgentOS 电脑操作智能体配置 ==========
    # Device Control AgentOS (Computer Use Agent)
    DEVICE_CONTROL_AGENTOS_URL: str = Field(
        default="http://localhost:7778",# AgentOS 服务端地址
        description="URL of the Device Control AgentOS server",
    )
    DEVICE_CONTROL_AGENT_ID: str = Field(
        default="computer-use-agent",   # 电脑操作智能体的 ID
        description="Agent ID for the Computer Use Agent",
    )

    # ========== 运行环境配置 ==========
    # Environment
    ENVIRONMENT: str = Field(
        default="development",          # 运行环境：development / production 等
        description="Application environment"
    )
    DEBUG: bool = Field(
        default=False,                  # Debug 模式开关；生产环境必须关闭
        description="Debug mode"
    )

    # ========== 计算属性：环境判断 ==========
    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        # 判断是否为开发/本地环境，支持多种写法
        return self.ENVIRONMENT.lower() in ("development", "dev", "local")

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        # 判断是否为生产环境
        return self.ENVIRONMENT.lower() in ("production", "prod")

    # ========== 计算属性：同步数据库连接串 ==========
    @property
    def database_url_sync(self) -> str:
        """Get synchronous database URL (force psycopg2 driver)."""
        # 将任意格式的 PG 连接串强制转换为 psycopg2 驱动格式，供同步 ORM/脚本使用
        url = str(self.DATABASE_URL)
        if "postgresql+asyncpg://" in url:
            return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
        if "postgresql+psycopg2://" in url:
            return url
        if "postgresql://" in url:
            return url.replace("postgresql://", "postgresql+psycopg2://")
        # 兜底：直接替换协议头
        scheme, rest = url.split("://", 1)
        return f"postgresql+psycopg2://{rest}"

    # ========== 计算属性：异步数据库连接串 ==========
    @property
    def database_url_async(self) -> str:
        """Get asynchronous database URL (force asyncpg driver)."""
        # 将任意格式的 PG 连接串强制转换为 asyncpg 驱动格式，供异步 SQLAlchemy 使用
        url = str(self.DATABASE_URL)
        if "postgresql+asyncpg://" in url:
            return url
        if "postgresql+psycopg2://" in url:
            return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
        if "postgresql://" in url:
            return url.replace("postgresql://", "postgresql+asyncpg://")
        # 兜底：直接替换协议头
        scheme, rest = url.split("://", 1)
        return f"postgresql+asyncpg://{rest}"


# ========== 全局单例实例 ==========
# Create global settings instance
# 项目启动时实例化一次，其他模块直接 `from config import settings` 使用即可
settings = Settings()