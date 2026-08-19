"""Setup endpoints for system initialization."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.core.security import generate_api_key, get_password_hash
from app.models import (
    AIProvider,
    Platform,
    PlatformType,
    PlatformTypeDefinition,
    Project,
    Staff,
    SystemSetup,
    VisitorAssignmentRule,
)
from app.models.staff import StaffRole, StaffStatus
from app.schemas.setup import (
    BatchCreateStaffRequest,
    BatchCreateStaffResponse,
    ConfigureLLMRequest,
    ConfigureLLMResponse,
    CreateAdminRequest,
    CreateAdminResponse,
    SetupCheckResult,
    SetupStatusResponse,
    SkipLLMConfigResponse,
    StaffCreatedItem,
    VerifySetupResponse,
)
from app.services.ai_client import ai_client
from app.services.ai_provider_default_models import resolve_initial_model_seeds
from app.services.wukongim_client import wukongim_client
from app.utils.const import CHANNEL_TYPE_PROJECT_STAFF, SETUP_DEFAULT_AGENT_MODEL
from app.utils.crypto import encrypt_str
from app.utils.encoding import build_project_staff_channel_id

logger = get_logger("endpoints.setup")

router = APIRouter()
'''
本模块是系统首次部署安装向导的后端 API 实现，基于 FastAPI + SQLAlchemy 异步架构，负责系统初始化全流程管控。
核心设计思想：
单例状态管控：通过 SystemSetup 数据库表单行记录全局安装状态，保证全系统唯一
阶段式安装：分为「创建管理员 → 配置 LLM / 跳过 LLM → 安装完成」三个阶段，状态自动流转
安全闭锁：系统安装完成后，所有初始化接口自动禁用（返回 403），防止未授权重入
事务一致性：跨服务操作（数据库 + AI 服务 + IM 服务）失败时自动回滚数据库
幂等设计：重复调用初始化接口不会重复创建数据，保证操作安全
'''
def _get_or_create_system_setup(db: Session) -> SystemSetup:
    """获取系统配置单例记录，不存在则自动创建。
    
    核心作用：保证 SystemSetup 表永远有且仅有一行记录，作为全局安装状态的唯一数据源。
    按创建时间升序取第一条，确保始终拿到最早的那条单例记录。
    """
    # 按创建时间正序，取第一条记录（单例表理论上只有一条）
    setup = db.query(SystemSetup).order_by(SystemSetup.created_at.asc()).first()
    
    # 记录不存在，创建初始化单例
    if setup is None:
        # 显式赋值时间戳，避免数据库无默认值时 NOT NULL 约束报错
        now = datetime.now(timezone.utc)
        setup = SystemSetup(
            is_installed=False,       # 系统是否安装完成
            admin_created=False,      # 管理员账号是否已创建
            llm_configured=False,     # LLM服务商是否已配置
            skip_llm_config=False,    # 是否跳过LLM配置步骤
            setup_version="v1",       # 安装配置版本号
            created_at=now,
            updated_at=now,
        )
        db.add(setup)
        db.commit()       # 提交事务持久化
        db.refresh(setup) # 刷新对象，获取数据库生成的字段（如ID）
    
    return setup


def _recalculate_install_flags(setup: SystemSetup) -> None:
    """重新计算并更新系统安装完成标志。
    
    安装完成判定规则：
    管理员已创建 AND (大模型已配置 OR 已跳过LLM配置)
    满足条件时自动标记 is_installed=True，并记录完成时间。
    """
    # 计算安装完成状态
    is_installed = setup.admin_created and (setup.llm_configured or setup.skip_llm_config)
    
    # 状态发生变化时才更新
    if setup.is_installed != is_installed:
        setup.is_installed = is_installed
        # 首次变为已安装状态，记录完成时间戳
        if is_installed and setup.setup_completed_at is None:
            setup.setup_completed_at = datetime.now(timezone.utc)


def _check_system_installed(db: Session) -> tuple[bool, bool, bool, bool, bool]:
    """检查系统安装状态，返回多维度状态元组。
    
    返回值顺序：
    (是否安装完成, 是否有管理员, 是否有普通坐席, 是否配置LLM, 是否跳过LLM)
    """
    # 确保单例记录存在
    setup = _get_or_create_system_setup(db)
    # 重新计算安装标志（避免数据不一致）
    _recalculate_install_flags(setup)
    db.commit()
    db.refresh(setup)
    
    # 检查是否存在普通角色的坐席账号（非管理员）
    has_user_staff = db.query(Staff).filter(
        Staff.role == StaffRole.USER.value,
        Staff.deleted_at.is_(None),
    ).first() is not None
    
    return (
        setup.is_installed,
        setup.admin_created,
        has_user_staff,
        setup.llm_configured,
        setup.skip_llm_config
    )


def _get_setup_completed_time(db: Session) -> Optional[datetime]:
    """获取系统安装完成的时间戳，未完成返回None。"""
    setup = db.query(SystemSetup).order_by(SystemSetup.created_at.asc()).first()
    if not setup:
        return None
    return setup.setup_completed_at

@router.get(
    "/status",
    response_model=SetupStatusResponse,
    summary="查询系统安装状态",
    description="检查系统是否完成初始安装，返回安装进度各维度状态"
)
async def get_setup_status(
    db: Session = Depends(get_db),
) -> SetupStatusResponse:
    """
    系统安装状态查询接口，前端安装向导轮询此接口获取当前进度。
    返回信息包括：管理员是否存在、普通坐席是否存在、LLM是否配置、安装完成时间等。
    """
    # 获取安装各维度状态
    is_installed, has_admin, has_user_staff, has_llm_config, skip_llm_config = _check_system_installed(db)
    # 已安装才返回完成时间，未安装返回None
    setup_completed_at = _get_setup_completed_time(db) if is_installed else None

    logger.info(
        f"Setup status check: installed={is_installed}, "
        f"has_admin={has_admin}, has_user_staff={has_user_staff}, "
        f"has_llm={has_llm_config}, skip_llm={skip_llm_config}"
    )

    return SetupStatusResponse(
        is_installed=is_installed,
        has_admin=has_admin,
        has_user_staff=has_user_staff,
        has_llm_config=has_llm_config,
        skip_llm_config=skip_llm_config,
        setup_completed_at=setup_completed_at,
    )


# 固定管理员用户名，系统唯一超级管理员账号恒为 admin
ADMIN_USERNAME = "admin"
@router.post(
    "/admin",
    response_model=CreateAdminResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建首个管理员账号",
    description="创建系统第一个管理员账号和默认项目，用户名固定为admin，仅安装阶段可调用一次"
)
async def create_admin(
    admin_data: CreateAdminRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> CreateAdminResponse:
    """
    安装向导第一步：创建超级管理员。
    执行流程：
    1. 校验系统未安装、管理员不存在
    2. 创建默认项目
    3. 创建默认AI智能体
    4. 创建管理员账号
    5. 初始化各平台渠道配置
    6. 创建IM坐席频道并加入管理员
    7. 更新安装状态标志
    """
    # 确保单例存在
    setup = _get_or_create_system_setup(db)

    # ========== 幂等校验：管理员已存在则直接返回信息，不重复创建 ==========
    existing_admin = db.query(Staff).filter(
        Staff.username == ADMIN_USERNAME,
        Staff.deleted_at.is_(None)
    ).first()

    if existing_admin:
        project = existing_admin.project
        logger.info(
            f"Admin already exists, returning existing info for idempotency: {ADMIN_USERNAME}"
        )
        return CreateAdminResponse(
            id=existing_admin.id,
            username=ADMIN_USERNAME,
            nickname=existing_admin.nickname,
            project_id=project.id if project else existing_admin.project_id,
            project_name=project.name if project else "Unknown",
            created_at=existing_admin.created_at,
        )

    # ========== 安全校验：系统已安装则禁止调用 ==========
    if setup.is_installed:
        logger.warning(
            f"Attempt to call setup endpoint after installation is complete: {request.url.path}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System installation is already complete. Setup endpoints are disabled for security reasons.",
        )

    # ========== 步骤1：创建默认项目 ==========
    api_key = generate_api_key()  # 生成项目API密钥
    project = Project(
        name=admin_data.project_name,
        api_key=api_key,
    )
    db.add(project)
    db.flush()  # 预提交，获取项目ID，不真正提交事务，失败可回滚

    logger.info(f"Created default project: {project.name} (ID: {project.id})")

    # ========== 步骤2：创建默认AI智能体（占位模型，后续LLM配置后替换） ==========
    try:
        agent_data = {
            "name": "Tgo AI Agent",
            "model": SETUP_DEFAULT_AGENT_MODEL,  # 临时占位模型
            "is_default": True,
        }
        agent_result = await ai_client.create_agent(
            project_id=str(project.id),
            agent_data=agent_data,
        )
        default_agent_id = agent_result.get("id")
        if not default_agent_id:
            raise ValueError("AI service returned empty agent ID")
        logger.info(
            "Created default AI agent for project",
            extra={"project_id": str(project.id), "agent_id": default_agent_id},
        )
    except Exception as e:
        # AI服务调用失败，回滚数据库事务，保证数据一致性
        logger.error(
            f"Failed to create default AI agent: {e}",
            extra={"project_id": str(project.id)},
        )
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to create default AI agent: {e}. Please retry.",
        )

    # ========== 步骤3：创建管理员账号 ==========
    password_hash = get_password_hash(admin_data.password)  # 密码哈希存储

    admin = Staff(
        project_id=project.id,
        username=ADMIN_USERNAME,
        password_hash=password_hash,
        nickname=admin_data.nickname or "Administrator",
        name=admin_data.nickname or "Administrator",
        role=StaffRole.ADMIN,       # 管理员角色
        status=StaffStatus.OFFLINE, # 初始离线状态
    )
    db.add(admin)

    # ========== 步骤4：按平台类型定义，初始化项目下所有渠道 ==========
    platform_type_definitions = db.query(PlatformTypeDefinition).all()
    platforms: list[Platform] = []
    website_platform: Optional[Platform] = None

    if not platform_type_definitions:
        logger.error(
            "No platform type definitions found; skipping automatic platform and visitor creation",
            extra={"project_id": str(project.id)},
        )
    else:
        for pt_def in platform_type_definitions:
            platform = Platform(
                project_id=project.id,
                type=pt_def.type,
                api_key=generate_api_key(),
                config={},
                is_active=False,
            )
            
            # 网站渠道特殊处理：默认激活并预置前端配置
            if pt_def.type == PlatformType.WEBSITE.value:
                platform.config = {
                    "position": "bottom-right",
                    "welcome_message": "Hello! How can I help you today?",
                    "widget_title": "TGO AI Chatbot",
                }
                platform.is_active = True
                website_platform = platform
            
            db.add(platform)
            platforms.append(platform)

        db.flush()  # 预提交获取平台ID

        logger.info(
            "Created platforms for project from platform type definitions",
            extra={"project_id": str(project.id), "platform_count": len(platforms)},
        )

    db.flush()  # 预提交获取管理员ID，用于IM频道

    # ========== 步骤5：创建项目坐席IM频道，管理员加入频道 ==========
    try:
        channel_id = build_project_staff_channel_id(project.id)
        admin_uid = f"{admin.id}-staff"  # IM用户ID规则：坐席ID + -staff
        await wukongim_client.create_channel(
            channel_id=channel_id,
            channel_type=CHANNEL_TYPE_PROJECT_STAFF,
            subscribers=[admin_uid],
        )
        logger.info(
            "Created project staff channel",
            extra={
                "project_id": str(project.id),
                "channel_id": channel_id,
                "admin_uid": admin_uid,
            },
        )
    except Exception as e:
        logger.error(f"Failed to create project staff channel: {e}")
        db.rollback()  # IM创建失败，回滚全部数据库操作
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create project staff channel"
        )

    # ========== 步骤6：更新系统安装状态 ==========
    setup.admin_created = True
    # 用户选择跳过LLM配置的话，直接标记
    if admin_data.skip_llm_config:
        setup.skip_llm_config = True
    _recalculate_install_flags(setup)  # 重新计算是否安装完成

    # 正式提交所有事务
    db.commit()
    db.refresh(admin)
    db.refresh(project)
    db.refresh(setup)

    logger.info(
        f"Created first admin: {ADMIN_USERNAME} (ID: {admin.id}) for project {project.name}"
    )

    return CreateAdminResponse(
        id=admin.id,
        username=ADMIN_USERNAME,
        nickname=admin.nickname,
        project_id=project.id,
        project_name=project.name,
        created_at=admin.created_at,
    )
@router.post(
    "/llm-config",
    response_model=ConfigureLLMResponse,
    status_code=status.HTTP_201_CREATED,
    summary="配置大语言模型服务商",
    description="配置系统LLM服务商，需先创建管理员账号，安装完成后禁用"
)
async def configure_llm(
    llm_data: ConfigureLLMRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ConfigureLLMResponse:
    """
    安装向导第二步：配置大模型服务商。
    执行流程：
    1. 校验系统未安装、管理员已创建
    2. 解析并校验可用模型列表
    3. 创建LLM服务商配置（API密钥加密存储）
    4. 同步初始化模型列表到数据库
    5. 更新默认智能体的模型配置（替换占位模型）
    6. 更新安装状态标志
    """
    setup = _get_or_create_system_setup(db)

    # 安全校验：已安装禁止调用
    if setup.is_installed:
        logger.warning(
            f"Attempt to call setup endpoint after installation is complete: {request.url.path}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System installation is already complete. Setup endpoints are disabled for security reasons.",
        )

    has_admin = setup.admin_created
    # 前置校验：必须先创建管理员
    if not has_admin:
        logger.warning("Attempt to configure LLM before creating admin")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin account must be created before configuring LLM provider"
        )

    # 获取首个项目（创建管理员时生成）
    project = db.query(Project).filter(Project.deleted_at.is_(None)).first()
    if not project:
        logger.error("No project found despite admin existing")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="System error: No project found"
        )

    # 解析初始模型种子列表（用户指定或数据库默认）
    initial_model_seeds = resolve_initial_model_seeds(db, llm_data.provider, llm_data.available_models)
    initial_model_ids = [seed.model_id for seed in initial_model_seeds]

    # 校验默认模型必须在可用模型列表中
    if llm_data.default_model and llm_data.default_model not in initial_model_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="default_model must be in available_models list"
        )

    # ========== 创建LLM服务商配置 ==========
    ai_provider = AIProvider(
        project_id=project.id,
        provider=llm_data.provider,
        name=llm_data.name,
        api_key=encrypt_str(llm_data.api_key),  # API密钥加密存储
        api_base_url=llm_data.api_base_url,
        # 默认模型：用户指定 → 第一个可用模型 → None
        default_model=llm_data.default_model or (initial_model_ids[0] if initial_model_ids else None),
        config=llm_data.config,
        is_active=llm_data.is_active,
    )

    # 同步初始化模型记录到 AIModel 表
    from app.models import AIModel
    for seed in initial_model_seeds:
        m = AIModel(
            provider_id=ai_provider.id,
            provider=llm_data.provider,
            model_id=seed.model_id,
            model_name=seed.model_name,
            model_type=seed.model_type,
            is_active=True
        )
        ai_provider.models.append(m)

    db.add(ai_provider)

    # 更新安装状态
    setup.llm_configured = True
    setup.skip_llm_config = False  # 配置了LLM就取消跳过标记
    _recalculate_install_flags(setup)

    db.commit()
    db.refresh(ai_provider)
    db.refresh(setup)

    # ========== 替换默认智能体的占位模型 ==========
    if ai_provider.default_model:
        try:
            # 查询项目的默认智能体
            agents_result = await ai_client.list_agents(
                project_id=str(project.id),
                is_default=True,
                limit=1,
                offset=0,
            )
            agents = agents_result.get("data", []) if isinstance(agents_result, dict) else []
            if agents:
                default_agent = agents[0]
                default_agent_id = default_agent.get("id")
                # 确认是占位模型才替换
                if default_agent_id and default_agent.get("model") == SETUP_DEFAULT_AGENT_MODEL:
                    await ai_client.update_agent(
                        project_id=str(project.id),
                        agent_id=str(default_agent_id),
                        agent_data={"model": ai_provider.default_model},
                    )
                    logger.info(
                        "Updated bootstrap default agent model after LLM setup",
                        extra={
                            "project_id": str(project.id),
                            "agent_id": str(default_agent_id),
                            "model": ai_provider.default_model,
                        },
                    )
        except Exception as exc:
            # 更新智能体失败不影响主流程，仅打警告日志
            logger.warning(
                "Failed to update bootstrap default agent model after LLM setup",
                extra={"project_id": str(project.id), "error": str(exc)},
            )

    logger.info(
        f"Created LLM provider: {ai_provider.provider}/{ai_provider.name} "
        f"(ID: {ai_provider.id}) for project {project.id}"
    )

    return ConfigureLLMResponse(
        id=ai_provider.id,
        provider=ai_provider.provider,
        name=ai_provider.name,
        default_model=ai_provider.default_model,
        is_active=ai_provider.is_active,
        project_id=ai_provider.project_id,
        created_at=ai_provider.created_at,
    )
@router.post(
    "/skip-llm",
    response_model=SkipLLMConfigResponse,
    status_code=status.HTTP_200_OK,
    summary="安装时跳过LLM配置",
    description="跳过LLM配置步骤直接完成安装，后续可在管理后台再配置"
)
async def skip_llm_configuration(
    request: Request,
    db: Session = Depends(get_db),
) -> SkipLLMConfigResponse:
    """
    跳过LLM配置步骤，直接完成安装。
    前置条件：管理员已创建、未配置LLM、未跳过LLM。
    执行后标记 skip_llm_config=True，自动触发安装完成判定。
    """
    setup = _get_or_create_system_setup(db)

    # 安全校验：已安装禁止调用
    if setup.is_installed:
        logger.warning(
            f"Attempt to call setup endpoint after installation is complete: {request.url.path}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System installation is already complete. Setup endpoints are disabled for security reasons.",
        )

    # 前置校验1：必须先创建管理员
    if not setup.admin_created:
        logger.warning("Attempt to skip LLM config before admin is created")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin account must be created first",
        )

    # 前置校验2：已经配置了LLM不能跳过
    if setup.llm_configured:
        logger.warning("Attempt to skip LLM config after provider already configured")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LLM provider already configured",
        )

    # 前置校验3：已经跳过了不能重复跳过
    if setup.skip_llm_config:
        logger.warning("Attempt to skip LLM config which was already skipped")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LLM configuration already skipped",
        )

    # 执行跳过操作
    setup.skip_llm_config = True
    _recalculate_install_flags(setup)  # 自动计算安装完成状态
    db.commit()
    db.refresh(setup)

    logger.info(
        "LLM configuration skipped via /v1/setup/skip-llm; "
        f"is_installed={setup.is_installed}, "
        f"setup_completed_at={setup.setup_completed_at}",
    )

    return SkipLLMConfigResponse(
        message="LLM configuration step skipped successfully",
        is_installed=setup.is_installed,
        setup_completed_at=setup.setup_completed_at,
    )@router.get(
    "/verify",
    response_model=VerifySetupResponse,
    summary="验证安装完整性",
    description="全面检查系统各组件安装状态，返回详细校验结果和问题提示"
)
async def verify_setup(
    db: Session = Depends(get_db),
) -> VerifySetupResponse:
    """
    系统安装完整性校验接口，执行多维度健康检查：
    1. 数据库连通性
    2. 管理员账号
    3. LLM配置状态
    4. 项目是否存在
    5. 系统安装标志
    返回每项检查结果、错误列表、警告列表。
    """
    checks = {}       # 各项检查结果字典
    errors = []       # 致命错误列表
    warnings = []     # 警告提示列表

    # ========== 检查1：数据库连通性 ==========
    try:
        db.execute(text("SELECT 1"))  # 执行简单SQL探测连接
        checks["database_connected"] = SetupCheckResult(
            passed=True,
            message="Database connection is healthy"
        )
    except Exception as e:
        checks["database_connected"] = SetupCheckResult(
            passed=False,
            message=f"Database connection failed: {str(e)}"
        )
        errors.append(f"Database connection error: {str(e)}")

    # ========== 检查2：管理员账号状态 ==========
    is_installed, has_admin, has_user_staff, has_llm_config, skip_llm_config = _check_system_installed(db)

    if has_admin:
        admin_count = db.query(Staff).filter(Staff.deleted_at.is_(None)).count()
        checks["admin_exists"] = SetupCheckResult(
            passed=True,
            message=f"Admin account exists ({admin_count} staff member(s) found)",
        )
    else:
        checks["admin_exists"] = SetupCheckResult(
            passed=False,
            message="No admin account found",
        )
        errors.append("Admin account has not been created")

    # ========== 检查3：LLM配置状态 ==========
    if has_llm_config:
        llm_count = (
            db.query(AIProvider)
            .filter(
                AIProvider.deleted_at.is_(None),
                AIProvider.is_active == True,
            )
            .count()
        )
        checks["llm_configured"] = SetupCheckResult(
            passed=True,
            message=f"LLM provider configured ({llm_count} active provider(s))",
        )
    elif skip_llm_config:
        # 跳过LLM也算通过，但加警告提示
        checks["llm_configured"] = SetupCheckResult(
            passed=True,
            message="LLM configuration was skipped during setup; no provider configured yet",
        )
        warnings.append(
            "LLM configuration was skipped during setup; you can configure a provider later."
        )
    else:
        checks["llm_configured"] = SetupCheckResult(
            passed=False,
            message="No active LLM provider found",
        )
        errors.append("LLM provider has not been configured")

    # ========== 检查4：项目是否存在 ==========
    project_count = db.query(Project).filter(Project.deleted_at.is_(None)).count()
    if project_count > 0:
        checks["project_exists"] = SetupCheckResult(
            passed=True,
            message=f"Project exists ({project_count} project(s) found)",
        )
    else:
        checks["project_exists"] = SetupCheckResult(
            passed=False,
            message="No project found",
        )
        errors.append("No project has been created")

    # ========== 检查5：系统安装标志 ==========
    if is_installed:
        checks["installation_status"] = SetupCheckResult(
            passed=True,
            message="Installation is marked as complete in system_setup table",
        )
    else:
        checks["installation_status"] = SetupCheckResult(
            passed=False,
            message="Installation is not marked as complete in system_setup table",
        )
        errors.append("System installation has not been completed in setup wizard")

    # 整体是否通过：所有检查项都通过才算有效
    is_valid = all(check.passed for check in checks.values())

    # 补充警告提示
    if has_admin and not has_llm_config and not skip_llm_config:
        warnings.append("Admin created but LLM provider not configured yet")
    elif has_llm_config and not has_admin:
        warnings.append("LLM provider configured but no admin account exists")
    
    # 警告：只有管理员没有普通坐席
    if has_admin and not has_user_staff:
        warnings.append("No user staff members found; consider adding customer service staff")

    logger.info(
        f"Setup verification: valid={is_valid}, "
        f"errors={len(errors)}, warnings={len(warnings)}",
    )

    return VerifySetupResponse(
        is_valid=is_valid,
        checks=checks,
        errors=errors,
        warnings=warnings,
    )
@router.post(
    "/staff",
    response_model=BatchCreateStaffResponse,
    status_code=status.HTTP_201_CREATED,
    summary="安装阶段批量创建坐席",
    description="初始安装阶段批量创建普通坐席账号，系统安装完成后自动禁用此接口"
)
async def batch_create_staff(
    staff_data: BatchCreateStaffRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> BatchCreateStaffResponse:
    """
    安装向导可选步骤：批量创建客服坐席账号。
    安全限制：仅系统未安装时可调用，安装完成后必须走鉴权后的坐席管理接口。
    执行逻辑：
    1. 校验未安装、管理员已存在
    2. 遍历坐席列表，已存在的用户名跳过
    3. 自动创建默认访客分配规则（首次创建坐席时）
    4. 批量将新坐席加入项目IM频道
    5. 返回创建成功列表和跳过列表
    """
    setup = _get_or_create_system_setup(db)

    # 核心安全校验：安装完成后绝对禁止调用此接口
    if setup.is_installed:
        logger.warning(
            f"SECURITY: Attempt to call batch staff creation after installation: {request.url.path}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "System installation is already complete. "
                "This setup endpoint is disabled for security reasons. "
                "Please use the authenticated staff management endpoints instead."
            ),
        )

    # 前置校验：必须先有管理员
    if not setup.admin_created:
        logger.warning("Attempt to create staff before admin account exists")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin account must be created before adding staff members"
        )

    # 获取项目
    project = db.query(Project).filter(Project.deleted_at.is_(None)).first()
    if not project:
        logger.error("No project found despite admin existing")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="System error: No project found"
        )

    created_staff = []       # 创建成功的坐席列表
    skipped_usernames = []   # 跳过的已存在用户名

    # 遍历批量创建
    for item in staff_data.staff_list:
        # 用户名去重校验
        existing = db.query(Staff).filter(
            Staff.username == item.username,
            Staff.deleted_at.is_(None),
        ).first()

        if existing:
            logger.info(f"Staff username already exists, skipping: {item.username}")
            skipped_usernames.append(item.username)
            continue

        # 创建普通坐席，角色固定为 USER，绝不允许创建管理员
        password_hash = get_password_hash(item.password)
        staff = Staff(
            project_id=project.id,
            username=item.username,
            password_hash=password_hash,
            name=item.name,
            nickname=item.nickname or item.name or item.username,
            description=item.description,
            role=StaffRole.USER,  # 强制普通角色，安全兜底
            status=StaffStatus.OFFLINE,
        )
        db.add(staff)
        created_staff.append(staff)

    # 有成功创建的坐席时执行后续操作
    if created_staff:
        # 首次创建坐席时，自动创建默认访客分配规则
        existing_rule = db.query(VisitorAssignmentRule).filter(
            VisitorAssignmentRule.project_id == project.id
        ).first()
        
        if not existing_rule:
            # 解析配置中的默认服务日（逗号分隔字符串转数字列表）
            default_weekdays = [
                int(d.strip()) 
                for d in settings.ASSIGNMENT_RULE_DEFAULT_WEEKDAYS.split(",") 
                if d.strip().isdigit()
            ]
            
            # 创建默认分配规则
            default_rule = VisitorAssignmentRule(
                project_id=project.id,
                llm_assignment_enabled=False,  # 默认关闭AI分配，使用负载均衡
                timezone=settings.ASSIGNMENT_RULE_DEFAULT_TIMEZONE,
                service_weekdays=default_weekdays,
                service_start_time=settings.ASSIGNMENT_RULE_DEFAULT_START_TIME,
                service_end_time=settings.ASSIGNMENT_RULE_DEFAULT_END_TIME,
                max_concurrent_chats=settings.ASSIGNMENT_RULE_DEFAULT_MAX_CONCURRENT_CHATS,
                auto_close_hours=settings.ASSIGNMENT_RULE_DEFAULT_AUTO_CLOSE_HOURS,
            )
            db.add(default_rule)
            logger.info(f"Created default visitor assignment rule for project {project.id}")
        
        db.flush()  # 预提交获取坐席ID
        
        # 批量将新坐席加入项目IM坐席频道
        try:
            channel_id = build_project_staff_channel_id(project.id)
            staff_uids = [f"{staff.id}-staff" for staff in created_staff]
            await wukongim_client.add_channel_subscribers(
                channel_id=channel_id,
                channel_type=CHANNEL_TYPE_PROJECT_STAFF,
                subscribers=staff_uids,
            )
            logger.info(
                f"Added {len(staff_uids)} staff to project channel",
                extra={
                    "project_id": str(project.id),
                    "channel_id": channel_id,
                    "staff_count": len(staff_uids),
                },
            )
        except Exception as e:
            logger.error(f"Failed to add staff to project channel: {e}")
            db.rollback()  # IM失败回滚全部
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to add staff to project channel"
            )
        
        db.commit()
        for staff in created_staff:
            db.refresh(staff)

        logger.info(
            f"Batch created {len(created_staff)} staff members during setup, "
            f"skipped {len(skipped_usernames)} existing usernames"
        )

    return BatchCreateStaffResponse(
        created_count=len(created_staff),
        staff_list=[
            StaffCreatedItem(
                id=staff.id,
                username=staff.username,
                name=staff.name,
                nickname=staff.nickname,
                created_at=staff.created_at,
            )
            for staff in created_staff
        ],
        skipped_usernames=skipped_usernames,
    )