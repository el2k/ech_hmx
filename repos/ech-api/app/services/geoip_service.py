# =============================================================================
# 模块：GeoIP 服务 (GeoIP service for IP to location lookup)
# =============================================================================
# 该模块提供了根据 IP 地址查询地理位置的公共服务，主要包括：
# 1. IP 地址地理位置查询（国家、地区、城市、ISP）
# 2. 支持两种数据源提供商
# 
# 提供商：
# 1. geoip2 (MaxMind GeoLite2) - 国际覆盖，需要 GeoLite2-City.mmdb
# 2. ip2region (lionsoul2014) - 中国地区数据更好，需要 ip2region.xdb
# 
# 设计目的：
# - 统一封装不同数据源的查询接口
# - 支持 IPv4 和 IPv6
# - 懒加载初始化，减少启动开销
# - 提供数据源切换能力
# 
# 参考：https://github.com/lionsoul2014/ip2region
# =============================================================================

from dataclasses import dataclass
from typing import Optional
import os

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("services.geoip")

# =============================================================================
# 步骤1: 尝试导入 geoip2 库
# =============================================================================
try:
    import geoip2.database
    import geoip2.errors
    GEOIP2_AVAILABLE = True
except ImportError:
    GEOIP2_AVAILABLE = False

# =============================================================================
# 步骤2: 尝试导入 ip2region 库（官方 py-ip2region 包 v3+）
# =============================================================================
# 参考：https://pypi.org/project/py-ip2region/
try:
    import ip2region.searcher as xdb_searcher
    import ip2region.util as xdb_util
    IP2REGION_AVAILABLE = True
except ImportError:
    IP2REGION_AVAILABLE = False


# =============================================================================
# 步骤3: 地理位置数据类
# =============================================================================

@dataclass
class GeoLocation:
    """
    从 IP 地址派生的地理位置数据。

    Attributes:
        country: 国家名称（如 "中国"）
        country_code: 国家代码（如 "CN"）
        region: 地区/省份（如 "广东省"）
        city: 城市（如 "深圳市"）
        isp: 互联网服务提供商（仅 ip2region 提供）
    """
    country: Optional[str] = None
    country_code: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    isp: Optional[str] = None  # 仅 ip2region 支持

    def is_empty(self) -> bool:
        """检查是否所有字段都为空。"""
        return not any([self.country, self.country_code, self.region, self.city])


# =============================================================================
# 步骤4: GeoIP 服务类
# =============================================================================

class GeoIPService:
    """
    根据 IP 地址查询地理位置的 GeoIP 服务。

    支持两种数据源：
    - geoip2: MaxMind GeoLite2 数据库
    - ip2region: lionsoul2014 的 ip2region 数据库（中国地区数据更准确）

    设计特点：
    - 懒加载：在首次查询时初始化数据库
    - 自动选择：根据配置选择数据源
    - 双栈支持：同时支持 IPv4 和 IPv6
    - 容错处理：数据库加载失败时优雅降级
    """

    def __init__(self):
        # geoip2 数据库读取器
        self._geoip2_reader: Optional["geoip2.database.Reader"] = None
        # ip2region 使用独立的 IPv4 和 IPv6 数据库
        self._ip2region_searcher_v4: Optional[xdb_searcher.Searcher] = None
        self._ip2region_searcher_v6: Optional[xdb_searcher.Searcher] = None
        self._initialized = False
        self._init_error: Optional[str] = None
        self._provider: Optional[str] = None

    # =========================================================================
    # 懒加载初始化
    # =========================================================================

    def _ensure_initialized(self) -> bool:
        """
        懒加载初始化 GeoIP 数据库读取器。

        执行流程：
        1. 如果已初始化，直接返回状态
        2. 检查配置是否启用 GeoIP
        3. 根据 provider 类型加载对应数据库
        4. 记录加载结果

        Returns:
            bool: 初始化成功返回 True，否则返回 False
        """
        if self._initialized:
            # 检查是否有可用的读取器
            has_ip2region = (
                self._ip2region_searcher_v4 is not None or
                self._ip2region_searcher_v6 is not None
            )
            return self._geoip2_reader is not None or has_ip2region

        self._initialized = True

        # 检查 GeoIP 是否启用
        if not settings.GEOIP_ENABLED:
            self._init_error = "GeoIP is disabled in settings"
            return False

        db_path = settings.GEOIP_DATABASE_PATH
        if not db_path:
            self._init_error = "GEOIP_DATABASE_PATH not configured"
            logger.info("GeoIP database path not configured. IP geolocation disabled.")
            return False

        provider = settings.GEOIP_PROVIDER.lower()
        self._provider = provider

        # 根据提供者类型加载数据库
        if provider == "ip2region":
            return self._init_ip2region(db_path)
        elif provider == "geoip2":
            if not os.path.exists(db_path):
                self._init_error = f"GeoIP database file not found: {db_path}"
                logger.warning(f"GeoIP database file not found: {db_path}")
                return False
            return self._init_geoip2(db_path)
        else:
            self._init_error = f"Unknown GeoIP provider: {provider}"
            logger.error(f"Unknown GeoIP provider: {provider}. Supported: 'geoip2', 'ip2region'")
            return False

    # =========================================================================
    # ip2region 初始化
    # =========================================================================

    def _init_ip2region(self, db_path: str) -> bool:
        """
        初始化 ip2region 查询器。

        ip2region 使用独立的 IPv4 和 IPv6 数据库。
        db_path 可以是：
        - 单个文件路径（根据文件名自动检测版本）
        - 包含 ip2region_v4.xdb 和/或 ip2region_v6.xdb 的目录

        参考：https://pypi.org/project/py-ip2region/

        Args:
            db_path: 数据库路径（文件或目录）

        Returns:
            bool: 至少加载了一个数据库返回 True
        """
        if not IP2REGION_AVAILABLE:
            self._init_error = "py-ip2region library not installed. Run: pip install py-ip2region"
            logger.warning("py-ip2region library not installed. IP geolocation disabled.")
            return False

        loaded_any = False

        # 情况1: db_path 是目录
        if os.path.isdir(db_path):
            # 在目录中查找 v4 和 v6 的 xdb 文件
            v4_path = os.path.join(db_path, "ip2region_v4.xdb")
            v6_path = os.path.join(db_path, "ip2region_v6.xdb")

            if os.path.exists(v4_path):
                if self._load_ip2region_db(v4_path, xdb_util.IPv4, "IPv4"):
                    loaded_any = True

            if os.path.exists(v6_path):
                if self._load_ip2region_db(v6_path, xdb_util.IPv6, "IPv6"):
                    loaded_any = True
        else:
            # 情况2: db_path 是单个文件 - 从文件名检测版本
            if not os.path.exists(db_path):
                self._init_error = f"ip2region database file not found: {db_path}"
                logger.warning(f"ip2region database file not found: {db_path}")
                return False

            # 从文件名判断 IP 版本
            filename = os.path.basename(db_path).lower()
            if "v6" in filename or "ipv6" in filename:
                if self._load_ip2region_db(db_path, xdb_util.IPv6, "IPv6"):
                    loaded_any = True
            else:
                # 默认为 IPv4
                if self._load_ip2region_db(db_path, xdb_util.IPv4, "IPv4"):
                    loaded_any = True

        if not loaded_any:
            self._init_error = "Failed to load any ip2region database"
            return False

        return True

    def _load_ip2region_db(self, db_path: str, version: int, version_name: str) -> bool:
        """
        加载单个 ip2region 数据库文件。

        Args:
            db_path: 数据库文件路径
            version: IP 版本（xdb_util.IPv4 或 xdb_util.IPv6）
            version_name: 版本名称（用于日志）

        Returns:
            bool: 加载成功返回 True
        """
        try:
            # 将整个 xdb 加载到内存中，以获得最佳性能和线程安全性
            # 注意：load_content_from_file 在 util 模块中，不在 searcher 中
            searcher = xdb_searcher.new_with_file_only(
                xdb_util.Version(version), db_path
            )

            if version == xdb_util.IPv4:
                self._ip2region_searcher_v4 = searcher
            else:
                self._ip2region_searcher_v6 = searcher

            logger.info(f"ip2region {version_name} database loaded from {db_path}")
            return True
        except Exception as e:
            logger.warning(f"Failed to load ip2region {version_name} database from {db_path}: {e}")
            return False

    # =========================================================================
    # geoip2 初始化
    # =========================================================================

    def _init_geoip2(self, db_path: str) -> bool:
        """
        初始化 geoip2 读取器。

        Args:
            db_path: GeoIP2 数据库文件路径

        Returns:
            bool: 初始化成功返回 True
        """
        if not GEOIP2_AVAILABLE:
            self._init_error = "geoip2 library not installed. Run: pip install geoip2"
            logger.warning("geoip2 library not installed. IP geolocation disabled.")
            return False

        try:
            self._geoip2_reader = geoip2.database.Reader(db_path)
            logger.info(f"GeoIP2 database loaded successfully from {db_path}")
            return True
        except Exception as e:
            self._init_error = f"Failed to load GeoIP2 database: {e}"
            logger.error(f"Failed to load GeoIP2 database: {e}")
            return False

    # =========================================================================
    # 公开查询接口
    # =========================================================================

    def lookup(self, ip_address: Optional[str]) -> GeoLocation:
        """
        查询 IP 地址的地理位置数据。

        执行流程：
        1. 验证 IP 地址是否有效
        2. 确保数据库已初始化
        3. 跳过私有 IP 地址
        4. 根据配置的 provider 调用对应的查询方法

        Args:
            ip_address: 要查询的 IP 地址（IPv4 或 IPv6）

        Returns:
            GeoLocation: 包含地理位置数据的对象，查询失败时返回空对象
        """
        if not ip_address:
            return GeoLocation()

        if not self._ensure_initialized():
            return GeoLocation()

        # 跳过私有/本地 IP 地址
        if self._is_private_ip(ip_address):
            return GeoLocation()

        # 根据提供者类型进行查询
        if self._provider == "ip2region":
            has_searcher = self._ip2region_searcher_v4 or self._ip2region_searcher_v6
            if has_searcher:
                return self._lookup_ip2region(ip_address)
        elif self._provider == "geoip2" and self._geoip2_reader:
            return self._lookup_geoip2(ip_address)

        return GeoLocation()

    def _is_ipv6(self, ip_address: str) -> bool:
        """检查 IP 地址是否为 IPv6（简单判断：包含冒号）。"""
        return ":" in ip_address

    # =========================================================================
    # ip2region 查询
    # =========================================================================

    def _lookup_ip2region(self, ip_address: str) -> GeoLocation:
        """
        使用 ip2region 查询地理位置。

        ip2region 返回格式（管道符分隔）：
        - 标准格式：国家|区域|省份|城市|ISP（5 部分）
        - 简化格式：国家|省份|城市|ISP（4 部分）
        - 示例（5部分）：中国|0|广东省|深圳市|电信
        - 示例（4部分）：中国|广东省|深圳市|电信

        Args:
            ip_address: IP 地址

        Returns:
            GeoLocation: 地理位置数据
        """
        try:
            # 根据 IP 版本选择对应的查询器
            is_v6 = self._is_ipv6(ip_address)

            if is_v6:
                searcher = self._ip2region_searcher_v6
                if not searcher:
                    logger.debug(f"No IPv6 searcher available for {ip_address}")
                    return GeoLocation()
            else:
                searcher = self._ip2region_searcher_v4
                if not searcher:
                    logger.debug(f"No IPv4 searcher available for {ip_address}")
                    return GeoLocation()

            # 执行查询
            result = searcher.search(ip_address)
            if not result:
                return GeoLocation()

            # 解析结果（管道符分隔）
            parts = result.split("|")

            # 解析不同格式
            if len(parts) == 5:
                # 标准格式：国家|区域|省份|城市|ISP
                country = parts[0] if parts[0] != "0" else None
                # parts[1] 通常是 "0"（保留区域），跳过
                region = parts[2] if parts[2] != "0" else None
                city = parts[3] if parts[3] != "0" else None
                isp = parts[4] if parts[4] != "0" else None
            elif len(parts) == 4:
                # 简化格式：国家|省份|城市|ISP
                country = parts[0] if parts[0] != "0" else None
                region = parts[1] if parts[1] != "0" else None
                city = parts[2] if parts[2] != "0" else None
                isp = parts[3] if parts[3] != "0" else None
            else:
                # 兼容其他长度（如 v1 格式为 5 部分）
                country = parts[0] if len(parts) > 0 and parts[0] != "0" else None
                region = parts[2] if len(parts) > 2 and parts[2] != "0" else None
                city = parts[3] if len(parts) > 3 and parts[3] != "0" else None
                isp = parts[4] if len(parts) > 4 and parts[4] != "0" else None

            # 生成国家代码
            country_code = self._get_country_code(country)

            return GeoLocation(
                country=country,
                country_code=country_code,
                region=region,
                city=city,
                isp=isp,
            )
        except Exception as e:
            logger.warning(f"ip2region lookup failed for {ip_address}: {e}")
            return GeoLocation()

    # =========================================================================
    # geoip2 查询
    # =========================================================================

    def _lookup_geoip2(self, ip_address: str) -> GeoLocation:
        """
        使用 geoip2 查询地理位置。

        Args:
            ip_address: IP 地址

        Returns:
            GeoLocation: 地理位置数据
        """
        try:
            response = self._geoip2_reader.city(ip_address)

            return GeoLocation(
                country=response.country.name,
                country_code=response.country.iso_code,
                region=response.subdivisions.most_specific.name if response.subdivisions else None,
                city=response.city.name,
            )
        except geoip2.errors.AddressNotFoundError:
            # IP 地址在数据库中不存在
            logger.debug(f"IP address not found in GeoIP database: {ip_address}")
            return GeoLocation()
        except Exception as e:
            logger.warning(f"GeoIP2 lookup failed for {ip_address}: {e}")
            return GeoLocation()

    # =========================================================================
    # 国家代码映射
    # =========================================================================

    def _get_country_code(self, country: Optional[str]) -> Optional[str]:
        """
        从国家名称获取 ISO 国家代码（用于 ip2region）。

        Args:
            country: 国家名称（中文）

        Returns:
            Optional[str]: 两位字母的国家代码
        """
        if not country:
            return None

        # 常见国家名称到代码的映射
        country_codes = {
            "中国": "CN",
            "美国": "US",
            "日本": "JP",
            "韩国": "KR",
            "英国": "GB",
            "德国": "DE",
            "法国": "FR",
            "俄罗斯": "RU",
            "加拿大": "CA",
            "澳大利亚": "AU",
            "新加坡": "SG",
            "印度": "IN",
            "巴西": "BR",
            "意大利": "IT",
            "西班牙": "ES",
            "荷兰": "NL",
            "瑞士": "CH",
            "瑞典": "SE",
            "挪威": "NO",
            "丹麦": "DK",
            "芬兰": "FI",
            "波兰": "PL",
            "奥地利": "AT",
            "比利时": "BE",
            "爱尔兰": "IE",
            "新西兰": "NZ",
            "墨西哥": "MX",
            "阿根廷": "AR",
            "智利": "CL",
            "南非": "ZA",
            "埃及": "EG",
            "土耳其": "TR",
            "以色列": "IL",
            "阿联酋": "AE",
            "沙特阿拉伯": "SA",
            "泰国": "TH",
            "越南": "VN",
            "马来西亚": "MY",
            "印度尼西亚": "ID",
            "菲律宾": "PH",
            "中国台湾": "TW",
            "台湾": "TW",
            "中国香港": "HK",
            "香港": "HK",
            "中国澳门": "MO",
            "澳门": "MO",
        }
        return country_codes.get(country)

    # =========================================================================
    # 私有 IP 检测
    # =========================================================================

    def _is_private_ip(self, ip_address: str) -> bool:
        """
        检查 IP 地址是否为私有/本地地址。

        私有 IP 范围：
        - 10.0.0.0/8
        - 172.16.0.0/12
        - 192.168.0.0/16
        - 127.0.0.0/8（本地回环）
        - ::1（IPv6 回环）
        - fe80::/10（IPv6 链路本地）

        Args:
            ip_address: IP 地址

        Returns:
            bool: 是私有地址返回 True
        """
        private_prefixes = (
            "10.",
            "172.16.", "172.17.", "172.18.", "172.19.",
            "172.20.", "172.21.", "172.22.", "172.23.",
            "172.24.", "172.25.", "172.26.", "172.27.",
            "172.28.", "172.29.", "172.30.", "172.31.",
            "192.168.",
            "127.",
            "localhost",
            "::1",
            "fe80:",  # IPv6 链路本地
        )
        # startswith 检查是否以任何私有前缀开头
        return ip_address.startswith(private_prefixes)

    # =========================================================================
    # 资源清理
    # =========================================================================

    def close(self):
        """关闭数据库读取器，释放资源。"""
        if self._geoip2_reader:
            self._geoip2_reader.close()
            self._geoip2_reader = None
        if self._ip2region_searcher_v4:
            self._ip2region_searcher_v4.close()
            self._ip2region_searcher_v4 = None
        if self._ip2region_searcher_v6:
            self._ip2region_searcher_v6.close()
            self._ip2region_searcher_v6 = None

    # =========================================================================
    # 属性方法
    # =========================================================================

    @property
    def is_available(self) -> bool:
        """检查 GeoIP 查询是否可用。"""
        return self._ensure_initialized()

    @property
    def provider(self) -> Optional[str]:
        """获取当前使用的提供者名称。"""
        self._ensure_initialized()
        return self._provider

    @property
    def status(self) -> str:
        """获取 GeoIP 服务的当前状态。"""
        if not self._initialized:
            self._ensure_initialized()

        has_ip2region = (
            self._ip2region_searcher_v4 is not None or
            self._ip2region_searcher_v6 is not None
        )
        if self._geoip2_reader is not None or has_ip2region:
            details = []
            if self._ip2region_searcher_v4:
                details.append("IPv4")
            if self._ip2region_searcher_v6:
                details.append("IPv6")
            if self._geoip2_reader:
                details.append("geoip2")
            return f"ready ({self._provider}: {', '.join(details)})"
        return self._init_error or "not initialized"


# =============================================================================
# 全局单例实例
# =============================================================================

# 导出全局单例，供其他模块使用
geoip_service = GeoIPService()