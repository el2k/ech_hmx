"""JWT token handling for service‑to‑service authentication."""
# 模块说明：服务与服务之间互相调用的JWT鉴权工具（服务间通信token，不是用户登录token）

import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional

from jose import JWTError, jwt   # jose库：python JWT编解码库
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.exceptions import AuthenticationError
from app.models.project import Project


def create_access_token(data: Dict[str, str], expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token.
    
    Args:
        data: Data to encode in the token  需要放进令牌的业务载荷字典
        expires_delta: Token expiration time 自定义过期时长，不传就用配置默认值
        
    Returns:
        Encoded JWT token 返回生成完成的jwt字符串
    """
    # 拷贝一份，避免修改外部传入的原始字典
    to_encode = data.copy()

    # 判断是否传入自定义过期时间
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        # 读取配置文件里的默认过期分钟数
        expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    
    # 把过期时间exp写入jwt载荷，exp是JWT标准字段，解码器会自动校验是否过期
    to_encode.update({"exp": expire})

    # 使用项目密钥 + 指定加密算法，把to_encode字典编码成JWT字符串
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt


def verify_token(token: str) -> Dict[str, str]:
    """
    Verify and decode a JWT token.
    
    Args:
        token: JWT token to verify 传入待校验的jwt字符串
        
    Returns:
        Decoded token payload 解码后的载荷字典
        
    Raises:
        AuthenticationError: If token is invalid 令牌任意异常统一抛自定义鉴权异常
    """
    try:
        # 解码+校验：校验签名、校验exp过期时间；算法必须和签发时一致
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return payload
    except JWTError as e:
        # 捕获所有JWT异常：签名错误、过期、格式错误、算法不匹配全部走到这里
        raise AuthenticationError(f"Invalid token: {str(e)}")


async def get_project_from_jwt(token: str, db: AsyncSession) -> Project:
    """
    Get project from JWT token.
    完整流程：校验JWT → 取出project_id → 查询数据库，返回真实Project数据库对象
    
    Args:
        token: JWT token
        db: Database session 异步数据库会话
        
    Returns:
        Project associated with the token
        
    Raises:
        AuthenticationError: If token is invalid or project not found
    """
    # 第一步：调用上面函数完成签名、过期校验，拿到payload载荷
    payload = verify_token(token)
    
    # 从token里面取出project_id字段，这个是服务间token约定的业务字段
    project_id_str = payload.get("project_id")
    if not project_id_str:
        raise AuthenticationError("Token missing project_id claim")
    
    # 字符串转UUID类型，数据库主键是uuid格式，格式不对直接抛异常
    try:
        project_id = uuid.UUID(project_id_str)
    except ValueError:
        raise AuthenticationError("Invalid project_id format in token")
    
    # 根据uuid查询数据库Project表
    project = await db.get(Project, project_id)
    if not project:
        raise AuthenticationError("Project not found")
    
    # 额外业务校验：项目已经被软删除，禁止访问
    if project.is_deleted:
        raise AuthenticationError("Project is deleted")
    
    # 全部校验通过，返回数据库ORM模型对象，上层接口可以直接拿project做权限判断
    return project