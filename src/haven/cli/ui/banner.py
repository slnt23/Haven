"""Haven V2 启动横幅。"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

HAVEN_ASCII = r"""[bold cyan]
          _   _
         | | | | __ ___   _____ _ __
         | |_| |/ _` \ \ / / _ \ '_ \
         |  _  | (_| |\ V /  __/ | | |
         |_| |_|\__,_| \_/ \___|_| |_|
[/]"""


def print_banner(
    *,
    model: str = "—",
    skills: int = 0,
    tools: int = 0,
    workflows: int = 0,
    memory_turns: int = 0,
    providers: int = 0,
    vector_available: bool = False,
    version: str = "2.0.0",
    channel: str = "cli",
) -> None:
    console = Console(highlight=False)

    left = Text.from_markup(HAVEN_ASCII)
    right = Text()
    right.append(f"\n  Version:  [bold cyan]{version}[/]")
    right.append(f"\n  Model:    [green]{model}[/]")
    right.append(f"\n  Skills:   [cyan]{skills}[/]")
    right.append(f"\n  Tools:    [cyan]{tools}[/]")
    right.append(f"\n  Providers:[cyan]{providers}[/]")
    right.append(f"\n  Workflows:[cyan]{workflows}[/]")
    vec_status = "[green]on[/]" if vector_available else "[dim]off[/]"
    right.append(f"\n  Memory:   [cyan]{memory_turns} turns[/]  Vector: {vec_status}")
    right.append(f"\n  Channel:  [dim]{channel}[/]")

    from rich.columns import Columns

    console.print(Panel(Columns([left, right]), border_style="cyan"))
    console.print()
