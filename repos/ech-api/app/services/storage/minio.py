# -*- coding: utf-8 -*-
"""MinIO/S3 storage backend."""
# 模块说明：MinIO/S3 存储后端实现，使用 boto3 库与兼容 S3 协议的对象存储服务交互。
# MinIO 是兼容 AWS S3 API 的开源对象存储服务，因此本实现也适用于 AWS S3、Google Cloud Storage（兼容模式）等。

import asyncio
from typing import BinaryIO, Any, Optional
from urllib.parse import urlparse

# 尝试导入 boto3（AWS SDK for Python）及其异常类
try:
    import boto3
    from botocore.exceptions import ClientError  # boto3 的客户端异常类型
except ImportError:
    boto3 = None
    ClientError = Exception  # 如果未安装，将 ClientError 降级为普通 Exception

# 导入存储后端抽象基类
from app.services.storage.base import StorageBackend


class MinIOBackend(StorageBackend):
    """
    MinIO 存储实现类（兼容 S3 协议）。
    
    使用 boto3 库与任何兼容 S3 协议的对象存储服务交互，包括：
        - MinIO（开源对象存储）
        - AWS S3（亚马逊云对象存储）
        - 阿里云 OSS（部分兼容模式）
        - Google Cloud Storage（S3 兼容模式）
        - 其他 S3 兼容服务
    
    所有涉及网络 IO 的操作都通过 asyncio.run_in_executor 转为异步，
    避免阻塞事件循环。
    """

    def __init__(
        self,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        bucket_name: str,
        upload_url: Optional[str] = None,
        download_url: Optional[str] = None,
        region_name: str = "us-east-1",
    ):
        """
        初始化 MinIO/S3 后端。

        Args:
            endpoint_url: S3 服务的端点 URL
                         MinIO 示例：http://localhost:9000
                         AWS S3 示例：https://s3.amazonaws.com
            access_key_id: 访问密钥 ID（MinIO 中的 Access Key）
            secret_access_key: 访问密钥 Secret（MinIO 中的 Secret Key）
            bucket_name: 存储桶名称
            upload_url: 上传专用 URL（可选），用于内网上传加速或分离上传流量
            download_url: 下载专用 URL（可选），通常是 CDN 域名或自定义域名
                         如果提供，生成的访问 URL 将使用此域名
            region_name: S3 区域名称，默认 "us-east-1"
                        MinIO 通常可以忽略此参数
        """
        # 检查 boto3 是否已安装
        if boto3 is None:
            raise ImportError(
                "The 'boto3' package is required for MinIOBackend. "
                "Install it with 'pip install boto3'."
            )

        self.bucket_name = bucket_name
        # download_url：用于生成文件访问 URL 的基础地址
        # 如果未提供，使用 endpoint_url
        self.download_url = (download_url or endpoint_url).rstrip("/")
        # upload_url：用于实际上传操作的端点
        # 如果未提供，使用 endpoint_url
        self.upload_url = (upload_url or endpoint_url).rstrip("/")
        
        # 初始化 boto3 S3 客户端
        self.s3 = boto3.client(
            "s3",
            endpoint_url=self.upload_url,          # API 请求端点
            aws_access_key_id=access_key_id,       # 访问密钥 ID
            aws_secret_access_key=secret_access_key, # 访问密钥 Secret
            region_name=region_name,                # 区域名称
        )

    # ------------------- 核心存储操作（异步） -------------------

    async def upload(self, file: BinaryIO, path: str, content_type: str) -> str:
        """
        上传文件到 MinIO/S3。

        使用 boto3 的 put_object 方法上传文件。
        boto3 是同步库，通过 run_in_executor 将其放入线程池执行。

        Args:
            file: 文件对象（二进制读取模式）
            path: 文件在存储中的相对路径（作为 S3 的 Key）
            content_type: 文件的 MIME 类型，设置到 ContentType 头部

        Returns:
            str: 文件的公网访问 URL
        """
        loop = asyncio.get_event_loop()
        clean_path = path.lstrip("/")  # S3 的 Key 不应以斜杠开头
        
        # 在线程池中执行同步的 put_object 调用
        await loop.run_in_executor(
            None,
            lambda: self.s3.put_object(
                Bucket=self.bucket_name,      # 存储桶名称
                Key=clean_path,                # 文件的 Key（路径）
                Body=file,                     # 文件内容
                ContentType=content_type       # 内容类型
            )
        )
        return self.get_public_url(path)

    async def delete(self, path: str) -> bool:
        """
        从 MinIO/S3 删除文件。

        Args:
            path: 文件在存储中的相对路径

        Returns:
            bool: 删除成功返回 True，失败返回 False
        """
        loop = asyncio.get_event_loop()
        try:
            # 调用 delete_object 方法删除文件
            await loop.run_in_executor(
                None,
                lambda: self.s3.delete_object(
                    Bucket=self.bucket_name,
                    Key=path.lstrip("/")
                )
            )
            return True
        except Exception:
            # 捕获所有异常（文件不存在、权限不足等），返回 False
            return False

    # ------------------- 辅助方法 -------------------

    def get_public_url(self, path: str) -> str:
        """
        根据存储路径生成公网访问 URL。

        处理两种 URL 格式：
            1. 虚拟主机风格（Virtual-host-style）：
               https://{bucket_name}.{domain}/{path}
            2. 路径风格（Path-style）：
               https://{domain}/{bucket_name}/{path}
        
        MinIO 通常使用路径风格，AWS S3 默认使用虚拟主机风格。
        本实现自动检测 download_url 中是否已包含 bucket_name，
        如果不包含则自动追加 /{bucket_name} 前缀。

        Args:
            path: 文件存储路径

        Returns:
            str: 完整的公网访问 URL
        """
        clean_path = path.lstrip("/")
        # 如果 download_url 中没有包含 bucket_name，需要手动添加
        # 例如：download_url = "https://cdn.example.com" 
        #      -> "https://cdn.example.com/my-bucket/file.txt"
        if self.bucket_name not in self.download_url:
            return f"{self.download_url}/{self.bucket_name}/{clean_path}"
        # 如果已包含 bucket_name，直接拼接路径
        # 例如：download_url = "https://my-bucket.minio.example.com"
        #      -> "https://my-bucket.minio.example.com/file.txt"
        return f"{self.download_url}/{clean_path}"

    async def exists(self, path: str) -> bool:
        """
        检查文件是否存在于 MinIO/S3 中。

        使用 head_object 方法获取文件元数据，如果成功则文件存在。
        head_object 不会下载文件内容，只获取元数据，效率较高。

        Args:
            path: 文件存储路径

        Returns:
            bool: 文件存在返回 True，否则返回 False
        """
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: self.s3.head_object(
                    Bucket=self.bucket_name,
                    Key=path.lstrip("/")
                )
            )
            return True
        except ClientError:
            # ClientError 通常表示文件不存在（404）或权限不足（403）
            # 统一返回 False
            return False
        except Exception:
            # 其他异常也返回 False
            return False

    def resolve_url(self, url: str) -> str:
        """
        解析并规范化一个可能是相对路径或格式不正确的 URL。

        处理逻辑与 LocalStorageBackend 类似，但最终调用 get_public_url
        生成 S3/CDN 直链。

        Args:
            url: 待解析的 URL 或路径

        Returns:
            str: 规范化后的完整 URL
        """
        if not url or not isinstance(url, str):
            return url
            
        # 情况1：以 "/" 开头的相对路径
        if url.startswith("/"):
            path = url
            # 如果路径以 "/api/v1" 开头，去除 API 前缀
            if path.startswith("/api/v1"):
                path = path[4:]  # 去掉 "/api"（注意：只去掉了4个字符）
            return self.get_public_url(path)
            
        # 情况2：完整的 HTTP/HTTPS URL，且指向 localhost（开发环境）
        if url.startswith("http://") or url.startswith("https://"):
            parsed = urlparse(url)
            # 仅处理本地地址（开发环境常见）
            if "localhost" in parsed.netloc or "127.0.0.1" in parsed.netloc:
                p = parsed.path
                if p.startswith("/api/v1"):
                    p = p[4:]
                return self.get_public_url(p)
                
        # 其他情况：直接返回原始 URL
        return url

    def get_file_access_url(self, file_id: str, storage_url: str) -> str:
        """
        获取前端应该使用的文件访问 URL。

        对于云存储，直接返回存储 URL（OSS/S3 直链）。
        前端可以直接从 CDN/对象存储下载文件，无需经过应用服务器。

        Args:
            file_id: 数据库中的文件 ID（云存储模式不使用）
            storage_url: upload() 方法返回的存储 URL

        Returns:
            str: 前端应该使用的最终访问 URL
        """
        return storage_url