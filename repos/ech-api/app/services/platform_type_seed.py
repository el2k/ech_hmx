"""Seed default platform types into ai_platform_types table (idempotent).

This runs on service startup and performs an upsert by unique key `type` to
avoid duplicate rows while keeping names/icons up to date.
"""
from __future__ import annotations

from typing import List, Dict

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.logging import startup_log
from app.models.platform import PlatformTypeDefinition


# 预置全部渠道平台类型字典
# type：唯一业务标识(唯一索引)；name中文显示名；name_en英文名称；is_supported当前系统是否对接支持
# is_supported=False：仅预留枚举定义，前端展示但不可新建该渠道
SEED_PLATFORM_TYPES: List[Dict[str, object]] = [
    # Supported platform types 已对接支持的渠道
    {
        "type": "website",
        "name": "网站小部件",
        "name_en": "Website",
        "is_supported": True,
    },
    {
        "type": "wecom",
        "name": "微信客服",
        "name_en": "WeCom",
        "is_supported": True,
    },
    {
        "type": "email",
        "name": "邮件",
        "name_en": "Email",
        "is_supported": True,
    },
    {
        "type": "custom",
        "name": "自定义",
        "name_en": "Custom",
        "is_supported": True,
    },
    {
        "type": "wecom_bot",
        "name": "企业微信机器人",
        "name_en": "WeCom Bot",
        "is_supported": True,
    },
    {
        "type": "feishu_bot",
        "name": "飞书机器人",
        "name_en": "Feishu Bot",
        "is_supported": True,
    },
    {
        "type": "dingtalk_bot",
        "name": "钉钉机器人",
        "name_en": "DingTalk Bot",
        "is_supported": True,
    },
    # Other platform types from PlatformType enum (currently not supported)
    # 预留渠道类型，暂未实现对接，is_supported=False
    {
        "type": "wechat",
        "name": "微信公众号",
        "name_en": "WeChat Official Account",
        "is_supported": False,
    },
    {
        "type": "whatsapp",
        "name": "WhatsApp",
        "name_en": "WhatsApp",
        "is_supported": False,
    },
    {
        "type": "telegram",
        "name": "Telegram",
        "name_en": "Telegram",
        "is_supported": True,
    },
    {
        "type": "sms",
        "name": "短信",
        "name_en": "SMS",
        "is_supported": False,
    },
    {
        "type": "facebook",
        "name": "Facebook",
        "name_en": "Facebook",
        "is_supported": False,
    },
    {
        "type": "instagram",
        "name": "Instagram",
        "name_en": "Instagram",
        "is_supported": False,
    },
    {
        "type": "twitter",
        "name": "Twitter",
        "name_en": "Twitter",
        "is_supported": False,
    },
    {
        "type": "linkedin",
        "name": "LinkedIn",
        "name_en": "LinkedIn",
        "is_supported": False,
    },
    {
        "type": "discord",
        "name": "Discord",
        "name_en": "Discord",
        "is_supported": False,
    },
    {
        "type": "slack",
        "name": "Slack",
        "name_en": "Slack",
        "is_supported": True,
    },
    {
        "type": "teams",
        "name": "Microsoft Teams",
        "name_en": "Microsoft Teams",
        "is_supported": False,
    },
    {
        "type": "phone",
        "name": "电话",
        "name_en": "Phone",
        "is_supported": False,
    },
    {
        "type": "douyin",
        "name": "抖音",
        "name_en": "Douyin",
        "is_supported": False,
    },
    {
        "type": "tiktok",
        "name": "TikTok",
        "name_en": "TikTok",
        "is_supported": False,
    },
]


def ensure_platform_types_seed() -> None:
    """Ensure default platform types exist; upsert by unique `type`.
    渠道类型种子初始化函数，服务启动时调用，**幂等PostgreSQL UPSERT逻辑**
    业务唯一键：type字段；不存在则插入，已存在则更新名称、支持状态；
    ⚠️异常场景：回滚事务、打印告警日志，但**不会抛出异常阻断服务启动**。
    """
    # 创建独立数据库会话
    db: Session = SessionLocal()
    try:
        # 遍历所有预置渠道定义，逐一生成upsert语句
        for row in SEED_PLATFORM_TYPES:
            # postgres原生insert语句，写入ai_platform_types表
            stmt = insert(PlatformTypeDefinition).values(
                type=row["type"],               # 渠道唯一标识
                name=row["name"],               # 中文名称
                is_supported=row["is_supported"], # 是否支持该渠道
                name_en=row.get("name_en"),     # 英文名称，允许缺失
            )

            # on_conflict_do_update：PG特有UPSERT冲突更新逻辑
            # index_elements：指定唯一约束字段 type
            # stmt.excluded：代表insert语句传入的待写入的新数据行
            stmt = stmt.on_conflict_do_update(
                index_elements=[PlatformTypeDefinition.type],
                set_={
                    "name": stmt.excluded.name,
                    "is_supported": stmt.excluded.is_supported,
                    "name_en": stmt.excluded.name_en,
                },
            )
            # 执行单条upsert SQL，此时还未真正提交数据库
            db.execute(stmt)

        # 全部循环完成后一次性事务提交；要么全部成功，要么全部回滚
        db.commit()

        startup_log("✅ Platform types seeded (idempotent)")

    except Exception as e:  # pragma: no cover
        # 发生任何异常，回滚整个事务，防止部分写入脏数据
        db.rollback()
        # 只打印告警日志，不raise抛出异常；初始化失败不阻止服务继续运行
        startup_log(f"⚠️  Failed to seed platform types: {e}")

    finally:
        # 无论成功失败，强制关闭数据库会话释放连接
        db.close()