"""Default model seed resolution for AI provider creation flows."""
# 模块用途：AI服务商创建流程中，处理默认模型种子数据的解析逻辑
# 当新增一个AI服务商时，自动加载/生成该服务商预置的模型列表

from dataclasses import dataclass
from typing import Iterable

# SQLAlchemy ORM 数据库相关导入
from sqlalchemy import select
from sqlalchemy.orm import Session

# 导入数据库ORM模型：AIProviderDefaultModel 服务商默认模型表
from app.models import AIProviderDefaultModel

# 常量：openai兼容模式服务商标识，自定义服务商统一归为此类
OPENAI_COMPATIBLE_PROVIDER = "openai_compatible"

# 服务商别名映射字典：把用户输入的各种简写/别名，转换为系统内部标准key
_PROVIDER_ALIASES: dict[str, str] = {
    "azure": "azure_openai",               # azure 别名映射到标准azure_openai
    "azure-openai": "azure_openai",        # azure-openai 横杠写法兼容
    "qwen": "dashscope",                   # qwen → 阿里通义千问dashscope
    "ali": "dashscope",                    # ali简写
    "aliyun": "dashscope",                 # aliyun阿里云别名
    "custom": OPENAI_COMPATIBLE_PROVIDER,  # custom自定义服务商映射为openai兼容
}


@dataclass(frozen=True)
class ProviderModelSeed:
    """Model seed used to initialize AIModel rows for a new provider.
    不可变数据类(frozen=True)：模型种子，用于新建AI服务商时初始化AIModel数据库记录
    frozen=True：实例创建后属性不可修改，保证种子数据只读安全
    """
    model_id: str      # 模型底层ID，调用API时使用，例如 gpt‑4o、qwen‑turbo
    model_name: str    # 前端展示的模型名称
    model_type: str    # 模型类型：chat对话 / embedding向量嵌入


def normalize_provider_key(provider: str) -> str:
    """Normalize provider aliases to the canonical key used by default templates.
    将传入的服务商名称做标准化归一化，把别名、简写统一成系统内部标准key
    :param provider: 用户传入的服务商原始字符串，可以为空、大小写混乱、别名
    :return: 系统内部标准服务商key
    """
    # 去除首尾空格、全部转小写
    raw = (provider or "").strip().lower()
    # 如果为空字符串，兜底返回openai兼容模式
    if not raw:
        return OPENAI_COMPATIBLE_PROVIDER
    # 在别名字典查找，找到则返回标准key；找不到返回原始归一化字符串
    return _PROVIDER_ALIASES.get(raw, raw)


def resolve_initial_model_seeds(
    db: Session,
    provider: str,
    requested_models: list[str] | None,
) -> list[ProviderModelSeed]:
    """Resolve the model list used at provider creation time.
    【入口函数】服务商创建时，解析需要初始化的模型种子列表
    两种分支：①用户手动指定模型列表；②使用数据库预配置的默认模型
    :param db: SQLAlchemy数据库会话
    :param provider: 原始服务商名称字符串
    :param requested_models: 用户手动传入的模型ID列表，None代表用户没有指定
    :return: ProviderModelSeed种子对象列表，用于后续写入模型记录
    """
    # 如果用户手动传入了模型列表，直接基于用户输入生成种子
    if requested_models:
        return _seeds_from_requested_models(requested_models)
    # 用户没有指定模型，从数据库读取该服务商预置默认模型种子
    return get_default_model_seeds(db, provider)


def get_default_model_seeds(db: Session, provider: str) -> list[ProviderModelSeed]:
    """Load default model seeds from DB for a provider, with openai‑compatible fallback.
    从数据库加载服务商的默认模型种子，带降级兜底逻辑
    降级策略：如果该服务商没有配置激活的默认模型，则回退使用 openai_compatible 的默认模型
    :param db: 数据库会话
    :param provider: 原始服务商名称
    :return: ProviderModelSeed对象列表
    """
    # 第一步归一化服务商key
    provider_key = normalize_provider_key(provider)
    # 查询数据库获取该服务商的激活默认模型行
    rows = _load_default_rows(db, provider_key)

    # 如果查询结果为空，并且当前不是openai兼容本身，则降级读取openai_compatible的默认模型
    if not rows and provider_key != OPENAI_COMPATIBLE_PROVIDER:
        rows = _load_default_rows(db, OPENAI_COMPATIBLE_PROVIDER)

    # 将数据库ORM行对象，转换为ProviderModelSeed种子对象
    # 容错：model_name为空就复用model_id；model_type为空调用函数自动推断模型类型
    return [
        ProviderModelSeed(
            model_id=row.model_id,
            model_name=row.model_name or row.model_id,
            model_type=row.model_type or infer_model_type(row.model_id),
        )
        for row in rows
    ]


def infer_model_type(model_id: str) -> str:
    """根据model_id字符串简单推断模型类型
    规则：model_id包含embedding → embedding向量模型；其余默认chat对话模型
    :param model_id: 模型ID字符串
    :return: "embedding" | "chat"
    """
    return "embedding" if "embedding" in model_id.lower() else "chat"


def _seeds_from_requested_models(models: Iterable[str]) -> list[ProviderModelSeed]:
    """
    私有函数：根据用户手动输入的模型ID列表生成ProviderModelSeed种子
    做去重、空值过滤；model_name直接复用model_id，模型ID推断model_type
    :param models: 用户传入的模型ID可迭代对象
    :return: 去重后的种子列表，保持输入顺序
    """
    ordered_seeds: list[ProviderModelSeed] = []
    seen_model_ids: set[str] = set()  # 集合用于记录已经处理过的model_id，实现去重

    for raw_model_id in models:
        model_id = raw_model_id.strip()
        # 空字符串跳过；已经出现过的model_id跳过，去重
        if not model_id or model_id in seen_model_ids:
            continue
        seen_model_ids.add(model_id)
        # 构建种子对象：名称直接用model_id，类型自动推断
        ordered_seeds.append(
            ProviderModelSeed(
                model_id=model_id,
                model_name=model_id,
                model_type=infer_model_type(model_id),
            )
        )
    return ordered_seeds


def _load_default_rows(db: Session, provider: str) -> list[AIProviderDefaultModel]:
    """
    私有函数：执行SQL查询，读取指定服务商激活状态的默认模型配置
    排序规则：sort_order升序优先，sort_order相同时按model_id升序
    :param db: 数据库会话
    :param provider: 归一化后的标准服务商key
    :return: AIProviderDefaultModel ORM行对象列表
    """
    stmt = (
        select(AIProviderDefaultModel)
        .where(
            AIProviderDefaultModel.provider == provider,       # 匹配服务商key
            AIProviderDefaultModel.is_active.is_(True),        # 只查询启用/激活的默认模型
        )
        .order_by(
            AIProviderDefaultModel.sort_order.asc(),    # 先按排序号从小到大
            AIProviderDefaultModel.model_id.asc()       # 排序号相同，再按模型ID字母升序
        )
    )
    # scalars取出ORM实体对象，.all()获取全部结果，转list返回
    return list(db.scalars(stmt).all())