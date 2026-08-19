# -*- coding: utf-8 -*-
"""Aliyun OSS storage backend."""
# 模块说明：阿里云对象存储（OSS）后端实现，提供与OSS交互的具体方法。

import asyncio
from typing import BinaryIO, Any
from urllib.parse import urlparse

# 尝试导入阿里云OSS SDK（oss2）
try:
    import oss2
except ImportError:
    oss2 = None  # 如果未安装，标记为None，后续初始化时会抛出友好的错误提示

# 导入存储后端抽象基类
from app.services.storage.base import StorageBackend


class AliyunOSSBackend(StorageBackend):
    """
    阿里云OSS存储后端实现类。
    
    继承自 StorageBackend，实现了标准的上传、删除、存在性检查等操作。
    所有与OSS SDK交互的方法都使用 asyncio 的 run_in_executor 将同步调用转为异步，
    避免阻塞事件循环。
    """

    def __init__(
        self,
        endpoint: str,
        bucket_name: str,
        access_key_id: str,
        access_key_secret: str,
        bucket_url: str = None,
    ):
        """
        初始化阿里云OSS后端。

        Args:
            endpoint: OSS服务端点，例如 "oss-cn-hangzhou.aliyuncs.com"
            bucket_name: 存储桶名称
            access_key_id: 阿里云访问密钥ID
            access_key_secret: 阿里云访问密钥Secret
            bucket_url: 存储桶的公开访问URL基础地址，可以是默认OSS域名或自定义CDN域名
                       例如 "https://my-bucket.oss-cn-hangzhou.aliyuncs.com" 
                       或 "https://cdn.example.com"
        """
        # 检查oss2库是否已安装，若未安装则抛出明确的错误提示
        if oss2 is None:
            raise ImportError(
                "The 'oss2' package is required for AliyunOSSBackend. "
                "Install it with 'pip install oss2'."
            )

        # 创建OSS认证对象
        self.auth = oss2.Auth(access_key_id, access_key_secret)
        
        # 创建Bucket操作对象，用于执行上传、删除等操作
        self.bucket = oss2.Bucket(self.auth, endpoint, bucket_name)
        
        # 构建存储桶的公网访问URL
        # 如果未提供bucket_url，则使用默认格式：https://{bucket_name}.{endpoint}
        # 去除末尾多余的斜杠，便于后续路径拼接
        self.bucket_url = (bucket_url or f"https://{bucket_name}.{endpoint}").rstrip("/")

    # ------------------- 核心存储操作（异步） -------------------

    async def upload(self, file: BinaryIO, path: str, content_type: str) -> str:
        """
        上传文件到阿里云OSS。

        参数：
            file: 文件对象（二进制模式打开）
            path: 文件在OSS中的存储路径（可包含目录层级）
            content_type: 文件的MIME类型，用于设置HTTP响应头

        返回：
            str: 文件的公网访问URL
        """
        # 使用 run_in_executor 将同步的OSS SDK调用放入线程池执行
        # 避免阻塞主事件循环
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, 
            # lambda表达式：调用oss2的put_object方法
            # path.lstrip("/") 去除路径开头的斜杠，OSS路径不应以斜杠开头
            # headers 设置Content-Type，浏览器访问时能正确识别文件类型
            lambda: self.bucket.put_object(
                path.lstrip("/"), 
                file, 
                headers={"Content-Type": content_type}
            )
        )
        # 上传完成后返回公网访问URL
        return self.get_public_url(path)

    async def delete(self, path: str) -> bool:
        """
        删除OSS中的文件。

        参数：
            path: 文件在OSS中的存储路径

        返回：
            bool: 删除成功返回True，失败返回False
        """
        loop = asyncio.get_event_loop()
        try:
            # 调用oss2的delete_object方法删除文件
            await loop.run_in_executor(
                None,
                lambda: self.bucket.delete_object(path.lstrip("/"))
            )
            return True
        except Exception:
            # 删除失败（如文件不存在、权限不足等）返回False
            # 不抛出异常，保持接口一致性
            return False

    # ------------------- 辅助方法 -------------------

    def get_public_url(self, path: str) -> str:
        """
        生成文件在OSS中的公网访问URL。

        参数：
            path: 文件在OSS中的存储路径

        返回：
            str: 完整的公网访问URL
        """
        clean_path = path.lstrip("/")  # 清理路径开头的斜杠
        # 拼接 bucket_url 和路径，生成可直接访问的链接
        # 注意：这里对路径前缀没有做特殊处理，所有文件都通过 bucket_url 访问
        # 如果业务需要区分API代理和OSS直链，可在此增加逻辑判断
        return f"{self.bucket_url}/{clean_path}"

    async def exists(self, path: str) -> bool:
        """
        检查文件是否存在于OSS中。

        参数：
            path: 文件在OSS中的存储路径

        返回：
            bool: 文件存在返回True，否则返回False
        """
        loop = asyncio.get_event_loop()
        # 调用oss2的object_exists方法判断文件是否存在
        return await loop.run_in_executor(
            None,
            lambda: self.bucket.object_exists(path.lstrip("/"))
        )

    def resolve_url(self, url: str) -> str:
        """
        解析并规范化一个可能是相对路径或不正确的公网URL。
        主要用于将本地服务URL转换为OSS直链。

        参数：
            url: 待解析的URL或路径（可能是相对路径、本地地址等）

        返回：
            str: 规范化后的完整URL
        """
        if not url or not isinstance(url, str):
            return url
            
        # 情况1：输入是相对路径（以 "/" 开头）
        if url.startswith("/"):
            path = url
            # 如果路径以 "/api/v1" 开头，去除该前缀（因为OSS中存储的路径通常不包含API前缀）
            if path.startswith("/api/v1"):
                path = path[4:]  # 去掉 "/api" 保留 "/v1/... " 注意：这里可能有误，应该是去掉 "/api/v1"
                # 修正：更好的写法是 path = path[7:] 或使用 replace，但保留原代码逻辑
            return self.get_public_url(path)
            
        # 情况2：输入是完整的URL
        if url.startswith("http://") or url.startswith("https://"):
            parsed = urlparse(url)
            # 如果URL指向 localhost 或 127.0.0.1（通常是开发环境），
            # 将其转换为OSS直链
            if "localhost" in parsed.netloc or "127.0.0.1" in parsed.netloc:
                p = parsed.path
                if p.startswith("/api/v1"):
                    p = p[4:]  # 同样去除API前缀
                return self.get_public_url(p)
                
        # 其他情况：直接返回原始URL（可能是完整的OSS直链或其他外链）
        return url

    def get_file_access_url(self, file_id: str, storage_url: str) -> str:
        """
        获取文件的访问URL。
        对于云存储，直接返回存储URL即可（因为OSS本身就提供公网访问能力）。

        参数：
            file_id: 文件ID（阿里云OSS实现中暂未使用）
            storage_url: 存储的完整URL

        返回：
            str: 文件的访问URL
        """
        # 云存储直接返回存储URL，无需通过API代理
        return storage_url