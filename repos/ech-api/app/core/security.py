"""
安全工具模块：统一提供认证与授权能力
涵盖：JWT令牌管理、密码哈希校验、用户身份认证、项目级认证、RBAC权限校验、API密钥生成
"""

from datetime import datetime, timedelta  # 处理JWT过期时间计算
from typing import Any, Dict, Literal, Optional, Union  # 类型注解，提升代码可维护性与类型检查
from uuid import UUID  # 兼容UUID类型的项目ID/用户ID

# FastAPI 核心组件：依赖注入、请求头解析、HTTP异常、标准状态码、Bearer认证方案
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# JWT 编解码与异常处理（python-jose库）
from jose import JWTError, jwt
# 密码哈希库，支持bcrypt等安全算法
from passlib.context import CryptContext
# SQLAlchemy 数据库会话
from sqlalchemy.orm import Session

# 项目内部模块导入
from app.core.config import settings       # 全局配置（密钥、算法、过期时间等）
from app.core.database import get_db       # 数据库会话依赖生成器
from app.core.logging import get_logger    # 日志实例工厂
from app.models import Project, Staff, Permission, RolePermission, ProjectRolePermission  # 数据模型

# 初始化模块专属日志器
logger = get_logger("security")


# ===================== 常量定义 =====================
# 管理员角色标识：管理员默认拥有全部权限，用于快速权限短路判断
ADMIN_ROLE = "admin"

# 用户支持的语言类型：字面量类型限制取值范围，用于国际化
UserLanguage = Literal["zh", "en"]
DEFAULT_LANGUAGE: UserLanguage = "en"  # 默认语言为英文


# ===================== 语言解析依赖 =====================
def get_user_language(
    x_user_language: Optional[str] = Header(None, alias="x-user-language"),
) -> UserLanguage:
    """
    从请求头中解析用户语言偏好，作为FastAPI依赖注入使用
    
    Args:
        x_user_language: HTTP请求头 x-user-language 的值，通过alias映射蛇形命名变量
        Header(None) 表示该头非必填，无则返回None

    Returns:
        中文返回 "zh"，其他情况默认返回 "en"
    """
    # 不区分大小写匹配中文
    if x_user_language and x_user_language.lower() == "zh":
        return "zh"
    # 非法值/空值均返回默认英文
    return "en"


# ===================== 密码哈希工具 =====================
# 密码哈希上下文：全局单例，避免重复初始化
pwd_context = CryptContext(
    schemes=["bcrypt"],       # 使用bcrypt算法（行业标准，自带盐值、抗彩虹表）
    deprecated="auto",        # 自动标记旧算法为废弃，兼容历史哈希值
    bcrypt__rounds=12         # bcrypt计算轮数：12是安全与性能的平衡值，越高越慢越安全
)


# ===================== JWT 认证基础配置 =====================
# HTTP Bearer 认证方案：自动解析 Authorization: Bearer <token> 请求头
# 格式错误时自动返回401，无需手动处理
security = HTTPBearer()


# ===================== JWT 令牌生成 =====================
def create_access_token(
    subject: Union[str, Any],
    project_id: Optional[Union[str, UUID]] = None,
    role: Optional[str] = None,
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    生成JWT访问令牌，可携带项目ID与角色信息
    
    Args:
        subject: 令牌主体，通常为用户名/用户ID，唯一标识用户
        project_id: 可选，项目ID，写入令牌claim，用于项目级权限
        role: 可选，用户角色，写入令牌claim
        expires_delta: 可选，自定义过期时长；不填则使用配置默认值

    Returns:
        编码后的JWT字符串
    """
    # 计算过期时间：统一使用UTC时间，避免时区问题
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

    # JWT Payload 基础字段
    to_encode = {"exp": expire, "sub": str(subject)}

    # 可选claim：项目ID，转字符串保证JSON可序列化
    if project_id:
        to_encode["project_id"] = str(project_id)
    
    # 可选claim：角色
    if role:
        to_encode["role"] = role

    # 使用配置中的密钥+算法签名并编码
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


# ===================== 密码校验与哈希 =====================
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    校验明文密码与哈希值是否匹配
    
    Args:
        plain_password: 用户输入的明文密码
        hashed_password: 数据库中存储的哈希值

    Returns:
        匹配返回True，不匹配返回False
    """
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    生成密码哈希值，用户注册/修改密码时调用
    
    Args:
        password: 明文密码

    Returns:
        bcrypt哈希字符串
    """
    return pwd_context.hash(password)


# ===================== JWT 令牌校验 =====================
def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """
    验证JWT令牌有效性并返回解码后的payload
    静默失败模式：验证失败返回None而非抛出异常，适合非强制登录场景
    
    Args:
        token: JWT令牌字符串

    Returns:
        验证成功返回payload字典；失败返回None
    """
    try:
        # 解码并验证签名、过期时间
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        return payload
    except JWTError as e:
        # 使用debug级别日志，避免未认证接口产生大量噪音日志
        # 包含签名错误、过期、格式错误、篡改等所有JWT相关异常
        logger.debug(f"Token verification failed: {e}")
        return None


# ===================== 当前用户认证依赖 =====================
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> Staff:
    """
    FastAPI依赖：从JWT令牌获取当前已认证用户
    认证失败直接抛出401异常，阻断请求
    
    Args:
        credentials: Bearer令牌凭证，由security依赖自动解析
        db: 数据库会话，由get_db依赖注入

    Returns:
        Staff对象：当前登录的员工用户

    Raises:
        HTTPException 401: 令牌无效、用户不存在等认证失败场景
    """
    # 预定义401异常，符合HTTP规范，携带WWW-Authenticate头告知客户端认证方式
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # 验证令牌并获取payload
        payload = verify_token(credentials.credentials)
        if payload is None:
            logger.info("Token verification failed: No credentials provided")
            raise credentials_exception
        
        # 提取主体（用户名）
        username: str = payload.get("sub")
        if username is None:
            logger.info("Token verification failed: No subject provided")
            raise credentials_exception
            
    except JWTError:
        # 兜底异常捕获（verify_token已捕获JWTError，此处为冗余保险）
        logger.info("Token verification failed: JWTError")
        raise credentials_exception
    
    # 从数据库查询用户：匹配用户名 + 未软删除（deleted_at为空）
    user = db.query(Staff).filter(
        Staff.username == username,
        Staff.deleted_at.is_(None)
    ).first()
    
    if user is None:
        logger.info("Token verification failed: User not found")
        raise credentials_exception
    
    return user


# ===================== 活跃用户校验依赖 =====================
async def get_current_active_user(
    current_user: Staff = Depends(get_current_user),
) -> Staff:
    """
    FastAPI依赖：校验当前用户是否为活跃状态
    基于get_current_user，额外增加启用状态校验
    
    Args:
        current_user: 已认证的用户对象

    Returns:
        活跃的Staff对象

    Raises:
        HTTPException 400: 用户已被禁用/软删除
    """
    # 软删除标记非空表示用户已停用
    if current_user.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    return current_user


# ===================== 用户名密码认证 =====================
def authenticate_user(db: Session, username: str, password: str) -> Optional[Staff]:
    """
    用户名+密码认证，登录接口专用
    同步函数，直接在登录业务逻辑中调用，不作为FastAPI依赖
    
    Args:
        db: 数据库会话
        username: 用户名
        password: 明文密码

    Returns:
        认证成功返回Staff对象；失败返回None
    """
    # 第一步：按用户名查询未删除的用户
    user = db.query(Staff).filter(
        Staff.username == username,
        Staff.deleted_at.is_(None)
    ).first()
    
    # 用户不存在直接返回
    if not user:
        return None
    
    # 第二步：校验密码
    if not verify_password(password, user.password_hash):
        return None
    
    return user


# ===================== 项目查询工具 =====================
def get_project_by_id(db: Session, project_id: Union[str, UUID]) -> Optional[Project]:
    """
    根据ID查询项目（过滤已软删除项），通用工具函数
    
    Args:
        db: 数据库会话
        project_id: 项目ID，支持字符串或UUID

    Returns:
        Project对象或None
    """
    return db.query(Project).filter(
        Project.id == str(project_id),
        Project.deleted_at.is_(None)
    ).first()


# ===================== API密钥生成 =====================
def generate_api_key() -> str:
    """
    生成安全的API密钥
    使用secrets模块（密码学安全随机数），比random更适合密钥场景
    
    Returns:
        带前缀的32位随机字符API密钥，格式：ak_live_xxxxxxxx...
    """
    import secrets  # 延迟导入，仅生成密钥时加载
    import string

    # 字符集：大小写字母 + 数字
    alphabet = string.ascii_letters + string.digits
    # 前缀标识密钥类型与环境（live生产环境），便于排查与识别
    api_key = "ak_live_" + "".join(secrets.choice(alphabet) for _ in range(32))
    return api_key


# ===================== 项目级认证依赖 =====================
async def get_authenticated_project(
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer(auto_error=True)),
    db: Session = Depends(get_db),
) -> tuple[Project, str]:
    """
    FastAPI依赖：JWT认证并返回关联项目 + 下游转发用API密钥
    支持两种认证模式：
    1. 纯项目令牌：JWT payload直接携带project_id
    2. 用户令牌：通过用户信息关联到所属项目（降级方案）

    注意：返回的api_key_for_forwarding是用于调用下游AI/RAG服务的凭证，
    并非本服务(tgo-api)的认证密钥。
    
    Args:
        credentials: Bearer令牌凭证
        db: 数据库会话

    Returns:
        元组 (项目对象, 下游服务转发用API密钥)

    Raises:
        HTTPException 401: 令牌无效、无项目信息、项目不存在
    """
    # ========== 1. 验证JWT令牌 ==========
    payload = verify_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid JWT token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ========== 2. 提取项目ID ==========
    project_id = payload.get("project_id")
    
    # 降级逻辑：令牌无project_id时，通过用户名查用户关联的项目
    if not project_id:
        username = payload.get("sub")
        if username:
            user = db.query(Staff).filter(
                Staff.username == username,
                Staff.deleted_at.is_(None)
            ).first()
            if user:
                project_id = user.project_id

    # 仍无项目ID则认证失败
    if not project_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No project information in JWT token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ========== 3. 查询项目实体 ==========
    project = get_project_by_id(db, project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Project not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ========== 4. 取出下游转发密钥 ==========
    api_key_for_forwarding = project.api_key
    logger.debug(f"Authenticated via JWT for project: {project.id}")

    return project, api_key_for_forwarding


# ===================== 权限校验核心逻辑 =====================
def check_user_permission(
    db: Session,
    user: Staff,
    permission: str,
) -> bool:
    """
    检查用户是否拥有指定权限，采用 **MERGE合并模式**：
    最终权限 = 全局角色权限(RolePermission) + 项目级角色权限(ProjectRolePermission)
    项目只能追加权限，不能收回全局已授予的权限
    
    Args:
        db: 数据库会话
        user: 待校验的员工用户
        permission: 权限编码，格式为 resource:action（如 staff:create）

    Returns:
        有权限返回True，无权限返回False
    """
    # 管理员短路：直接拥有所有权限
    if user.role == ADMIN_ROLE:
        return True
    
    # 解析权限编码：拆分资源与操作
    try:
        resource, action = permission.split(":")
    except ValueError:
        # 格式非法记录警告，返回无权限
        logger.warning(f"Invalid permission format: {permission}")
        return False
    
    # ========== 第一步：校验全局角色权限 ==========
    # 多表关联：RolePermission 关联 Permission 表，匹配角色+资源+操作
    has_global_permission = db.query(RolePermission).join(Permission).filter(
        RolePermission.role == user.role,
        Permission.resource == resource,
        Permission.action == action,
    ).first()
    
    if has_global_permission:
        return True
    
    # ========== 第二步：校验项目级角色权限（追加权限） ==========
    has_project_permission = db.query(ProjectRolePermission).join(Permission).filter(
        ProjectRolePermission.role == user.role,
        ProjectRolePermission.project_id == user.project_id,
        Permission.resource == resource,
        Permission.action == action,
    ).first()
    
    # 项目权限存在则返回True，否则False
    return has_project_permission is not None


# ===================== 权限依赖工厂 =====================
def require_permission(permission: str):
    """
    权限依赖工厂：生成FastAPI依赖函数，用于接口级权限控制
    高阶函数，接收权限编码，返回一个可注入的依赖函数
    依赖内部完成：令牌认证 → 用户查询 → 状态校验 → 权限校验
    
    Args:
        permission: 权限编码，格式 resource:action

    Returns:
        FastAPI依赖函数，校验通过返回当前用户
    
    使用示例：
        @router.post("/staff")
        async def create_staff(
            current_user: Staff = Depends(require_permission("staff:create")),
        ):
            # 只有staff:create权限的用户可访问
            pass
    """
    async def permission_dependency(
        credentials: HTTPAuthorizationCredentials = Depends(security),
        db: Session = Depends(get_db),
    ) -> Staff:
        """内部依赖函数：执行完整的认证+授权流程"""
        # 定义401认证异常
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
        # ========== 1. JWT认证 ==========
        try:
            payload = verify_token(credentials.credentials)
            if payload is None:
                raise credentials_exception
            
            username: str = payload.get("sub")
            if username is None:
                raise credentials_exception
                
        except JWTError:
            raise credentials_exception
        
        # ========== 2. 查询用户 ==========
        user = db.query(Staff).filter(
            Staff.username == username,
            Staff.deleted_at.is_(None)
        ).first()
        
        if user is None:
            raise credentials_exception
        
        # ========== 3. 校验用户活跃状态 ==========
        if user.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Inactive user"
            )
        
        # ========== 4. 权限校验 ==========
        if not check_user_permission(db, user, permission):
            logger.warning(
                f"Permission denied: user {user.username} lacks permission {permission}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission}"
            )
        
        return user
    
    return permission_dependency


# ===================== 管理员依赖工厂 =====================
def require_admin():
    """
    管理员权限依赖工厂：便捷方法，等价于 require_permission 的管理员特化版
    复用 get_current_active_user 依赖，仅额外校验管理员角色
    
    Returns:
        FastAPI依赖函数，校验通过返回当前管理员用户
    
    使用示例：
        @router.delete("/staff/{staff_id}")
        async def delete_staff(
            current_user: Staff = Depends(require_admin()),
        ):
            # 仅管理员可访问
            pass
    """
    async def admin_dependency(
        current_user: Staff = Depends(get_current_active_user),
    ) -> Staff:
        """内部依赖：校验用户是否为管理员"""
        if current_user.role != ADMIN_ROLE:
            logger.warning(
                f"Admin required: user {current_user.username} is not admin"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin permission required"
            )
        return current_user
    
    return admin_dependency