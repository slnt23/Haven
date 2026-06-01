"""ToolResolver — 动态工具解析层。

在 Skill 与 ToolManager 之间，根据 Skill 声明 + Context + RuntimeState
动态解析可用工具集。

架构：
    Skill (tools: [code_exec, file_ops, web_search])
        │
        ▼
    ToolResolver.resolve(skill_names, context, state)
        │  1. 读取 Skill.tools 声明
        │  2. 名称 → 标签 → 类别 → 能力关键词 多级匹配
        │  3. 上下文过滤（channel / permissions / availability）
        │  4. MCP 命名空间工具支持（provider__tool_name）
        │
        ▼
    ResolveResult(tools=[...], unresolved=[...], warnings=[...])
        │
        ▼
    ToolManager (Provider → Builtin / MCP)

用法::

    tm = ToolManager()
    await tm.start_all()

    resolver = ToolResolver(tm)
    result = resolver.resolve(
        ["coder", "medical"],
        channel="cli",
        permissions=["read", "write"],
    )
    tools = result.tools
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

from haven.tools.base import HavenTool, ToolCategory

logger = logging.getLogger("haven.tools.resolver")


# ============================================================================
# 能力关键词 → ToolCategory 映射
# ============================================================================

_CAPABILITY_CATEGORY: dict[str, ToolCategory] = {
    # File operations
    "file": ToolCategory.FILE,
    "file_ops": ToolCategory.FILE,
    "file_operations": ToolCategory.FILE,
    "fs": ToolCategory.FILE,
    # Code execution
    "code": ToolCategory.CODE,
    "code_exec": ToolCategory.CODE,
    "exec": ToolCategory.CODE,
    "execute": ToolCategory.CODE,
    "shell": ToolCategory.CODE,
    "run": ToolCategory.CODE,
    # Search
    "search": ToolCategory.SEARCH,
    "web_search": ToolCategory.SEARCH,
    "lookup": ToolCategory.SEARCH,
    "find": ToolCategory.SEARCH,
    "query": ToolCategory.SEARCH,
    # Knowledge / RAG
    "knowledge": ToolCategory.KNOWLEDGE,
    "rag": ToolCategory.KNOWLEDGE,
    "rag_search": ToolCategory.KNOWLEDGE,
    "retrieval": ToolCategory.KNOWLEDGE,
    "embedding": ToolCategory.KNOWLEDGE,
    # Communication
    "email": ToolCategory.COMMUNICATION,
    "send": ToolCategory.COMMUNICATION,
    "notify": ToolCategory.COMMUNICATION,
    "message": ToolCategory.COMMUNICATION,
    # Medical (maps to KNOWLEDGE since medical_kb is knowledge-category)
    "medical": ToolCategory.KNOWLEDGE,
    "medical_kb": ToolCategory.KNOWLEDGE,
    "health": ToolCategory.KNOWLEDGE,
    # System
    "system": ToolCategory.SYSTEM,
    "sys": ToolCategory.SYSTEM,
}

# ============================================================================
# Data classes
# ============================================================================


@dataclass
class ToolRequirement:
    """单个工具需求，从 Skill.tools 解析而来。"""

    raw: str  # skill 中声明的原始字符串
    skill_name: str = ""  # 来源 skill
    matched: bool = False  # 是否已匹配
    resolved_to: str = ""  # 匹配到的具体工具名


@dataclass
class ResolveResult:
    """ToolResolver.resolve() 的返回结果。"""

    tools: list[HavenTool] = field(default_factory=list)
    """解析到的工具实例列表（可直接 bind 到 LLM）。"""

    unresolved: list[ToolRequirement] = field(default_factory=list)
    """未能解析的需求列表。"""

    warnings: list[str] = field(default_factory=list)
    """解析过程中的警告信息。"""

    source_map: dict[str, str] = field(default_factory=dict)
    """{tool_name: provider_name} 来源映射。"""

    @property
    def all_resolved(self) -> bool:
        return len(self.unresolved) == 0

    @property
    def tool_names(self) -> list[str]:
        return [t.name for t in self.tools]


# ============================================================================
# ToolResolver
# ============================================================================


class ToolResolver:
    """动态工具解析器。

    位于 Skill → ToolManager 之间。根据 Skill 声明的工具需求、
    上下文和运行时状态，动态解析可用工具列表。

    解析优先级（从高到低）：
      1. 精确名称匹配 — ``code_exec`` 在 ToolManager 中直接命中
      2. MCP 命名空间匹配 — ``github__search_code`` 按前缀匹配
      3. 标签匹配 — 任何 tool.metadata.tags 包含该名称
      4. 类别匹配 — 能力关键词 → ToolCategory 映射
      5. 失败了——记入 unresolved

    上下文过滤（resolve 后自动应用）：
      - channel 限制（某些工具仅在特定通道可用）
      - permissions 限制（仅返回权限匹配的工具）
      - provider 可用性（仅 CONNECTED 的 provider）
    """

    def __init__(self, tool_manager: Any):
        self._tm = tool_manager
        self._cache: dict[str, ResolveResult] = {}
        self._name_index: dict[str, HavenTool] = {}
        self._tag_index: dict[str, list[HavenTool]] = {}
        self._category_index: dict[str, list[HavenTool]] = {}
        self._index_built = False

    # ==================================================================
    # 公开 API
    # ==================================================================

    def resolve(
        self,
        skill_names: list[str],
        *,
        context: dict[str, str] | None = None,
        channel: str = "cli",
        permissions: list[str] | None = None,
        only_available: bool = True,
        use_cache: bool = True,
    ) -> ResolveResult:
        """根据 skill 列表 + 上下文解析可用工具。

        Args:
            skill_names: skill 名列表（如 ``["coder", "medical"]``）。
            context: 运行时上下文（如 RuntimeState.context）。
            channel: 当前通道（cli / socket / feishu / email）。
            permissions: 授予的权限列表（如 ``["read", "write"]``）。
            only_available: 仅返回 provider 已连接的工具。
            use_cache: 是否使用缓存（相同 skill 组合复用结果）。

        Returns:
            ResolveResult — 包含已解析工具、未解析需求、警告。
        """
        # 构建索引
        if not self._index_built:
            self._build_index()

        # 缓存
        cache_key = _make_cache_key(skill_names, channel, permissions or [])
        if use_cache and cache_key in self._cache:
            return self._cache[cache_key]

        # 收集 Skill 工具需求 → 解析
        requirements = self._collect_requirements(skill_names)
        result = self._match_all(requirements)

        # 上下文过滤
        result.tools = self._apply_filters(
            result.tools,
            channel=channel,
            permissions=permissions,
            only_available=only_available,
            context=context,
        )

        # 构建 source_map
        for tool in result.tools:
            provider = getattr(tool.metadata, "provider", "unknown")
            result.source_map[tool.name] = provider

        if use_cache:
            self._cache[cache_key] = result
            if len(self._cache) > 64:
                first = next(iter(self._cache))
                del self._cache[first]

        if result.unresolved:
            names = [r.raw for r in result.unresolved]
            logger.debug("Unresolved tool requirements: %s", names)

        return result

    def invalidate_cache(self) -> None:
        """清空解析缓存（provider 变更后调用）。"""
        self._cache.clear()
        self._index_built = False

    # ==================================================================
    # 索引
    # ==================================================================

    def _build_index(self) -> None:
        """为 ToolManager 中所有工具建立多维索引。"""
        self._name_index.clear()
        self._tag_index.clear()
        self._category_index.clear()

        for tool in self._tm.list_all():
            # 名称索引
            self._name_index[tool.name] = tool

            # 标签索引
            for tag in getattr(tool.metadata, "tags", []):
                self._tag_index.setdefault(tag, []).append(tool)

            # 类别索引
            cat = getattr(tool.metadata, "category", None)
            if cat:
                cat_val = cat.value if hasattr(cat, "value") else str(cat)
                self._category_index.setdefault(cat_val, []).append(tool)

        self._index_built = True
        logger.debug(
            "ToolResolver index: %d names, %d tags, %d categories",
            len(self._name_index),
            len(self._tag_index),
            len(self._category_index),
        )

    # ==================================================================
    # 需求收集
    # ==================================================================

    @staticmethod
    def _collect_requirements(skill_names: list[str]) -> list[ToolRequirement]:
        """从 SkillRegistry 读取所有 skill 的工具需求。"""
        from haven.skills.registry import SkillRegistry

        seen: set[str] = set()
        requirements: list[ToolRequirement] = []

        for sn in skill_names:
            try:
                skill = SkillRegistry.get(sn)
            except KeyError:
                continue
            for tool_name in getattr(skill, "tools", []):
                if tool_name and tool_name not in seen:
                    seen.add(tool_name)
                    requirements.append(
                        ToolRequirement(
                            raw=tool_name,
                            skill_name=sn,
                        )
                    )

        return requirements

    # ==================================================================
    # 匹配引擎
    # ==================================================================

    def _match_all(self, requirements: list[ToolRequirement]) -> ResolveResult:
        tools: dict[str, HavenTool] = {}
        unresolved: list[ToolRequirement] = []
        warnings: list[str] = []

        for req in requirements:
            matched = self._match_one(req.raw)
            if matched:
                if matched.name not in tools:
                    tools[matched.name] = matched
                req.matched = True
                req.resolved_to = matched.name
            else:
                unresolved.append(req)
                warnings.append(
                    f"Skill '{req.skill_name}' 需要工具 '{req.raw}'，但未在任何 provider 中找到"
                )

        return ResolveResult(
            tools=list(tools.values()),
            unresolved=unresolved,
            warnings=warnings,
        )

    def _match_one(self, requirement: str) -> HavenTool | None:
        """对单个工具需求执行多级匹配。

        匹配顺序: exact name → MCP prefix → tag → category → capability
        """
        # Level 1: 精确名称匹配
        tool = self._name_index.get(requirement)
        if tool:
            return tool

        # Level 2: MCP 命名空间匹配（provider__tool_name）
        if "__" in requirement:
            tool = self._name_index.get(requirement)
            if tool:
                return tool

        # Level 3: 标签匹配（tool.metadata.tags 包含该字符串）
        candidates = self._tag_index.get(requirement)
        if candidates:
            return self._pick_best(candidates, requirement)

        # Level 4: 类别匹配（requirement 是 ToolCategory 值）
        if requirement in self._category_index:
            return self._pick_best(self._category_index[requirement], requirement)

        # Level 5: 能力关键词 → 类别映射
        category = _CAPABILITY_CATEGORY.get(requirement)
        if category:
            cat_val = category.value
            candidates = self._category_index.get(cat_val)
            if candidates:
                return self._pick_best(candidates, requirement)

        return None

    @staticmethod
    def _pick_best(candidates: list[HavenTool], requirement: str) -> HavenTool | None:
        """从候选中选最佳工具。优先内置 > 优先名称最接近 > 第一个。

        heuristic:
          1. 内置 provider（builtin）优先于 MCP
          2. 名称包含 requirement 的优先
        """
        if not candidates:
            return None

        # 内置优先
        builtins = [t for t in candidates if getattr(t.metadata, "provider", "") == "builtin"]
        target = builtins if builtins else candidates

        # 名称匹配度
        exact = [t for t in target if t.name == requirement]
        if exact:
            return exact[0]

        return target[0]

    # ==================================================================
    # 上下文过滤
    # ==================================================================

    def _apply_filters(
        self,
        tools: list[HavenTool],
        *,
        channel: str,
        permissions: list[str] | None,
        only_available: bool,
        context: dict[str, str] | None,
    ) -> list[HavenTool]:
        """对已解析的工具列表应用上下文过滤。"""
        result: list[HavenTool] = []

        for tool in tools:
            # 可用性过滤
            if only_available and not self._is_available(tool):
                continue

            # 权限过滤
            if permissions and not self._has_permission(tool, permissions):
                continue

            # Channel 过滤（工具 metadata.tags 中若有 channel:xxx 标签则限制通道）
            tags = getattr(tool.metadata, "tags", [])
            channel_tags = [t for t in tags if t.startswith("channel:")]
            if channel_tags:
                allowed_channels = {t.split(":", 1)[1] for t in channel_tags}
                if channel not in allowed_channels:
                    continue

            result.append(tool)

        return result

    def _is_available(self, tool: HavenTool) -> bool:
        """检查工具的 provider 是否已连接。"""
        provider_name = getattr(tool.metadata, "provider", "")
        if not provider_name:
            return True

        # builtin 始终可用
        if provider_name == "builtin":
            return True

        # MCP provider: 检查是否 CONNECTED
        actual_name = (
            provider_name.replace("mcp:", "", 1)
            if provider_name.startswith("mcp:")
            else provider_name
        )
        provider = self._tm.get_provider(actual_name)
        if provider is None:
            return False

        from haven.tools.providers.base import ProviderStatus

        return provider.info.status == ProviderStatus.CONNECTED

    @staticmethod
    def _has_permission(tool: HavenTool, granted: list[str]) -> bool:
        """检查工具需要的权限是否被授予。"""
        required = getattr(tool.metadata, "permissions", [])
        if not required:
            return True

        required_vals = {p.value if hasattr(p, "value") else str(p) for p in required}
        granted_set = set(granted)

        # EXECUTE 需要 write 权限
        if "execute" in required_vals and "write" not in granted_set:
            return False
        # WRITE 需要 write 权限
        if "write" in required_vals and "write" not in granted_set:
            return False

        return True


# ============================================================================
# helpers
# ============================================================================


def _make_cache_key(skill_names: list[str], channel: str, permissions: list[str]) -> str:
    parts = sorted(skill_names)
    parts.append(f"ch:{channel}")
    parts.extend(f"p:{p}" for p in sorted(permissions))
    return "|".join(parts)
