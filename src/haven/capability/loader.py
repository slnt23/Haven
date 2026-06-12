"""CapabilityLoader —— 统一的能力加载入口。

编排：
  1. Skill 加载：从 .md 文件扫描 → 解析 YAML frontmatter → 注册到 CapabilityRegistry
  2. Tool 加载：启动 BuiltinProvider + MCPProvider → 发现工具 → 注册到 CapabilityRegistry

Provider 生命周期：start → discover → (工具注册) → stop
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from omegaconf import OmegaConf

from haven.capability.models import Skill
from haven.capability.registry import CapabilityRegistry
from haven.capability.resolver import DependencyResolver

logger = logging.getLogger("haven.capability.loader")

# ============================================================================
# Skill 加载
# ============================================================================


class SkillLoader:
    """从 .md 文件加载 Skill。

    每个 .md 文件以 ``---`` 分隔的 YAML frontmatter 开头:

        ---
        name: coder
        description: ...
        tags: [development]
        dependencies: []
        ---

        ## 角色：高级软件工程师...
    """

    @staticmethod
    def load_from_dir(directory: str | Path) -> list[Skill]:
        """扫描目录，加载所有 .md 文件。"""
        directory = Path(directory)
        if not directory.is_dir():
            return []

        skills: list[Skill] = []
        for md_file in sorted(directory.glob("*.md")):
            skill = SkillLoader._parse_file(md_file)
            if skill is not None:
                skills.append(skill)
        return skills

    @staticmethod
    def load_single(filepath: str | Path) -> Skill | None:
        """加载单个 .md 文件。"""
        filepath = Path(filepath)
        if not filepath.is_file():
            return None
        return SkillLoader._parse_file(filepath)

    @staticmethod
    def _parse_file(filepath: Path) -> Skill | None:
        raw = filepath.read_text(encoding="utf-8")
        frontmatter, body = SkillLoader._split_frontmatter(raw)
        if frontmatter is None:
            return None

        import yaml

        try:
            meta = yaml.safe_load(frontmatter)
        except yaml.YAMLError:
            return None

        if not isinstance(meta, dict):
            return None

        return Skill(
            name=str(meta.get("name", filepath.stem)),
            description=str(meta.get("description", "")),
            prompt=body.strip(),
            tags=_ensure_str_list(meta.get("tags", [])),
            tools=_ensure_str_list(meta.get("tools", [])),
            dependencies=_ensure_str_list(meta.get("dependencies", [])),
            version=str(meta.get("version", "1.0")),
            source_file=filepath,
            default=bool(meta.get("default", False)),
        )

    @staticmethod
    def _split_frontmatter(raw: str) -> tuple[str | None, str]:
        """返回 (frontmatter, body)，无 frontmatter 时返回 (None, raw)。"""
        raw = raw.lstrip()
        if not raw.startswith("---"):
            return None, raw
        end = raw.find("---", 3)
        if end == -1:
            return None, raw
        frontmatter = raw[3:end].strip()
        body = raw[end + 3:].strip()
        return frontmatter, body


def _ensure_str_list(value: list) -> list[str]:
    return [str(v) for v in (value or [])]


# ============================================================================
# 系统 Skill
# ============================================================================

_SYSTEM_PERSONA_PATH = Path(__file__).resolve().parent.parent / "config" / "haven.md"


# ============================================================================
# CapabilityLoader
# ============================================================================


class CapabilityLoader:
    """统一的能力加载器。

    加载流程：
      1. 加载系统人格 Skill（haven.md）
      2. 加载用户领域 Skill（skills/ 目录）
      3. 启动 ToolProvider（Builtin + MCP）
      4. 全部注册到 CapabilityRegistry

    Usage::

        registry = CapabilityRegistry()
        loader = CapabilityLoader(registry)
        await loader.load_all()
    """

    def __init__(self, registry: CapabilityRegistry) -> None:
        self.registry = registry
        self._tool_providers: dict[str, Any] = {}
        self._started = False

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    async def load_all(
        self,
        *,
        skill_dir: str = "skills",
        load_mcp: bool = True,
        mcp_enabled: bool = True,
    ) -> CapabilityRegistry:
        """加载全部能力和工具，返回已填充的注册表。

        幂等：重复调用不重新加载。
        """
        if self._started:
            return self.registry

        # 1. 系统人格 Skill
        self._load_system_persona()

        # 2. 用户领域 Skills
        self._load_user_skills(skill_dir)

        # 3. 内置工具
        await self._load_builtin_tools()

        # 4. MCP 工具
        if load_mcp and mcp_enabled:
            await self._load_mcp_tools()

        self._started = True
        logger.info(
            "CapabilityLoader: %d skills, %d tools loaded",
            self.registry.skill_count,
            self.registry.tool_count,
        )
        return self.registry

    async def stop_all(self) -> None:
        """停止所有 ToolProvider，释放连接。"""
        import asyncio

        await asyncio.gather(
            *(p.stop() for p in self._tool_providers.values()),
            return_exceptions=True,
        )
        self._tool_providers.clear()
        self._started = False

    # ------------------------------------------------------------------
    # 内部：Skill
    # ------------------------------------------------------------------

    def _load_system_persona(self) -> None:
        if _SYSTEM_PERSONA_PATH.is_file():
            skill = SkillLoader.load_single(_SYSTEM_PERSONA_PATH)
            if skill is not None:
                self.registry.register(skill)

    def _load_user_skills(self, skill_dir: str) -> None:
        from haven.config import settings

        user_dir = Path.cwd() / skill_dir
        if not user_dir.is_dir():
            return
        for skill in SkillLoader.load_from_dir(user_dir):
            self.registry.register(skill)

    # ------------------------------------------------------------------
    # 内部：Tool
    # ------------------------------------------------------------------

    async def _load_builtin_tools(self) -> None:
        from haven.capability.tools.providers.builtin import BuiltinProvider

        provider = BuiltinProvider()
        await self._start_provider(provider)

    async def _load_mcp_tools(self) -> None:
        from haven.capability.tools.providers.mcp import MCPProvider
        from haven.config.mcp import MCPServerConfig
        from haven.config import get_mcp_config

        raw_configs = get_mcp_config()
        for entry in raw_configs:
            try:
                cfg = MCPServerConfig(**entry)
                if cfg.enabled:
                    provider = MCPProvider(cfg)
                    await self._start_provider(provider)
            except Exception:
                logger.debug("Skip MCP server config: %s", entry.get("name", entry), exc_info=True)

    async def _start_provider(self, provider: Any) -> None:
        """启动单个 Provider 并注册其工具到 registry。"""
        try:
            await provider.start()
            self._tool_providers[provider.info.name] = provider
            for base_tool in provider.list_tools():
                from haven.capability.models import Tool

                cap_tool = Tool(base_tool, provider=provider.info.name)
                self.registry.register(cap_tool)
        except Exception:
            logger.warning("Provider '%s' failed to start", provider.info.name, exc_info=True)


# ============================================================================
# 便捷函数（兼容旧代码）
# ============================================================================


def load_skills_to_registry(
    registry: CapabilityRegistry,
    *,
    skill_dir: str = "skills",
) -> None:
    """加载系统人格 + 用户 Skill 到指定注册表。"""
    loader = CapabilityLoader(registry)
    loader._load_system_persona()
    loader._load_user_skills(skill_dir)
