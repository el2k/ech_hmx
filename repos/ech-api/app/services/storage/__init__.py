# -*- coding: utf-8 -*-
"""Storage services module.

Provides a unified interface for file storage.
Currently only supports local storage, OSS can be added later.
"""
# 模块说明：存储服务模块，提供统一的文件存储接口。
# 目前仅支持本地存储，后续可扩展支持阿里云OSS、MinIO等。

# 导入配置对象
from app.core.config import settings
# 导入存储后端抽象基类
from app.services.storage.base import StorageBackend
# 导入本地存储后端实现
from app.services.storage.local import LocalStorageBackend


def get_storage_backend() -> StorageBackend:
    """
    工厂函数：根据配置文件中的存储类型，返回对应的存储后端实例。
    
    支持的存储类型：
        - "local"（默认）：本地文件系统存储
        - "oss"：阿里云对象存储 OSS
        - "minio"：MinIO 对象存储（兼容 S3 协议）
    
    返回：
        StorageBackend: 实现了 StorageBackend 接口的具体存储后端实例
    """
    # 从配置中读取存储类型，默认为 "local"，并转为小写
    storage_type = getattr(settings, "STORAGE_TYPE", "local").lower()
    
    # ------------------- 阿里云 OSS 分支 -------------------
    if storage_type == "oss":
        # 延迟导入阿里云OSS后端，避免不必要的依赖加载
        from app.services.storage.aliyun_oss import AliyunOSSBackend
        return AliyunOSSBackend(
            endpoint=settings.OSS_ENDPOINT,                 # OSS 服务端点
            bucket_name=settings.OSS_BUCKET_NAME,           # 存储桶名称
            access_key_id=settings.OSS_ACCESS_KEY_ID,       # 访问密钥 ID
            access_key_secret=settings.OSS_ACCESS_KEY_SECRET, # 访问密钥 Secret
            bucket_url=settings.OSS_BUCKET_URL,             # 存储桶的公开访问 URL
        )
    
    # ------------------- MinIO 分支 -------------------
    elif storage_type == "minio":
        from app.services.storage.minio import MinIOBackend
        return MinIOBackend(
            endpoint_url=settings.MINIO_URL,                      # MinIO 服务地址
            access_key_id=settings.MINIO_ACCESS_KEY_ID,           # 访问密钥 ID
            secret_access_key=settings.MINIO_SECRET_ACCESS_KEY,   # 访问密钥 Secret
            bucket_name=settings.MINIO_BUCKET_NAME,               # 存储桶名称
            upload_url=settings.MINIO_UPLOAD_URL,                 # 上传专用 URL（可能带签名）
            download_url=settings.MINIO_DOWNLOAD_URL,             # 下载专用 URL（可能带签名）
        )
    
    # ------------------- 默认：本地存储 -------------------
    # 当 storage_type 不是 "oss" 或 "minio" 时，回退到本地存储
    return LocalStorageBackend(
        base_path=getattr(settings, "UPLOAD_DIR", "./uploads"),  # 本地存储根目录，默认 "./uploads"
        api_base_url=settings.API_BASE_URL,                       # API 基础 URL，用于构建文件访问地址
    )


# ------------------- 全局单例管理 -------------------
# 全局存储后端实例（懒加载模式）
_storage = None


def get_storage() -> StorageBackend:
    """
    获取全局的存储后端单例实例。
    
    使用懒加载模式（Lazy Initialization），仅在首次调用时创建实例，
    后续调用直接返回已创建的实例，避免重复初始化开销。
    
    返回：
        StorageBackend: 全局唯一的存储后端实例
    """
    global _storage  # 声明要修改全局变量
    
    if _storage is None:
        # 首次调用，调用工厂函数创建实例
        _storage = get_storage_backend()
    
    return _storage


# ------------------- 模块导出列表 -------------------
__all__ = [
    "StorageBackend",          # 存储后端抽象基类（供外部类型注解使用）
    "LocalStorageBackend",     # 本地存储后端实现（供外部直接使用）
    "get_storage_backend",     # 工厂函数（获取新实例）
    "get_storage",             # 单例获取函数（获取全局实例）
]