# -*- coding: utf-8 -*-
"""Visitor related service logic."""
# 模块说明：访客（Visitor）相关的服务层逻辑，包括访客创建、系统信息更新、WuKongIM频道保障等。

import hashlib
import re
import uuid
from datetime import datetime
from typing import Optional, List, Tuple

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import (
    Platform,
    Visitor,
    VisitorSystemInfo,
    ChannelMember,
)
from app.schemas.visitor import VisitorSystemInfoRequest
from app.services.wukongim_client import wukongim_client
from app.services.geoip_service import geoip_service
from app.utils.const import (
    CHANNEL_TYPE_CUSTOMER_SERVICE,
    MEMBER_TYPE_VISITOR,
)
from app.utils.encoding import build_visitor_channel_id

# 获取当前模块的日志记录器
logger = get_logger("services.visitor")

# ------------------- 常量定义 -------------------
# 预设的访客默认名称列表（用于生成确定性的默认姓名）
DEFAULT_VISITOR_NAMES = [
    "Alex Chen", "Sarah Johnson", "Michael Zhang", "Emma Wilson", "David Kumar",
    "Jessica Martinez", "Ryan O'Connor", "Sophia Lee", "James Anderson", "Olivia Brown",
    "Daniel Garcia", "Isabella Rodriguez", "Matthew Taylor", "Ava Thompson",
    "Christopher White", "Mia Harris", "Andrew Clark", "Emily Lewis", "Joshua Walker",
    "Charlotte Hall", "Kevin Young", "Amelia Allen", "Brandon King", "Harper Wright",
    "Tyler Scott", "Evelyn Green", "Justin Adams", "Abigail Baker", "Nathan Nelson",
    "Ella Carter",
]

# 中文昵称组件：形容词
CUSTOMER_SERVICE_ADJECTIVES_ZH = [
    "星光", "温暖", "清晨", "晴空", "暖阳", "微风", "云端", "静谧", "灵动", "璀璨", "悠然", "暮色",
]

# 中文昵称组件：名词
CUSTOMER_SERVICE_NOUNS_ZH = [
    "海豚", "星猫", "向日葵", "松果", "雨燕", "晨露", "珊瑚", "雪狐", "轻舟", "薰衣草", "流萤", "橄榄树",
]

# 英文昵称组件：形容词
CUSTOMER_SERVICE_ADJECTIVES_EN = [
    "Starry", "Warm", "Morning", "Sunny", "Bright", "Breezy", "Cloud", "Quiet", "Swift", "Shiny", "Calm", "Twilight",
]

# 英文昵称组件：名词
CUSTOMER_SERVICE_NOUNS_EN = [
    "Dolphin", "Cat", "Sunflower", "Pine", "Swallow", "Dew", "Coral", "Fox", "Boat", "Lavender", "Firefly", "Olive",
]

# 头像上传允许的MIME类型
AVATAR_ALLOWED_MIME_TYPES = {
    "image/jpeg", "image/jpg", "image/png", "image/gif", "image/webp",
}
# 头像上传允许的文件扩展名
AVATAR_ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
# 头像最大尺寸（5MB）
AVATAR_MAX_SIZE_MB = 5


# ------------------- 工具函数 -------------------
def generate_default_visitor_name(visitor_id: str) -> str:
    """
    根据访客ID生成一个确定性的默认名称。
    使用SHA256哈希取模，从预设列表中选出一个名字，保证同一访客ID总是得到相同名称。
    """
    id_bytes = visitor_id.encode('utf-8')
    hash_digest = hashlib.sha256(id_bytes).digest()
    # 取前4字节转换为整数，再取模
    index = int.from_bytes(hash_digest[:4], byteorder='big') % len(DEFAULT_VISITOR_NAMES)
    return DEFAULT_VISITOR_NAMES[index]


def generate_customer_service_nickname(identifier: Optional[str]) -> Tuple[str, str]:
    """
    为访客生成友好的备用昵称（中英文各一个）。
    用于当未提供昵称时，生成默认昵称。昵称由形容词+名词+3位十六进制后缀组成。
    参数 identifier：用于生成确定性的标识符，通常为平台open_id或访客ID；若为空则使用当前UTC时间。
    返回：(英文昵称, 中文昵称)
    """
    base_identifier = (identifier or "").strip()
    if not base_identifier:
        base_identifier = datetime.utcnow().isoformat()  # 若标识符为空，使用当前时间

    digest = hashlib.sha256(base_identifier.encode("utf-8")).digest()

    # 使用哈希字节的不同位置分别选择形容词和名词
    # 英文昵称
    adjective_en = CUSTOMER_SERVICE_ADJECTIVES_EN[digest[0] % len(CUSTOMER_SERVICE_ADJECTIVES_EN)]
    noun_en = CUSTOMER_SERVICE_NOUNS_EN[digest[1] % len(CUSTOMER_SERVICE_NOUNS_EN)]

    # 中文昵称（同样使用digest[0]和digest[1]，但对应不同词汇表）
    adjective_zh = CUSTOMER_SERVICE_ADJECTIVES_ZH[digest[0] % len(CUSTOMER_SERVICE_ADJECTIVES_ZH)]
    noun_zh = CUSTOMER_SERVICE_NOUNS_ZH[digest[1] % len(CUSTOMER_SERVICE_NOUNS_ZH)]

    # 后缀：取digest[2:4]转整数，格式化为大写十六进制，取前3位
    suffix_value = int.from_bytes(digest[2:4], byteorder="big")
    suffix = format(suffix_value, "x").upper()[:3]

    nickname_en = f"{adjective_en}{noun_en}{suffix}"
    nickname_zh = f"{adjective_zh}{noun_zh}{suffix}"

    return nickname_en, nickname_zh


def resolve_visitor_nickname(
    provided_nickname: Optional[str],
    provided_nickname_zh: Optional[str],
    identifier: Optional[str],
) -> Tuple[str, str]:
    """
    解析并返回最终的访客昵称（中英文）。
    如果提供的昵称不为空，则使用；否则调用 generate_customer_service_nickname 生成默认值。
    返回：(英文昵称, 中文昵称)
    """
    nickname_en = (provided_nickname or "").strip()
    nickname_zh = (provided_nickname_zh or "").strip()

    # 如果两者都已提供，直接返回
    if nickname_en and nickname_zh:
        return nickname_en, nickname_zh

    # 否则生成默认值，并用已有值覆盖（若一方为空则用生成的，若都为空则全用生成的）
    generated_en, generated_zh = generate_customer_service_nickname(identifier)
    return nickname_en or generated_en, nickname_zh or generated_zh


# ------------------- 核心服务函数 -------------------
async def ensure_visitor_channel(
    db: Session,
    visitor: Visitor,
    platform: Platform,
) -> None:
    """
    确保访客在WuKongIM中拥有对应的频道。
    该函数将数据库操作与外部API调用分离，以缩短事务持续时间，防止死锁。
    流程：
      1. 在数据库事务中检查并创建 ChannelMember 记录（如果不存在）。
      2. 提交事务，释放锁。
      3. 调用 WuKongIM API 创建频道（可能失败，但不会回滚数据库更改）。
    """
    channel_id = build_visitor_channel_id(visitor.id)  # 根据访客ID构建频道ID
    subscribers = [str(visitor.id) + "-vtr"]          # 订阅者列表，格式为 "visitor_id-vtr"
    need_create_member = False

    # Phase 1：数据库操作（短事务）
    try:
        # 查询是否已存在该访客在该频道下的成员记录
        existing_visitor_member = (
            db.query(ChannelMember)
            .filter(
                ChannelMember.project_id == platform.project_id,
                ChannelMember.channel_id == channel_id,
                ChannelMember.member_id == visitor.id,
                ChannelMember.deleted_at.is_(None),
            )
            .first()
        )

        # 若不存在，则创建一条新记录
        if not existing_visitor_member:
            visitor_member = ChannelMember(
                project_id=platform.project_id,
                channel_id=channel_id,
                channel_type=CHANNEL_TYPE_CUSTOMER_SERVICE,
                member_id=visitor.id,
                member_type=MEMBER_TYPE_VISITOR,
            )
            db.add(visitor_member)
            db.commit()
            need_create_member = True  # 标记已创建，用于日志

    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        logger.error(f"Failed to create ChannelMember for visitor: {e}")
        raise  # 数据库失败直接抛异常

    # Phase 2：外部API调用（在事务之外）
    try:
        await wukongim_client.create_channel(
            channel_id=channel_id,
            channel_type=CHANNEL_TYPE_CUSTOMER_SERVICE,
            subscribers=subscribers,
        )
        logger.info(
            "WuKongIM channel ensured for visitor",
            extra={
                "channel_id": channel_id,
                "channel_type": CHANNEL_TYPE_CUSTOMER_SERVICE,
                "visitor_id": str(visitor.id),
                "member_created": need_create_member,
            },
        )
    except Exception as e:
        # 外部API失败仅记录日志，不抛出异常，也不回滚DB。
        # 因为 ChannelMember 记录有效，后续可以重试。
        logger.error(f"Failed to create WuKongIM channel for visitor: {e}")


async def create_visitor_with_channel(
    db: Session,
    platform: Platform,
    platform_open_id: Optional[str] = None,
    name: Optional[str] = None,
    nickname: Optional[str] = None,
    nickname_zh: Optional[str] = None,
    avatar_url: Optional[str] = None,
    phone_number: Optional[str] = None,
    email: Optional[str] = None,
    company: Optional[str] = None,
    job_title: Optional[str] = None,
    source: Optional[str] = None,
    note: Optional[str] = None,
    custom_attributes: Optional[dict] = None,
    timezone: Optional[str] = None,
    language: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> Visitor:
    """
    创建一个新的访客，并为其设置WuKongIM频道。
    参数说明：
      - platform: 平台对象
      - platform_open_id: 平台侧的用户唯一标识，若未提供，则会先生成一个临时ID，之后用 visitor.id 更新。
      - name: 真实姓名（可选）
      - nickname/nickname_zh: 中英文昵称（可选，未提供则生成默认）
      - avatar_url, phone_number, email, company, job_title, source, note: 基本信息
      - custom_attributes: 自定义属性（字典）
      - timezone, language: 时区和语言
      - ip_address: IP地址，用于地理位置解析
    返回：创建的 Visitor 对象（已刷新）。
    """
    # 判断是否需要使用访客ID作为open_id（即未提供platform_open_id）
    use_visitor_id_as_open_id = not platform_open_id

    # 若未提供，生成一个临时占位符
    if use_visitor_id_as_open_id:
        initial_platform_open_id = f"pending-{uuid.uuid4().hex}"
    else:
        initial_platform_open_id = platform_open_id

    # 解析最终昵称（若传入的为空则生成默认）
    resolved_nickname, resolved_nickname_zh = resolve_visitor_nickname(
        nickname, nickname_zh, platform_open_id or None
    )

    # 根据IP地址获取地理位置信息（使用geoip服务）
    geo_location = geoip_service.lookup(ip_address)

    # 创建 Visitor 对象
    visitor = Visitor(
        project_id=platform.project_id,
        platform_id=platform.id,
        platform_open_id=initial_platform_open_id,
        name=name,
        nickname=resolved_nickname,
        nickname_zh=resolved_nickname_zh,
        avatar_url=avatar_url,
        phone_number=phone_number,
        email=email,
        company=company,
        job_title=job_title,
        source=source,
        note=note,
        custom_attributes=custom_attributes or {},
        timezone=timezone,
        language=language,
        ip_address=ip_address,
        geo_country=geo_location.country,
        geo_country_code=geo_location.country_code,
        geo_region=geo_location.region,
        geo_city=geo_location.city,
        geo_isp=geo_location.isp,
        first_visit_time=datetime.utcnow(),
        last_visit_time=datetime.utcnow(),
    )
    db.add(visitor)

    # 如果之前未提供platform_open_id，则在flush后获得visitor.id，更新platform_open_id为 "visitor.id-vtr"
    if use_visitor_id_as_open_id:
        db.flush()  # 确保visitor获得自增ID
        visitor.platform_open_id = str(visitor.id) + "-vtr"

    db.commit()
    db.refresh(visitor)  # 刷新以获取最新状态（如数据库默认值）

    # 创建WuKongIM频道（异步）
    await ensure_visitor_channel(db, visitor, platform)
    return visitor


def upsert_visitor_system_info(
    db: Session,
    visitor: Visitor,
    platform: Platform,
    system_info_payload: Optional[VisitorSystemInfoRequest],
) -> bool:
    """
    创建或更新访客的系统信息记录。
    参数：
      - visitor: 访客对象
      - platform: 平台对象
      - system_info_payload: 包含系统信息的请求对象（可能为None）
    返回：bool，表示是否有任何字段发生了变化。
    """
    system_info = visitor.system_info  # 通过关系访问，可能为None
    created = False
    if not system_info:
        # 若不存在，则创建新的系统信息记录
        system_info = VisitorSystemInfo(
            project_id=platform.project_id,
            visitor_id=visitor.id,
        )
        db.add(system_info)
        visitor.system_info = system_info
        created = True

    changed = created  # 新建也算作变更

    # 若platform字段与当前平台名称不一致则更新
    if system_info.platform != platform.name:
        system_info.platform = platform.name
        changed = True

    # 若首次看到时间为空，则设置为当前UTC时间
    if system_info.first_seen_at is None:
        system_info.first_seen_at = datetime.utcnow()
        changed = True

    # 如果payload存在，则提取其中指定的字段并更新
    info_data = system_info_payload.model_dump(exclude_none=True) if system_info_payload else {}
    for field in ("source_detail", "browser", "operating_system"):
        if field in info_data and getattr(system_info, field) != info_data[field]:
            setattr(system_info, field, info_data[field])
            changed = True

    return changed


def sanitize_avatar_filename(name: str, limit: int = 100) -> str:
    """
    对上传的头像文件名进行安全清理，防止路径遍历和非法字符。
    替换反斜杠、斜杠、连续点，并移除除字母数字下划线点横线以外的字符。
    若文件名超过限制长度，则截断（保留扩展名）。
    """
    # 替换危险字符
    name = name.replace("\\", "_").replace("/", "_").replace("..", ".")
    # 只保留安全的字符
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    # 若长度未超限直接返回
    if len(name) <= limit:
        return name
    # 若包含扩展名，则保留扩展名，截断主体部分
    if "." in name:
        base, ext = name.rsplit(".", 1)
        base = base[: max(1, limit - len(ext) - 1)]  # 确保至少保留1个字符
        return f"{base}.{ext}"
    return name[:limit]