"""Redis-based bind code service."""

import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import redis.asyncio as redis

from app.config import settings
from app.core.logging import get_logger

logger = get_logger("services.bind_code_service")


"""
设备绑定码服务，基于Redis实现设备绑定验证码管理
场景：设备端输入绑定码，后端校验绑定码，完成设备与项目project_id的绑定
能力：生成唯一绑定码、过期自动失效、一次性使用、失败尝试限流
"""

class BindCodeService:
    """Service for managing device bind codes in Redis.
    管理设备绑定码的服务类，全部绑定码数据存放于Redis，不落地数据库表
    """

    # Redis key前缀：绑定码存储key 格式 dc:bind_code:{code值}，value存放project_id字符串
    KEY_PREFIX = "dc:bind_code:"
    # Redis key前缀：绑定失败计次限流key 格式 dc:bind_attempts:{标识符}
    ATTEMPT_PREFIX = "dc:bind_attempts:"
    # 同一个标识符最大失败尝试次数
    MAX_ATTEMPTS = 5
    # 失败计次的时间窗口，单位秒，1小时。超过窗口次数清零
    ATTEMPT_WINDOW = 3600  # 1 hour

    def __init__(self):
        """初始化，创建redis客户端实例"""
        logger.info(f"[DEBUG] BindCodeService initializing with REDIS_URL: {settings.REDIS_URL}")
        # decode_responses=True：redis返回结果直接是字符串，不再返回bytes字节
        self.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
        logger.info(f"[DEBUG] BindCodeService Redis client created")

    def _generate_code(self) -> str:
        """Generate a random alphanumeric code.
        私有方法：生成随机大写字母+数字的绑定码
        长度读取配置 settings.BIND_CODE_LENGTH
        """
        return "".join(
            random.choices(
                string.ascii_uppercase + string.digits, k=settings.BIND_CODE_LENGTH
            )
        )

    async def generate(self, project_id: uuid.UUID) -> Tuple[str, datetime]:
        """
        Generate a unique bind code and store it in Redis.
        Returns the code and its expiration time.
        为某个项目生成唯一设备绑定码，存入Redis
        :param project_id: 项目UUID，绑定码归属哪个项目
        :return: (bind_code字符串, 过期时间utc时间对象)
        """
        logger.info(f"[DEBUG] Generating bind code for project {project_id}")
        logger.info(f"[DEBUG] Redis URL: {settings.REDIS_URL}")
        
        # 最多重试5次：防止生成的随机码在redis已经存在，保证全局唯一
        for attempt in range(5):  # Retry up to 5 times if code exists
            code = self._generate_code()
            key = f"{self.KEY_PREFIX}{code}"
            logger.info(f"[DEBUG] Attempt {attempt + 1}: Generated code {code}, key={key}")

            try:
                # setnx：SET if Not eXists。redis原子命令，key不存在才写入，返回True；key已存在返回False
                # 作用：并发下保证bind_code全局唯一，防止多个项目拿到同一个绑定码
                success = await self.redis.setnx(key, str(project_id))
                logger.info(f"[DEBUG] SETNX result for {key}: {success}")
                
                if success:
                    # 设置key过期时间，配置项BIND_CODE_EXPIRY_MINUTES（分钟）转秒
                    expiry_seconds = settings.BIND_CODE_EXPIRY_MINUTES * 60
                    await self.redis.expire(key, expiry_seconds)
                    logger.info(f"[DEBUG] Set expiry {expiry_seconds}s for key {key}")

                    # 计算UTC标准的过期时间，返回给上层接口展示给用户
                    expires_at = datetime.now(timezone.utc) + timedelta(
                        minutes=settings.BIND_CODE_EXPIRY_MINUTES
                    )
                    logger.info(f"[DEBUG] Generated bind code {code} for project {project_id}, expires_at={expires_at}")
                    return code, expires_at
            except Exception as e:
                logger.error(f"[DEBUG] Redis error during bind code generation: {e}", exc_info=True)
                raise

        # 循环5次全部失败，没有找到不重复的绑定码，抛出异常
        logger.error("[DEBUG] Failed to generate a unique bind code after 5 attempts")
        raise Exception("Failed to generate unique bind code")

    async def validate(self, code: str) -> Optional[uuid.UUID]:
        """
        Validate a bind code and return the associated project_id.
        The code is deleted after successful validation.
        校验用户输入的绑定码
        ✅成功：删除redis中的绑定码（一次性使用，用过即作废），返回归属project_id
        ❌失败：返回None（码不存在、过期、格式错误）
        """
        logger.info(f"[DEBUG] Validating bind code: {code}")

        # 用户输入转大写，做兼容，防止大小写问题
        key = f"{self.KEY_PREFIX}{code.upper()}"
        logger.info(f"[DEBUG] Looking up Redis key: {key}")
        
        try:
            # 根据绑定码查询redis，拿到对应的project_id字符串，归属哪个项目
            project_id_str = await self.redis.get(key)
            logger.info(f"[DEBUG] Redis get result for {key}: {project_id_str}")
        except Exception as e:
            logger.error(f"[DEBUG] Redis error while getting key {key}: {e}", exc_info=True)
            return None

        # key不存在，代表绑定码过期 / 错误 / 已经被使用过
        if not project_id_str:
            logger.warning(f"[DEBUG] Invalid or expired bind code attempt: {code} (key not found in Redis)")
            # 调试用：打印当前redis内全部绑定码，生产环境要删掉keys命令！keys会阻塞redis
            try:
                all_keys = await self.redis.keys(f"{self.KEY_PREFIX}*")
                logger.info(f"[DEBUG] Existing bind code keys in Redis: {all_keys}")
            except Exception as e:
                logger.warning(f"[DEBUG] Could not list Redis keys: {e}")
            return None

        # 校验成功：删除绑定码，一次性，不能重复使用
        logger.info(f"[DEBUG] Bind code valid, deleting key {key}")
        await self.redis.delete(key)

        # 将字符串转成UUID对象返回，如果redis存的数据格式损坏，捕获异常返回None
        try:
            result = uuid.UUID(project_id_str)
            logger.info(f"[DEBUG] Bind code validated successfully, project_id={result}")
            return result
        except ValueError:
            logger.error(f"[DEBUG] Invalid UUID stored in Redis for code {code}: {project_id_str}")
            return None

    async def check_rate_limit(self, identifier: str) -> bool:
        """
        Basic rate limiting for bind code attempts.
        Returns True if allowed, False if rate limited.
        检查是否触发限流
        :param identifier: 限流标识，可以是ip、设备id等，用来区分不同请求方
        :return True=允许尝试；False=超过最大次数，拒绝
        """
        key = f"{self.ATTEMPT_PREFIX}{identifier}"
        # attempts是当前标识符的失败尝试次数，redis不存在key时返回None,get返回字符串，转换成int，这个返回值用于判断是否超过最大尝试次数
        attempts = await self.redis.get(key)

        # 已有记录并且大于等于最大尝试次数，限流拦截
        if attempts and int(attempts) >= self.MAX_ATTEMPTS:
            return False

        return True

    async def record_attempt(self, identifier: str):
        """Record a failed bind code attempt.
        记录一次绑定失败尝试；key不存在自动创建，并且设置过期时间
        """
        key = f"{self.ATTEMPT_PREFIX}{identifier}"
        # incr 原子自增 +1
        await self.redis.incr(key)
        # 设置过期时间，超过时间窗口次数自动重置
        await self.redis.expire(key, self.ATTEMPT_WINDOW)


# 全局单例实例，项目其他地方直接导入bind_code_service使用，不用重复new对象
bind_code_service = BindCodeService()