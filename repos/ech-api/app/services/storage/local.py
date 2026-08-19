# -*- coding: utf-8 -*-
"""Local file system storage backend."""
# 模块说明：本地文件系统存储后端实现，将文件保存在服务器的本地磁盘上。

import os
import shutil
from pathlib import Path
from typing import BinaryIO, Any
from urllib.parse import urlparse

# 导入存储后端抽象基类
from app.services.storage.base import StorageBackend


class LocalStorageBackend(StorageBackend):
    """
    本地文件系统存储实现类。
    
    继承自 StorageBackend，将文件存储到服务器本地磁盘。
    所有文件操作都是同步的（因为本地磁盘I/O通常很快，且上传的文件数据已经在内存中缓冲），
    实际上传方法 upload 和 delete 虽然是 async 定义，但内部并未使用异步I/O，
    这在FastAPI中是可以接受的，因为文件上传本身已经由Starlette处理了。
    
    适用场景：
        - 开发/测试环境：无需依赖云服务，快速启动
        - 小型部署：文件量不大，单机存储满足需求
        - 对存储成本敏感的项目
    """

    def __init__(self, base_path: str, api_base_url: str):
        """
        初始化本地存储后端。

        Args:
            base_path: 文件存储的根目录路径，例如 "./uploads"
            api_base_url: API服务的基础URL，用于生成文件访问地址
                         例如 "http://localhost:8000"
        """
        # 将基础路径转换为 Path 对象，便于路径操作
        self.base_path = Path(base_path)
        # 去除 api_base_url 末尾多余的斜杠，便于拼接
        self.api_base_url = api_base_url.rstrip("/")
        # 确保存储目录存在（如果不存在则创建）
        self._ensure_base_path()

    # ------------------- 私有辅助方法 -------------------

    def _ensure_base_path(self):
        """
        确保存储根目录存在。
        
        使用 parents=True 递归创建所有父级目录，
        exist_ok=True 表示如果目录已存在则不报错。
        """
        self.base_path.mkdir(parents=True, exist_ok=True)

    # ------------------- 核心存储操作 -------------------

    async def upload(self, file: BinaryIO, path: str, content_type: str) -> str:
        """
        上传文件到本地存储。

        注意：虽然此方法标记为 async，但实际 I/O 操作是同步的。
        这是因为：
            1. 文件对象已经在内存中（由 FastAPI/Starlette 的 UploadFile 处理）
            2. 使用 shutil.copyfileobj 进行高效的流式拷贝
            3. 本地磁盘 I/O 通常足够快，不需要异步化

        Args:
            file: 文件对象（二进制读取模式）
            path: 文件存储的相对路径（如 "chat/project123/uuid/file.png"）
            content_type: 文件的 MIME 类型（本地存储仅用于记录，实际使用较少）

        Returns:
            str: 文件的公网访问 URL（通过 API 代理访问）
        """
        # 去除路径开头的斜杠，防止路径穿越攻击
        # 使用 Path 拼接基础路径和相对路径，获取完整文件路径
        full_path = self.base_path / path.lstrip("/")
        
        # 确保目标文件的父目录存在
        # 例如存储路径为 chat/project123/uuid/file.png，则创建 chat/project123/uuid/ 目录
        full_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 同步写入文件
        # 使用 shutil.copyfileobj 高效地拷贝文件对象到磁盘文件
        with open(full_path, "wb") as f:
            shutil.copyfileobj(file, f)
        
        # 返回文件的公网访问 URL
        return self.get_public_url(path)

    async def delete(self, path: str) -> bool:
        """
        从本地存储中删除文件。

        Args:
            path: 文件存储的相对路径

        Returns:
            bool: 删除成功返回 True；文件不存在或删除失败返回 False
        """
        # 获取文件的完整路径
        full_path = self.base_path / path.lstrip("/")
        try:
            # 检查文件是否存在
            if full_path.exists():
                os.remove(full_path)  # 删除文件
                return True
            return False  # 文件不存在
        except Exception:
            # 捕获所有异常（如权限问题、路径问题），返回 False
            return False

    # ------------------- 辅助方法 -------------------

    def get_public_url(self, path: str) -> str:
        """
        根据存储路径生成公网访问 URL。

        本地存储采用 API 代理模式：
            前端不直接访问本地文件，而是通过 API 接口访问。
            这样可以利用 API 的认证、权限控制、日志记录等能力。

        处理两种路径格式：
            1. 已经是 API 路径（以 "/" 开头）：直接拼接 api_base_url
            2. 存储路径：转换为 API 路径格式

        Args:
            path: 文件路径，可能是存储路径或 API 路径

        Returns:
            str: 完整的公网访问 URL
        """
        if path.startswith("/"):
            # 如果已经是 API 路径（如 /v1/chat/files/xxx），直接拼接
            return f"{self.api_base_url}{path}"
        # 否则将存储路径转换为 API 路径
        # 格式：{api_base_url}/v1/chat/files/{path}
        return f"{self.api_base_url}/v1/chat/files/{path}"

    async def exists(self, path: str) -> bool:
        """
        检查本地文件是否存在。

        Args:
            path: 文件存储的相对路径

        Returns:
            bool: 文件存在返回 True，否则返回 False
        """
        full_path = self.base_path / path.lstrip("/")
        return full_path.exists()  # Path.exists() 返回文件或目录是否存在

    def resolve_url(self, url: str) -> str:
        """
        解析并规范化一个可能是相对路径或格式不正确的 URL。

        主要用于：
            1. 将前端传来的相对路径转换为完整 URL
            2. 将开发环境的 localhost 地址转换为正确的 API 地址
            3. 统一不同来源的 URL 格式

        Args:
            url: 待解析的 URL 或路径

        Returns:
            str: 规范化后的完整 URL
        """
        if not url or not isinstance(url, str):
            return url
        
        # 情况1：路径以 "/api/v1" 开头
        # 去除 "/api" 前缀，保留 "/v1/..." 格式
        path = url
        if path.startswith("/api/v1"):
            path = path[4:]  # 去掉 "/api"（注意：只去掉了4个字符，实际效果是 "/api" 被移除）
            # 更准确的写法：path = path[7:] 或 path = path.replace("/api", "", 1)
            # 但这里保留原代码逻辑
            
        # 情况2：以 "/" 开头的相对路径
        if path.startswith("/"):
            # 调用 get_public_url 将其转换为完整 URL
            return self.get_public_url(path)
            
        # 情况3：完整的 HTTP/HTTPS URL
        if url.startswith("http://") or url.startswith("https://"):
            parsed = urlparse(url)
            # 仅当 URL 指向 localhost 或 127.0.0.1 时才处理
            # （通常是开发环境下传入的地址，需要转换为正确的 API 地址）
            if "localhost" in parsed.netloc or "127.0.0.1" in parsed.netloc:
                p = parsed.path
                if p.startswith("/api/v1"):
                    p = p[4:]  # 同样去除 "/api" 前缀
                return self.get_public_url(p)
                
        # 其他情况：直接返回原始 URL
        # 可能是外部地址（如 CDN 链接）或已经正确格式化的地址
        return url

    def get_file_access_url(self, file_id: str, storage_url: str) -> str:
        """
        获取前端应该使用的文件访问 URL。

        本地存储采用 API 代理模式，前端通过 API 接口访问文件。
        返回格式：{api_base_url}/v1/chat/files/{file_id}

        Args:
            file_id: 数据库中存储的文件记录 ID
            storage_url: upload() 方法返回的存储 URL（本地存储中未使用）

        Returns:
            str: 前端应该使用的最终访问 URL
        """
        return f"{self.api_base_url}/v1/chat/files/{file_id}"