"""Development data initialization for easier testing and debugging."""
# 开发环境初始化种子数据模块
# 职责：权限表初始化种子、项目级权限辅助函数、服务启动Banner打印
# 幂等设计：重复执行不会重复插入数据；启动时调用 ensure_permissions_seed 初始化基础权限
import logging
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import startup_log
from app.core.security import get_password_hash
from app.models.project import Project
from app.models.staff import Staff, StaffRole, StaffStatus
from app.models.permission import Permission, RolePermission, ProjectRolePermission

# 模块日志器，标记来源 app.core.dev_data
logger = logging.getLogger("app.core.dev_data")


# Default permission definitions: (resource, action, description)
# 【全局权限定义池】
# 元组格式：(资源名, 操作动作, 描述)
# api_permissions 表的原始数据源；所有业务权限全部在这里统一维护
DEFAULT_PERMISSIONS: List[Tuple[str, str, str]] = [
    # Staff permissions 坐席管理权限
    ("staff", "create", "Create new staff members"),
    ("staff", "read", "View staff member details"),
    ("staff", "update", "Update staff member information"),
    ("staff", "delete", "Delete staff members"),
    ("staff", "list", "List all staff members"),

    # Visitor permissions 访客管理权限
    ("visitors", "create", "Create new visitors"),
    ("visitors", "read", "View visitor details"),
    ("visitors", "update", "Update visitor information"),
    ("visitors", "delete", "Delete visitors"),
    ("visitors", "list", "List all visitors"),

    # Visitor Assignment Rules permissions 访客分配规则
    ("visitor_assignment_rules", "read", "View visitor assignment rule"),
    ("visitor_assignment_rules", "update", "Update visitor assignment rule"),

    # Chat permissions 聊天会话权限
    ("chat", "read", "Read chat messages"),
    ("chat", "send", "Send chat messages"),

    # AI Agents permissions AI智能体
    ("ai_agents", "create", "Create AI agents"),
    ("ai_agents", "read", "View AI agent details"),
    ("ai_agents", "update", "Update AI agents"),
    ("ai_agents", "delete", "Delete AI agents"),
    ("ai_agents", "list", "List all AI agents"),

    # RAG Collections permissions RAG知识库集合
    ("rag_collections", "create", "Create RAG collections"),
    ("rag_collections", "read", "View RAG collection details"),
    ("rag_collections", "update", "Update RAG collections"),
    ("rag_collections", "delete", "Delete RAG collections"),
    ("rag_collections", "list", "List all RAG collections"),

    # RAG Files permissions RAG文档文件
    ("rag_files", "create", "Upload RAG files"),
    ("rag_files", "read", "View RAG file details"),
    ("rag_files", "delete", "Delete RAG files"),
    ("rag_files", "list", "List all RAG files"),

    # Tags permissions 标签管理
    ("tags", "create", "Create tags"),
    ("tags", "read", "View tag details"),
    ("tags", "update", "Update tags"),
    ("tags", "delete", "Delete tags"),
    ("tags", "list", "List all tags"),

    # Platforms permissions 渠道平台
    ("platforms", "create", "Create platforms"),
    ("platforms", "read", "View platform details"),
    ("platforms", "update", "Update platforms"),
    ("platforms", "delete", "Delete platforms"),
    ("platforms", "list", "List all platforms"),

    # Permissions management (admin only by design) 权限管理，仅管理员
    ("permissions", "read", "View permission definitions"),
    ("permissions", "manage", "Manage role permissions"),
]


# Default GLOBAL permissions for 'user' role - inherited by ALL projects
# 【全局角色默认权限】user角色，所有项目自动继承
# 新增权限只维护此列表；全局权限是基础，项目可以在此基础上叠加 ProjectRolePermission，不能削减全局权限
DEFAULT_USER_GLOBAL_PERMISSIONS: List[Tuple[str, str]] = [
    # Users can view staff list but not manage
    ("staff", "read"),
    ("staff", "list"),

    # Users have full visitor access
    ("visitors", "create"),
    ("visitors", "read"),
    ("visitors", "update"),
    ("visitors", "list"),

    # Users can view visitor assignment rules but not manage
    ("visitor_assignment_rules", "read"),

    # Users can chat
    ("chat", "read"),
    ("chat", "send"),

    # Users can view AI agents but not manage
    ("ai_agents", "read"),
    ("ai_agents", "list"),

    # Users can view RAG but not manage
    ("rag_collections", "read"),
    ("rag_collections", "list"),
    ("rag_files", "read"),
    ("rag_files", "list"),

    # Users can manage tags
    ("tags", "create"),
    ("tags", "read"),
    ("tags", "update"),
    ("tags", "delete"),
    ("tags", "list"),

    # Users can view platforms but not manage
    ("platforms", "read"),
    ("platforms", "list"),
]


def ensure_permissions_seed(db: Optional[Session] = None) -> None:
    """
    Ensure default permissions are seeded in the database.
    权限初始化种子函数，**幂等函数，可重复调用**；只插入不存在记录，不会覆盖已有数据

    This function seeds:
    1. Permission definitions (api_permissions table) 权限定义表，resource+action的全集
    2. Global role permissions (api_role_permissions table) - inherited by all projects
       全局角色权限表：user角色拥有哪些基础权限，所有租户项目自动继承

    Args:
        db: 可选外部session；不传函数内部会新建SessionLocal，执行完毕自动关闭
    """
    close_session = False
    # 如果外部没有传入db会话，则内部创建，标记执行完需要关闭
    if db is None:
        db = SessionLocal()
        close_session = True

    try:
        # Step 1: 初始化权限定义池 api_permissions
        for resource, action, description in DEFAULT_PERMISSIONS:
            # 根据 resource + action 联合唯一键判断记录是否已存在
            existing = db.query(Permission).filter(
                Permission.resource == resource,
                Permission.action == action,
            ).first()

            if not existing:
                permission = Permission(
                    resource=resource,
                    action=action,
                    description=description,
                )
                db.add(permission)
                logger.info(f"Created permission: {resource}:{action}")
        # 批量提交权限定义
        db.commit()
        logger.info("Permission definitions seeded successfully")

        # Step 2: 初始化全局user角色权限 api_role_permissions
        # 全局权限，全部项目都会继承这套基础权限
        all_permissions = db.query(Permission).all()
        # 构建 {(resource, action): permission_id} 的映射字典，方便快速查找id
        permission_map = {
            (p.resource, p.action): p.id for p in all_permissions
        }

        for resource, action in DEFAULT_USER_GLOBAL_PERMISSIONS:
            permission_id = permission_map.get((resource, action))
            if not permission_id:
                # 配置和数据库不一致，打印告警，跳过，不阻断流程
                logger.warning(f"Permission not found for global role: {resource}:{action}")
                continue

            # 判断该全局角色权限是否已存在：role + permission_id
            existing = db.query(RolePermission).filter(
                RolePermission.role == "user",
                RolePermission.permission_id == permission_id,
            ).first()

            if not existing:
                role_permission = RolePermission(
                    role="user",
                    permission_id=permission_id,
                )
                db.add(role_permission)
                logger.debug(f"Created global user role permission: {resource}:{action}")

        db.commit()
        logger.info("Global role permissions seeded successfully")

    except Exception as e:
        logger.error(f"Failed to seed permissions: {e}")
        db.rollback()  # 异常回滚事务
        raise  # 向上抛出异常，启动流程感知初始化失败
    finally:
        # 如果session是函数内部创建，则关闭会话；外部传入的session交给调用方管理
        if close_session:
            db.close()


def add_project_role_permission(
    project_id: UUID,
    role: str,
    resource: str,
    action: str,
    db: Optional[Session] = None,
) -> bool:
    """
    Add a project-specific permission for a role.
    给【单个项目(租户)】角色追加项目专属权限；叠加在全局权限之上
    > 重要业务规则：项目只能增加额外权限，**不能删除/覆盖全局继承权限**

    Args:
        project_id: 项目UUID
        role: 角色名称，如 user / agent
        resource: 资源名称，和Permission.resource一致
        action: 操作动作，和Permission.action一致
        db: 可选外部数据库session

    Returns:
        True: 成功新增；False: 记录已存在 / permission找不到
    """
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True

    try:
        # 查找基础权限定义
        permission = db.query(Permission).filter(
            Permission.resource == resource,
            Permission.action == action,
        ).first()

        if not permission:
            logger.warning(f"Permission not found: {resource}:{action}")
            return False

        # 联合唯一：project_id + role + permission_id
        existing = db.query(ProjectRolePermission).filter(
            ProjectRolePermission.role == role,
            ProjectRolePermission.permission_id == permission.id,
            ProjectRolePermission.project_id == project_id,
        ).first()

        if existing:
            # 该项目角色已经拥有此权限，直接返回False，不重复插入
            return False

        # 创建项目级附加权限
        project_permission = ProjectRolePermission(
            role=role,
            permission_id=permission.id,
            project_id=project_id,
        )
        db.add(project_permission)
        db.commit()

        logger.info(f"Added project permission {resource}:{action} for role {role} in project {project_id}")
        return True

    except Exception as e:
        logger.error(f"Failed to add project role permission: {e}")
        db.rollback()
        raise
    finally:
        if close_session:
            db.close()


def log_startup_banner() -> None:
    """Log beautiful startup banner. 打印服务启动的ASCII banner，使用专用startup_log日志输出"""
    startup_log("╔══════════════════════════════════════════════════════════════╗")
    startup_log("║                    🚀 TGO API Service                        ║")
    startup_log("║                  Core Business Logic Service                 ║")
    startup_log("╚══════════════════════════════════════════════════════════════╝")
    startup_log("")
    startup_log(f"📦 Version: {settings.PROJECT_VERSION}")
    startup_log(f"🌍 Environment: {settings.ENVIRONMENT.upper()}")
    startup_log("")