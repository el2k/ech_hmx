"""Device Service - Database operations for devices."""

import uuid
from datetime import datetime, timezone
from typing import Optional, Tuple, List

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.device import Device, DeviceSession, DeviceStatus, DeviceType
from app.schemas.device import DeviceResponse, DeviceUpdateRequest
from app.services.bind_code_service import bind_code_service

logger = get_logger("services.device_service")
''
'''
📌整体业务流程梳理
生成绑定码：后端调用generate_bind_code()，Redis 存短码 + 所属项目 ID，带过期。
设备注册：客户端输入绑定码 → register_device()，Redis 校验绑定码，创建 Device 记录，生成唯一device_token下发给客户端。
设备重连鉴权：客户端保存device_token，websocket 长连接使用get_device_by_token()鉴权，不再需要绑定码。
会话开启：设备启动 Agent 任务，调用create_session()新建会话。
会话运行：Agent 执行操作，持续调用increment_session_stats()累计截图、动作。
会话结束：任务完成调用end_session()打上结束时间。
设备生命周期：查询列表、修改名称、更新在线离线状态、删除设备。
'''
class DeviceService:
    """Service for device database operations.
    设备服务：封装设备相关全部数据库CRUD，接收异步数据库会话 db:AsyncSession
    """

    def __init__(self, db: AsyncSession):
        # 注入异步数据库会话，每一次接口请求实例化一次Service
        self.db = db

    async def list_devices(
        self,
        project_id: uuid.UUID,
        device_type: Optional[str] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[DeviceResponse], int]:
        """List devices for a project.
        分页查询项目下设备列表
        返回：(Pydantic设备响应对象列表,总条数)
        """
        # 组装查询条件：必须限定项目ID，做数据隔离，不同项目看不到彼此设备
        conditions = [Device.project_id == project_id]

        # 可选过滤条件：设备类型、设备状态
        if device_type:
            conditions.append(Device.device_type == device_type)
        if status:
            conditions.append(Device.status == status)

        # 先统计总数量，用于前端分页
        count_query = select(func.count(Device.id)).where(and_(*conditions))
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        # 查询分页设备数据，按创建时间倒序，新设备排在前面
        query = (
            select(Device)
            .where(and_(*conditions))
            .order_by(Device.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
        devices = result.scalars().all()

        # ORM模型 → Pydantic输出模型，返回给接口
        return [DeviceResponse.model_validate(d) for d in devices], total

    async def get_device(
        self,
        device_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> Optional[DeviceResponse]:
        """Get a device by ID.
        根据设备ID查询单台设备，带上project_id做权限隔离，防止跨项目越权访问
        找不到返回None
        """
        query = select(Device).where(
            and_(Device.id == device_id, Device.project_id == project_id)
        )
        result = await self.db.execute(query)
        device = result.scalar_one_or_none()

        if device:
            return DeviceResponse.model_validate(device)
        return None

    async def generate_bind_code(
        self,
        project_id: uuid.UUID,
    ) -> Tuple[str, datetime]:
        """Generate a new bind code using Redis.
        生成设备绑定码，交给Redis存储（带过期时间）
        返回 (绑定码字符串,过期时间)
        绑定码作用：客户端设备输入短码完成设备和项目绑定
        """
        return await bind_code_service.generate(project_id)

    async def register_device(
        self,
        bind_code: str,
        device_name: str,
        device_type: str,
        os: str,
        os_version: Optional[str],
        screen_resolution: Optional[str],
    ) -> Optional[Device]:
        """Register a device using a bind code.
        设备注册逻辑：客户端传入绑定码，校验通过后创建数据库设备记录
        返回ORM Device对象；绑定码无效返回None
        """
        logger.info(f"[DEBUG] register_device called: bind_code={bind_code}, device_name={device_name}, os={os}")
        
        # 1.去Redis校验绑定码，拿到归属project_id；绑定码过期/错误返回None注册失败
        logger.info(f"[DEBUG] Validating bind code from Redis...")
        project_id = await bind_code_service.validate(bind_code) # uuid
        if not project_id:
            logger.warning(f"[DEBUG] Invalid or expired bind code: {bind_code}")
            return None

        logger.info(f"[DEBUG] Bind code valid, project_id={project_id}")

        # 2.构造数据库Device对象
        try:
            device = Device(
                project_id=project_id,
                device_name=device_name,
                device_type=DeviceType(device_type), #枚举转换
                os=os,
                os_version=os_version,
                screen_resolution=screen_resolution,
                status=DeviceStatus.ONLINE, #刚注册直接标记在线
                last_seen_at=datetime.now(timezone.utc), #最后活跃时间UTC时间
                device_token=str(uuid.uuid4()), #生成设备token，后续设备重连鉴权使用
            )
            logger.info(f"[DEBUG] Device object created: {device}")

            self.db.add(device) #加入会话缓存，还没落库
            logger.info(f"[DEBUG] Device added to session, committing...")
            await self.db.commit() #提交事务写入数据库
            logger.info(f"[DEBUG] Commit successful, refreshing...")
            await self.db.refresh(device) #刷新对象，拿到数据库自动生成id等字段

            logger.info(f"[DEBUG] Device registered successfully: {device_name} ({device.id}) for project {project_id}")
            return device
        except Exception as e:
            logger.error(f"[DEBUG] Error creating device record: {e}", exc_info=True)
            raise #异常向上抛出，交给上层接口处理

    async def update_device(
        self,
        device_id: uuid.UUID,
        project_id: uuid.UUID,
        update_data: DeviceUpdateRequest,
    ) -> Optional[DeviceResponse]:
        """Update a device. 更新设备基础信息（设备名称等）"""
        # 权限校验：必须同时匹配设备id+项目id，防止越权修改别的项目设备
        query = select(Device).where(
            and_(Device.id == device_id, Device.project_id == project_id)
        )
        result = await self.db.execute(query)
        device = result.scalar_one_or_none()

        if not device:
            return None

        # 字段更新，只更新传入不为None的字段
        if update_data.device_name is not None:
            device.device_name = update_data.device_name

        await self.db.commit()
        await self.db.refresh(device)

        return DeviceResponse.model_validate(device)

    async def update_device_status(
        self,
        device_id: uuid.UUID,
        status: DeviceStatus,
    ) -> None:
        """Update device status. 更新设备在线/离线状态
        如果改为ONLINE，同步刷新last_seen_at最后活跃时间
        """
        query = select(Device).where(Device.id == device_id)
        result = await self.db.execute(query)
        device = result.scalar_one_or_none()

        if device:
            device.status = status
            if status == DeviceStatus.ONLINE:
                device.last_seen_at = datetime.now(timezone.utc)
            await self.db.commit()

    async def delete_device(
        self,
        device_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> bool:
        """Delete a device. 删除设备，返回bool是否删除成功"""
        query = select(Device).where(
            and_(Device.id == device_id, Device.project_id == project_id)
        )
        result = await self.db.execute(query)
        device = result.scalar_one_or_none()

        if not device:
            return False

        await self.db.delete(device)
        await self.db.commit()

        logger.info(f"Device deleted: {device_id}")
        return True

    async def get_device_by_token(self, device_token: str) -> Optional[Device]:
        """Get a device by its token (for reconnection).
        根据device_token查询设备，用于设备长连接重连鉴权
        设备持有token，不需要每次传绑定码，用于websocket接入
        """
        query = select(Device).where(Device.device_token == device_token)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    # ====================== 下面是设备会话 DeviceSession 管理 ======================
    """
    一台设备可以开启多次会话；会话代表一次Agent运行任务
    会话会统计截图数量、执行动作数量，记录会话开始/结束时间
    """

    async def create_session(
        self,
        device_id: uuid.UUID,
        agent_id: Optional[uuid.UUID] = None,
    ) -> DeviceSession:
        """Create a new device session. 创建一次设备会话，绑定设备、可选绑定Agent"""
        session = DeviceSession(
            device_id=device_id,
            agent_id=agent_id,
        )
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def end_session(self, session_id: uuid.UUID) -> None:
        """End a device session. 结束会话，填充ended_at结束时间"""
        query = select(DeviceSession).where(DeviceSession.id == session_id)
        result = await self.db.execute(query)
        session = result.scalar_one_or_none()

        if session:
            session.ended_at = datetime.now(timezone.utc)
            await self.db.commit()

    async def increment_session_stats(
        self,
        session_id: uuid.UUID,
        screenshots: int = 0,
        actions: int = 0,
    ) -> None:
        """Increment session statistics.
        会话统计计数累加：截图次数、执行动作次数
        Agent每截图一次、执行一次操作就调用这个函数做统计
        """
        query = select(DeviceSession).where(DeviceSession.id == session_id)
        result = await self.db.execute(query)
        session = result.scalar_one_or_none()

        if session:
            session.screenshots_count += screenshots
            session.actions_count += actions
            await self.db.commit()