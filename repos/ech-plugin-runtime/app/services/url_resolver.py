import re
import time
from urllib.parse import urljoin, urlparse
import httpx
import yaml
from typing import Optional, Dict, Any
from app.core.logging import get_logger

logger = get_logger("services.url_resolver")
# 业务定位：TGO 插件系统的URL 解析器。用户输入一个链接（GitHub/Gitee 仓库地址、blob 文件地址、自定义 http 地址），
# 该类自动识别地址类型，下载 plugin.yml / plugin.yaml 插件配置文件，解析 YAML，并把配置里的相对路径自动转为绝对 URL，返回插件配置字典。
class PluginURLResolver:
    """Resolves plugin URL and fetches plugin.yml configuration."""
    '''
    核心能力
    正则匹配识别 GitHub / Gitee 多种 URL 格式（仓库主页、tree 目录、blob 单文件）
    将网页地址转换为 raw 原始文件下载地址
    自动回退查找 plugin.yml / plugin.yaml
    网络请求获取 yaml，做超时、异常捕获、日志打印
    将配置内相对资源路径补全为绝对链接
    支持自定义外部 URL（非 github/gitee）'''
    GITHUB_PATTERN = re.compile(r'^https?://github\.com/([^/]+)/([^/]+)(?:/tree/([^/]+)(?:/(.*))?)?/?$')
    GITHUB_BLOB_PATTERN = re.compile(r'^https?://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.*)$')
    GITEE_PATTERN = re.compile(r'^https?://gitee\.com/([^/]+)/([^/]+)(?:/tree/([^/]+)(?:/(.*))?)?/?$')
    GITEE_BLOB_PATTERN = re.compile(r'^https?://gitee\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.*)$')
    # resolve 方法是入口，接收一个 URL，返回解析后的插件配置字典
    async def resolve(self, url: str) -> Dict[str, Any]:
        """
        Resolve URL and get plugin.yml content.
        Returns a dictionary containing the resolved configuration with absolute URLs for sources.
        """
        url = url.strip()
        
        # 1. Try GitHub Blob URL
        if blob_match := self.GITHUB_BLOB_PATTERN.match(url):
            return await self._resolve_github_blob(blob_match)

        # 2. Try Gitee Blob URL
        if gitee_blob_match := self.GITEE_BLOB_PATTERN.match(url):
            return await self._resolve_gitee_blob(gitee_blob_match)

        # 3. Try GitHub Repo/Tree URL
        if github_match := self.GITHUB_PATTERN.match(url):
            return await self._resolve_github(github_match)
        
        # 4. Try Gitee Repo/Tree URL
        if gitee_match := self.GITEE_PATTERN.match(url):
            return await self._resolve_gitee(gitee_match)
        
        # 5. Custom URL
        return await self._resolve_custom(url)
    
    async def _resolve_github_blob(self, match) -> Dict[str, Any]:
        user, repo, branch, path = match.groups()
        # Convert GitHub blob URL to raw URL. Use refs/heads/ if branch is provided for robustness.
        raw_url = f"https://raw.githubusercontent.com/{user}/{repo}/{branch}/{path}"
        base_url = raw_url.rsplit('/', 1)[0] + '/'
        
        config = await self._try_fetch_yaml(raw_url)
        if config:
            return self._resolve_relative_urls(config, base_url)
        
        raise ValueError(f"Could not fetch or parse plugin configuration from {raw_url}")

    async def _resolve_gitee_blob(self, match) -> Dict[str, Any]:
        user, repo, branch, path = match.groups()
        # Convert Gitee blob URL to raw URL
        raw_url = f"https://gitee.com/{user}/{repo}/raw/{branch}/{path}"
        base_url = raw_url.rsplit('/', 1)[0] + '/'
        
        config = await self._try_fetch_yaml(raw_url)
        if config:
            return self._resolve_relative_urls(config, base_url)
        
        raise ValueError(f"Could not fetch or parse plugin configuration from {raw_url}")

    async def _resolve_github(self, match) -> Dict[str, Any]:
        user, repo, branch, path = match.groups()
        branches = [branch] if branch else ['main', 'master']
        path = path.strip('/') if path else ""
        
        for br in branches:
            base_url = f"https://raw.githubusercontent.com/{user}/{repo}/{br}/"
            if path:
                base_url = urljoin(base_url, path + '/')
            
            config = await self._fetch_yaml_with_fallbacks(base_url)
            if config:
                return self._resolve_relative_urls(config, base_url)
        
        raise ValueError("Could not find plugin.yml or plugin.yaml in the GitHub repository.")

    async def _resolve_gitee(self, match) -> Dict[str, Any]:
        user, repo, branch, path = match.groups()
        branches = [branch] if branch else ['master', 'main']
        path = path.strip('/') if path else ""
        
        for br in branches:
            base_url = f"https://gitee.com/{user}/{repo}/raw/{br}/"
            if path:
                base_url = urljoin(base_url, path + '/')
                
            config = await self._fetch_yaml_with_fallbacks(base_url)
            if config:
                return self._resolve_relative_urls(config, base_url)
        
        raise ValueError("Could not find plugin.yml or plugin.yaml in the Gitee repository.")
    # _resolve_custom 方法处理自定义 URL，尝试获取 plugin.yml 或 plugin.yaml，并解析相对路径为绝对 URL
    async def _resolve_custom(self, url: str) -> Dict[str, Any]:
        """Handle custom URLs."""
        parsed = urlparse(url)
        path = parsed.path
        
        # If it points directly to a YAML file
        if path.endswith(('.yml', '.yaml')):
            yaml_url = url
            base_url = url.rsplit('/', 1)[0] + '/'
            config = await self._try_fetch_yaml(yaml_url)
            if config:
                return self._resolve_relative_urls(config, base_url)
        else:
            # Directory URL, auto-append plugin.yml
            base_url = url if url.endswith('/') else url + '/'
            config = await self._fetch_yaml_with_fallbacks(base_url)
            if config:
                return self._resolve_relative_urls(config, base_url)
        
        raise ValueError("Could not find or parse plugin.yml/plugin.yaml at the provided URL.")
    # _fetch_yaml_with_fallbacks 方法尝试从 base_url 获取 plugin.yml 或 plugin.yaml，并返回解析后的配置字典
    async def _fetch_yaml_with_fallbacks(self, base_url: str) -> Optional[Dict[str, Any]]:
        """Try fetching plugin.yml then plugin.yaml."""
        for filename in ['plugin.yml', 'plugin.yaml']:
            yaml_url = urljoin(base_url, filename)
            config = await self._try_fetch_yaml(yaml_url)
            if config:
                return config
        return None
    # _try_fetch_yaml 方法尝试获取指定 URL 的 YAML 文件，并解析为字典，处理网络异常和 YAML 解析异常
    async def _try_fetch_yaml(self, url: str) -> Optional[Dict[str, Any]]:
        """Attempt to fetch and parse a YAML file."""
        # Bypass cache for GitHub/Gitee by adding a timestamp
        if "raw.githubusercontent.com" in url or "gitee.com" in url:
            separator = "&" if "?" in url else "?"
            fetch_url = f"{url}{separator}t={int(time.time())}"
        else:
            fetch_url = url

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(fetch_url, follow_redirects=True)
                if response.status_code == 200:
                    try:
                        return yaml.safe_load(response.text)
                    except yaml.YAMLError as e:
                        logger.error(f"Failed to parse YAML from {fetch_url}: {e}")
                        return None
        except Exception as e:
            logger.error(f"Failed to fetch {fetch_url}: {e}")
        return None
    # _resolve_relative_urls 方法将配置中的相对路径转换为绝对 URL，使用 base_url 作为基准
    def _resolve_relative_urls(self, config: Dict[str, Any], base_url: str) -> Dict[str, Any]:
        """Convert relative paths in configuration to absolute URLs using base_url."""
        if 'source' in config:
            source = config['source']
            # Handle binary source
            if 'binary' in source and 'url' in source['binary']:
                url = source['binary']['url']
                if not url.startswith(('http://', 'https://')):
                    source['binary']['url'] = urljoin(base_url, url)
            
            # Handle github source path (if it were relative to the yml, but usually it's repo-based)
            # However, if it's a relative path in a repo, it might be useful.
            # For now, we mainly focus on binary URLs which are most likely to be relative.
            
        return config

