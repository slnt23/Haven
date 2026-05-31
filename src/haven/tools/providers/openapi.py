"""OpenAPIProvider — REST API → Tool。

解析 OpenAPI 3.x 规范，将每个端点映射为 HavenTool。
支持本地文件路径和远程 URL，自动推断参数 schema。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import yaml

from haven.tools.base import HavenTool, ToolMetadata, ToolCategory, ToolPermission
from haven.tools.providers.base import ToolProvider

logger = logging.getLogger("haven.tools.openapi")


class OpenAPIProvider(ToolProvider):
    """OpenAPI 规范工具提供者。

    配置示例::

        OpenAPIProvider(
            name="github",
            spec_path="https://api.github.com/openapi.json",
            base_url="https://api.github.com",
            headers={"Authorization": "Bearer ${GITHUB_TOKEN}"},
        )
    """

    def __init__(
        self,
        name: str,
        spec_path: str,
        *,
        base_url: str = "",
        headers: dict[str, str] | None = None,
        include_tags: list[str] | None = None,
        exclude_tags: list[str] | None = None,
    ):
        super().__init__(name, provider_type="openapi")
        self._spec_path = spec_path
        self._base_url = base_url
        self._headers = headers or {}
        self._include_tags = include_tags
        self._exclude_tags = exclude_tags or []
        self._spec: dict[str, Any] = {}

    async def _on_start(self) -> None:
        self._spec = await self._load_spec()

    async def discover(self) -> list[HavenTool]:
        if not self._spec:
            return []

        tools: list[HavenTool] = []
        paths = self._spec.get("paths", {})

        for path, methods in paths.items():
            for method, operation in methods.items():
                if method.upper() not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                    continue
                if not isinstance(operation, dict):
                    continue

                tags = operation.get("tags", [])
                if self._exclude_tags and any(t in self._exclude_tags for t in tags):
                    continue
                if self._include_tags and not any(t in self._include_tags for t in tags):
                    continue

                tool = self._operation_to_tool(path, method, operation)
                if tool:
                    tools.append(tool)

        logger.info("OpenAPI '%s': %d tools", self.info.name, len(tools))
        return tools

    async def health_check(self) -> bool:
        return bool(self._spec)

    # ========== 内部 ==========

    async def _load_spec(self) -> dict[str, Any]:
        if self._spec_path.startswith(("http://", "https://")):
            try:
                import httpx
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(self._spec_path)
                    resp.raise_for_status()
                    content = resp.text
            except ImportError:
                logger.warning("httpx not installed, cannot fetch remote spec")
                return {}
            except Exception as exc:
                logger.warning("Failed to fetch spec: %s", exc)
                return {}
        else:
            spec_file = Path(self._spec_path)
            if not spec_file.is_file():
                return {}
            content = spec_file.read_text(encoding="utf-8")

        if self._spec_path.endswith((".yaml", ".yml")):
            return yaml.safe_load(content)
        return json.loads(content)

    def _operation_to_tool(self, path: str, method: str, op: dict) -> HavenTool | None:
        op_id = op.get("operationId", "")
        if not op_id:
            op_id = f"{method}_{path}".replace("/", "_").replace("{", "").replace("}", "")

        summary = op.get("summary", "") or op.get("description", "") or f"{method.upper()} {path}"
        desc = op.get("description", summary)
        category = self._infer_category(path, method)

        return _OpenAPIToolWrapper(
            name=op_id,
            description=f"{summary}\n\n{method.upper()} {path}",
            metadata=ToolMetadata(
                provider=f"openapi:{self.info.name}",
                category=category,
                permissions=self._infer_permissions(method),
                requires_confirmation=(method.upper() in ("POST", "PUT", "DELETE", "PATCH")),
                tags=[f"api:{self.info.name}"] + op.get("tags", []),
            ),
            _path=path,
            _method=method.upper(),
            _base_url=self._base_url,
            _headers=self._headers,
        )

    @staticmethod
    def _infer_category(path: str, _method: str) -> ToolCategory:
        p = path.lower()
        if any(k in p for k in ("search", "query", "find", "lookup")):
            return ToolCategory.SEARCH
        if any(k in p for k in ("file", "upload", "download")):
            return ToolCategory.FILE
        if any(k in p for k in ("email", "mail", "notify")):
            return ToolCategory.COMMUNICATION
        return ToolCategory.CUSTOM

    @staticmethod
    def _infer_permissions(method: str) -> list[ToolPermission]:
        m = method.upper()
        if m == "GET":
            return [ToolPermission.READ]
        if m in ("POST", "PUT", "PATCH"):
            return [ToolPermission.READ, ToolPermission.WRITE]
        if m == "DELETE":
            return [ToolPermission.WRITE]
        return [ToolPermission.READ]


class _OpenAPIToolWrapper(HavenTool):
    """OpenAPI 端点工具包装器。运行时发出 HTTP 请求。"""

    def __init__(
        self, _path: str, _method: str, _base_url: str,
        _headers: dict[str, str], **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self._path = _path
        self._method = _method
        self._base_url = _base_url
        self._headers = _headers

    async def _arun(self, **kwargs: Any) -> str:
        try:
            import httpx
        except ImportError:
            return "Error: httpx not installed"

        url = urljoin(self._base_url, self._path)

        params: dict[str, Any] = {}
        json_body: dict[str, Any] | None = None
        for k, v in list(kwargs.items()):
            if "{" + k + "}" in url:
                url = url.replace("{" + k + "}", str(v))
            else:
                params[k] = v

        if self._method in ("POST", "PUT", "PATCH"):
            json_body = params
            params = {}

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.request(
                    method=self._method, url=url,
                    params=params or None, json=json_body,
                    headers=self._headers,
                )
                resp.raise_for_status()
                return resp.text[:4000]
        except Exception as exc:
            return f"API Error ({self._method} {url}): {exc}"

    def _run(self, **kwargs: Any) -> str:
        import asyncio
        return asyncio.run(self._arun(**kwargs))
