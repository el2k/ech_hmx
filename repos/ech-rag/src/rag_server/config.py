"""
Configuration management for RAG service using Pydantic Settings v2.
"""

import os
from typing import Any, Dict, List, Optional

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False, # case_sensitive 指定环境变量是否区分大小写，默认False
        extra="ignore", # extra 指定是否允许额外的未定义字段，默认 "ignore" 忽略未定义字段
    )

    # Application settings
    app_name: str = Field(default="ECH RAG Service", description="Application name")
    app_version: str = Field(default="0.1.0", description="Application version")
    environment: str = Field(default="development", description="Environment name")
    debug: bool = Field(default=False, description="Debug mode")
    log_level: str = Field(default="INFO", description="Logging level")

    # Server settings
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8082, description="Server port")
    workers: int = Field(default=1, description="Number of worker processes")
    reload: bool = Field(default=False, description="Auto-reload on code changes")

    # Database settings
    database_url: str = Field(
        default="postgresql+asyncpg://rag_user:rag_password@localhost:5432/rag_service",
        description="PostgreSQL database URL",
    )
    # 数据库连接池设置
    database_pool_size: int = Field(default=20, description="Database connection pool size")
    # 数据库最大溢出连接数
    database_max_overflow: int = Field(default=30, description="Database max overflow connections")
    # 数据库连接池超时时间
    database_pool_timeout: int = Field(default=30, description="Database pool timeout in seconds")

    # Redis settings
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis URL for caching and task queue",
    )
    # redis_password 指定 Redis 密码，如果 Redis 没有设置密码，则为 None
    redis_password: Optional[str] = Field(default=None, description="Redis password")
    # redis_db 指定 Redis 数据库编号，默认为 0
    redis_db: int = Field(default=0, description="Redis database number")

    # Authentication settings (API key based)
    api_key_header: str = Field(default="X-API-Key", description="API key header name")
    # api_key_cache_ttl 指定 API key 缓存的过期时间，单位为秒，默认值为 300 秒（5 分钟）
    api_key_cache_ttl: int = Field(default=300, description="API key cache TTL in seconds")

    # CORS settings
    # cors_origins 指定允许跨域请求的来源列表，默认值为 ["http://localhost:3000", "http://localhost:8080"]
    cors_origins: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:8080"],
        description="Allowed CORS origins",
    )
    # cors_allow_credentials 指定是否允许跨域请求携带凭证（如 Cookie），默认值为 True
    cors_allow_credentials: bool = Field(default=True, description="Allow CORS credentials")
    # cors_allow_methods 指定允许跨域请求的方法列表，默认值为 ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
    cors_allow_methods: List[str] = Field(
        default=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        description="Allowed CORS methods",
    )
    # cors_allow_headers 指定允许跨域请求的头部列表，默认值为 ["*"]，表示允许所有头部
    cors_allow_headers: List[str] = Field(
        default=["*"], description="Allowed CORS headers"
    )

    # File upload settings
    # max_file_size 指定文件上传的最大大小，单位为字节，默认值为 100MB
    max_file_size: int = Field(default=100 * 1024 * 1024, description="Max file size in bytes (100MB)")
    # upload_dir 指定文件上传的目录路径，默认值为 "uploads"
    upload_dir: str = Field(default="uploads", description="Upload directory path")
    # allowed_file_types 指定允许上传的文件类型列表，
    # 默认值为 ["application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "text/plain", "text/markdown", "text/html"]
    allowed_file_types: List[str] = Field(
        default=[
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "text/plain",
            "text/markdown",
            "text/html",
        ],
        description="Allowed file MIME types",
    )

    # Document processing settings
    # chunk_size 指定文档分块的大小，单位为 token，默认值为 1000
    chunk_size: int = Field(default=1000, description="Document chunk size in tokens")
    # chunk_overlap 指定文档分块的重叠大小，单位为 token，默认值为 200
    chunk_overlap: int = Field(default=200, description="Document chunk overlap in tokens")
    # batch_size 指定批量处理的大小，默认值为 50
    batch_size: int = Field(default=50, description="Batch size for processing")
    # max_concurrent_tasks 指定最大并发处理任务数，默认值为 10
    max_concurrent_tasks: int = Field(default=10, description="Max concurrent processing tasks")

    # Embedding settings
    # embedding_provider 指定嵌入向量提供商，默认值为 "openai"，可选值为 "openai" 或 "qwen3"
    embedding_provider: str = Field(
        default="openai",
        description="Embedding provider (openai, qwen3)"
    )
    openai_api_key: Optional[str] = Field(default=None, description="OpenAI API key")
    embedding_model: str = Field(
        default="text-embedding-ada-002", description="Embedding model name"
    )
    # embedding_dimensions 指定嵌入向量的维度，默认值为 1536
    embedding_dimensions: int = Field(default=1536, description="Embedding vector dimensions")
    # embedding_batch_size 指定嵌入向量批量处理的大小，默认值为 10（Qwen3 兼容性要求最大为 10）
    embedding_batch_size: int = Field(default=10, description="Embedding batch size (max 10 for Qwen3 compatibility)")

    # OpenAI-compatible settings
    # openai_compatible_base_url 指定 OpenAI 兼容的嵌入向量 API 基础 URL，例如 "http://localhost:11434/v1"
    openai_compatible_base_url: Optional[str] = Field(
        default=None,
        description="OpenAI-compatible Embeddings API base URL (e.g., http://localhost:11434/v1)"
    )

    # Qwen3-Embedding settings (Alibaba Cloud DashScope)
    qwen3_api_key: Optional[str] = Field(default=None, description="Alibaba Cloud DashScope API key")
    qwen3_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        description="Qwen3-Embedding API base URL"
    )
    qwen3_model: str = Field(
        default="text-embedding-v4",
        description="Qwen3-Embedding model name"
    )
    qwen3_dimensions: int = Field(default=1536, description="Qwen3-Embedding vector dimensions")

    # Search settings
    # default_search_limit 指定默认搜索结果限制，默认值为 20
    default_search_limit: int = Field(default=20, description="Default search result limit")
    # max_search_limit 指定最大搜索结果限制，默认值为 100
    max_search_limit: int = Field(default=100, description="Maximum search result limit")
    # min_similarity_score 指定最小相似度分数，用于过滤低质量结果，默认值为 0.1
    min_similarity_score: float = Field(default=0.1, description="Minimum similarity score (filter low-quality results)")
    # hybrid_search_weight 指定混合搜索中语义搜索的权重，默认值为 0.7
    semantic_search_weight: float = Field(default=0.7, description="Semantic search weight in hybrid search")
    # hybrid_search_weight 指定混合搜索中关键字搜索的权重，默认值为 0.3
    keyword_search_weight: float = Field(default=0.3, description="Keyword search weight in hybrid search")
    
    # Hybrid search settings
    # rrf_k 指定 RRF 融合常数 k，默认值为 60
    rrf_k: int = Field(default=60, description="RRF fusion constant k")
    # candidate_multiplier 指定混合搜索候选池的倍数，默认值为 5
    candidate_multiplier: int = Field(default=5, description="Candidate pool multiplier for hybrid search")
    
    # QA generation settings
    # default_is_qa_mode 指定默认 QA 模式开关，用于文件处理时请求未提供 is_qa_mode 时的默认值，默认值为 False
    default_is_qa_mode: bool = Field(
        default=False,
        description="Default QA mode switch for file processing when request does not provide is_qa_mode",
    )
    # qa_generation_batch_size 指定 QA 对生成的批量大小，默认值为 5
    qa_generation_batch_size: int = Field(default=5, description="Batch size for QA pair generation")

    # Rate limiting settings
    # rate_limit_enabled 指定是否启用速率限制，默认值为 True
    rate_limit_enabled: bool = Field(default=True, description="Enable rate limiting")
    # rate_limit_requests 指定每个窗口的请求限制，默认值为 100
    rate_limit_requests: int = Field(default=100, description="Rate limit requests per window")
    # rate_limit_window 指定速率限制窗口的时间，单位为秒，默认值为 60 秒
    rate_limit_window: int = Field(default=60, description="Rate limit window in seconds")

    # Monitoring settings
    # metrics_enabled 指定是否启用指标收集，默认值为 True
    metrics_enabled: bool = Field(default=True, description="Enable metrics collection")
    # tracing_enabled 指定是否启用分布式追踪，默认值为 False
    tracing_enabled: bool = Field(default=False, description="Enable distributed tracing")
    # health_check_interval 指定健康检查间隔，单位为秒，默认值为 30 秒
    health_check_interval: int = Field(default=30, description="Health check interval in seconds")

    # Celery settings
    # celery_broker_url 指定 Celery 消息代理 URL，如果未提供，则从 Redis URL 中获取，默认值为 None
    celery_broker_url: Optional[str] = Field(default=None, description="Celery broker URL")
    # celery_result_backend 指定 Celery 结果后端 URL，如果未提供，则从 Redis URL 中获取，默认值为 None
    celery_result_backend: Optional[str] = Field(default=None, description="Celery result backend URL")
    # celery_task_serializer 指定 Celery 任务序列化方式，默认值为 "json"
    celery_task_serializer: str = Field(default="json", description="Celery task serializer")
    # celery_result_serializer 指定 Celery 结果序列化方式，默认值为 "json"
    celery_result_serializer: str = Field(default="json", description="Celery result serializer")
    # celery_timezone 指定 Celery 时区，默认值为 "UTC"
    celery_timezone: str = Field(default="UTC", description="Celery timezone")
    # 指定该验证器作用于 celery_broker_url 字段。
    # mode="before" 非常关键：表示这个函数在 Pydantic 进行默认的类型转换和验证之前执行。此时拿到的 v 是用户传入的原始值。
    @field_validator("celery_broker_url", mode="before")
    @classmethod
    def set_celery_broker_url(cls, v: Optional[str], info) -> str:
        """Set Celery broker URL from Redis URL if not provided."""
        if v is not None:
            return v
        # Access other field values through info.data
        redis_url = info.data.get("redis_url", "redis://localhost:6379/0")
        return redis_url

    @field_validator("celery_result_backend", mode="before")
    @classmethod
    def set_celery_result_backend(cls, v: Optional[str], info) -> str:
        """Set Celery result backend URL from Redis URL if not provided."""
        if v is not None:
            return v
        # Access other field values through info.data
        redis_url = info.data.get("redis_url", "redis://localhost:6379/0")
        return redis_url

    @field_validator("upload_dir", mode="before")
    @classmethod
    def create_upload_dir(cls, v: str) -> str:
        """Create upload directory if it doesn't exist."""
        os.makedirs(v, exist_ok=True)
        return v


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get application settings instance."""
    return settings
