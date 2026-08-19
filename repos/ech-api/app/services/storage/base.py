# -*- coding: utf-8 -*-
"""Storage backend abstraction for file storage."""
# 模块说明：存储后端抽象基类，定义所有存储后端必须实现的统一接口。

from abc import ABC, abstractmethod
from typing import BinaryIO, Optional


class StorageBackend(ABC):
    """
    文件存储后端抽象基类。
    
    该类定义了文件存储的统一接口，所有具体存储后端（本地、OSS、MinIO等）
    都必须继承此类并实现所有抽象方法。
    
    设计目的：
        1. 统一不同存储方案的API，使上层业务代码与具体存储实现解耦
        2. 方便新增存储类型（如S3、Azure Blob等），只需实现此接口即可
        3. 便于单元测试中替换为Mock实现
    """

    # ------------------- 核心操作方法（必须实现） -------------------

    @abstractmethod
    async def upload(self, file: BinaryIO, path: str, content_type: str) -> str:
        """
        上传文件到存储后端。

        Args:
            file: 文件对象（二进制读取模式），支持任何实现了 read() 方法的类文件对象
            path: 文件在存储中的相对路径（可包含目录层级），例如 "avatars/user123.jpg"
            content_type: 文件的MIME类型，例如 "image/jpeg"、"application/pdf"
                         用于设置HTTP响应头的Content-Type，确保浏览器正确解析

        Returns:
            str: 文件的公网访问URL（完整URL地址）
                 例如 "https://cdn.example.com/avatars/user123.jpg"
                 或 "/api/v1/chat/files/xxx"（本地存储代理模式）
        """
        pass

    @abstractmethod
    async def delete(self, path: str) -> bool:
        """
        从存储中删除文件。

        Args:
            path: 文件在存储中的相对路径

        Returns:
            bool: 删除成功返回 True；文件不存在或删除失败返回 False
                  注意：此方法不应抛出异常，以保证调用方不需要处理各种异常情况
        """
        pass

    # ------------------- 辅助方法 -------------------

    @abstractmethod
    def get_public_url(self, path: str) -> str:
        """
        根据存储路径生成公网访问URL。

        Args:
            path: 文件相对路径或API路径（如 "/v1/chat/files/xxx"）
                 通常为存储时使用的路径

        Returns:
            str: 完整的公网访问URL
                 可能返回直接存储URL（OSS/CDN直链）或API代理URL（本地存储）
        """
        pass

    @abstractmethod
    async def exists(self, path: str) -> bool:
        """
        检查指定路径的文件是否存在于存储中。

        Args:
            path: 文件在存储中的相对路径

        Returns:
            bool: 文件存在返回 True，否则返回 False
        """
        pass

    @abstractmethod
    def resolve_url(self, url: str) -> str:
        """
        解析并规范化一个可能是相对路径或格式不正确的URL。

        此方法的主要用途：
            1. 将前端传入的相对路径（如 "/v1/chat/files/abc"）解析为完整URL
            2. 将开发环境的 localhost 地址转换为生产环境的存储地址
            3. 统一不同来源的URL格式，确保一致性

        Args:
            url: 待解析的URL或路径
                可能是：相对路径、完整URL、本地服务地址等

        Returns:
            str: 规范化后的完整公网URL
        """
        pass

    @abstractmethod
    def get_file_access_url(self, file_id: str, storage_url: str) -> str:
        """
        获取前端应该使用的文件访问URL。

        此方法用于区分两种访问模式：
            - 本地存储模式：返回API代理地址，例如 "/v1/chat/files/{file_id}"
            - 云存储模式：返回直接存储URL，例如 "https://cdn.example.com/xxx"

        为什么需要此方法？
            因为不同的存储后端有不同的访问方式，前端需要知道应该请求哪个URL。
            本地存储时，前端访问API接口，后端从本地读取文件返回；
            云存储时，前端直接访问CDN或OSS的URL，无需经过后端服务器。

        Args:
            file_id: 数据库中存储的文件记录ID（用于本地存储模式构建API路径）
            storage_url: upload() 方法返回的存储URL

        Returns:
            str: 前端应该使用的最终访问URL
        """
        pass