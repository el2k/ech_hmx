"""Client for synchronizing Platform records to the TGO Platform Service.

This module encapsulates HTTP calls to the external Platform Service so callers
can focus on business logic. Endpoints are derived from settings and the
platform service OpenAPI (docs/api_platform_service.json).

Current implementation uses POST /v1/platforms with the record body.
If the remote service supports update/delete via REST, you can extend methods
accordingly (e.g., PATCH/DELETE /v1/platforms/{id}).
"""
# __future__注解：允许在类型注解直接使用还未定义的类，提升向前兼容性
from __future__ import annotations

from typing import Any, Dict, Optional

# httpx：异步HTTP客户端，用来调用远端Platform Service接口
import httpx

# 全局配置，读取环境变量：服务地址、超时时间、调用鉴权密钥
from app.core.config import settings


def _platform_to_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """Map local Platform fields to Platform Service request body.

    The OpenAPI specifies PlatformCreateRequest fields.
    We include id to allow idempotent upsert behavior.

    将本地数据库Platform记录字典，转换为远端TGO Platform Service接口请求体
    遵循对方OpenAPI定义的PlatformCreateRequest数据结构
    主动带上本地id，实现幂等upsert：远端根据id存在则更新、不存在则新建
    """
    payload: Dict[str, Any] = {
        # UUID转字符串传给远端；防御data没有id的边界情况赋值None
        "id": str(data["id"]) if data.get("id") else None,
        "project_id": str(data["project_id"]),   # 多租户项目ID，转字符串
        "name": data["name"],                    # 渠道展示名称
        "type": data["type"],                    # 渠道类型：wechat / website等
        "config": data.get("config"),            # 渠道配置JSON，允许为空
        "is_active": data.get("is_active", True),# 渠道是否启用，取不到默认True
        "api_key": data.get("api_key"),          # 渠道对接凭证，可为null
    }
    return payload


class PlatformSyncClient:
    """
    TGO Platform Service HTTP异步客户端封装
    职责：隔离所有和远端平台服务的网络调用；上层业务/同步任务不需要关心url、header、鉴权、http细节
    """
    def __init__(self) -> None:
        # 基础地址，去除末尾斜杠，避免拼接url出现双斜杠 https://xxx//v1/platforms
        self.base_url = settings.PLATFORM_SERVICE_URL.rstrip("/")
        # HTTP请求超时时间，从配置读取
        self.timeout = settings.PLATFORM_SERVICE_TIMEOUT
        # 调用远端服务全局Bearer鉴权token
        self.api_key = settings.PLATFORM_SERVICE_API_KEY

    def _headers(self) -> Dict[str, str]:
        """构造HTTP请求头：Content‑Type + Bearer鉴权头"""
        headers = {"Content-Type": "application/json"}
        # 如果配置了api_key，则追加Authorization头部；支持无鉴权的调试环境
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def upsert_platform(self, platform_data: Dict[str, Any]) -> httpx.Response:
        """Create or upsert a platform via POST /v1/platforms.

        The remote service auto‑generates id if omitted; we include id to keep
        records synchronized across services.

        【幂等新增/更新渠道】调用远端POST /v1/platforms
        远端逻辑：请求携带id，数据库存在该id就更新，不存在就创建
        如果不传id远端会自动生成新id，会造成两边id不一致，所以我们强制传入本地id
        :param platform_data: 本地Platform模型转为的字典
        :return: httpx完整响应对象，由调用方处理状态码、异常
        """
        url = f"{self.base_url}/v1/platforms"
        # 本地字段映射为远端请求体
        payload = _platform_to_payload(platform_data)
        # 异步httpx上下文管理器：自动创建、释放http连接
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload, headers=self._headers())
        return resp

    async def delete_platform(self, platform_id: str) -> Optional[httpx.Response]:
        """Attempt to delete a platform. If DELETE is unsupported, return None.

        We try DELETE /v1/platforms/{id}. If the endpoint doesn't exist, callers
        should fall back to a soft‑delete upsert (deleted_at set, or is_active=False).

        请求远端删除渠道记录 DELETE /v1/platforms/{platform_id}
        容错设计：如果远端接口不存在/网络异常返回None，上层需要降级处理
        降级方案：不调用真实DELETE，改用upsert推送is_active=False / deleted_at做远端软删除
        :param platform_id: 本地渠道UUID字符串
        :return: 成功返回Response；非HTTP状态码类异常返回None
        """
        url = f"{self.base_url}/v1/platforms/{platform_id}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.delete(url, headers=self._headers())
                return resp
            except httpx.HTTPStatusError:
                # httpx开启raise_for_status时，4xx/5xx抛出HTTPStatusError，重新抛出给上层处理
                # 例如404：远端找不到这条记录；401鉴权失败；500服务内部错误，交给上层同步任务捕获
                raise
            except Exception:
                # 其余异常：连接超时、DNS失败、连接拒绝等网络异常 → 返回None，代表delete接口不可用
                return None


# 全局单例，整个应用复用同一个客户端实例对象（注意：httpx client不要长期持有，内部每次方法都新建临时AsyncClient）
platform_sync_client = PlatformSyncClient()