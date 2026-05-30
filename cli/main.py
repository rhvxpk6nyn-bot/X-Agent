"""X-Agent CLI — Claude Code interface replica."""

import re
import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape as rich_escape
from rich.prompt import Prompt
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text
from rich.panel import Panel

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.orchestrator import Orchestrator, StreamEvent
from core.config import config, KEY_PROMPTS
from core.memory import store as memory_store
from core.tools import tools as tool_registry

app = typer.Typer(name="x-agent")
console = Console(force_terminal=True, color_system="truecolor")

# Claude Code exact colors
AMBER = "#d4a574"      # ⏣ prompt, ⏺ tool icon, ⏳ thinking
DIM = "#8b8b90"        # secondary text, ⎿ prefix
WHITE = "#e4e4e7"      # primary text
GREEN = "#7eb77f"      # success
RED = "#e0556a"        # error

TOOL_LINE_RE = re.compile(r"^TOOL:\s*")

# Pre-compiled patterns for _clean_text (performance — avoid re-compiling on every chunk)
_CLEAN_XML_BLOCK_RE = re.compile(r"<tool>.*?</tool>", re.IGNORECASE | re.DOTALL)
_CLEAN_XML_TAG_RE = re.compile(r"</?tool>\s*\w*\s*>?\s*", re.IGNORECASE)
_CLEAN_TOOL_INLINE_RE = re.compile(r'TOOL:\s*\w+\s*\{[^\n]*\}\s*', re.IGNORECASE)


# ── API key setup ──────────────────────────────────────

def _setup_api_keys():
    if not sys.stdin.isatty():
        return
    missing = config.missing_keys()
    if not missing:
        return
    console.print()
    console.print(Panel.fit(
        "Some API keys are missing.\nEnter them now or press Enter to skip.",
        title="X-Agent Setup",
        border_style=AMBER,
    ))
    for name in missing:
        label, url = KEY_PROMPTS.get(name, (name, ""))
        console.print(f"  {label}")
        if url:
            console.print(f"  [{DIM}]Get one at: {url}[/{DIM}]")
        key = Prompt.ask(f"  Key")
        if key.strip():
            config.set_key(name, key.strip())
            console.print(f"  [{GREEN}]Saved[/{GREEN}]")
        else:
            console.print(f"  [{DIM}]Skipped[/{DIM}]")
        console.print()


@app.callback(invoke_without_command=True)
def _global_callback():
    _setup_api_keys()


# ── Helpers ────────────────────────────────────────────

def _clean_text(text: str) -> str:
    text = _CLEAN_XML_BLOCK_RE.sub("", text)
    text = _CLEAN_XML_TAG_RE.sub("", text)
    text = _CLEAN_TOOL_INLINE_RE.sub("", text)
    return text.strip()


def _read_input(prompt_text: str) -> str:
    line = console.input(prompt_text).rstrip()
    if not line.endswith("\\"):
        return line
    lines = [line[:-1].rstrip()]
    continuation = " " * (len(prompt_text) - 3) + "... "
    while True:
        more = console.input(continuation).rstrip()
        if more.endswith("\\"):
            lines.append(more[:-1].rstrip())
        else:
            lines.append(more)
            break
    return "\n".join(lines)


def _format_tool_args(args: dict) -> str:
    """Compact tool args display like Claude: (pattern="...", path="...")"""
    if not args:
        return ""
    parts = []
    for k, v in args.items():
        val = str(v)
        if len(val) > 50:
            val = val[:47] + "..."
        parts.append(f'{k}="{rich_escape(val)}"')
    return "(" + ", ".join(parts) + ")"


# ── Streaming display engine ───────────────────────────

def _is_system_message(text: str) -> bool:
    """Filter internal system messages from display output."""
    return any(text.lstrip().startswith(p) for p in (
        "\n[thinking detected",
        "\n[stopped:",
        "\n[stream error:",
    ))


def _stream_response(orch: Orchestrator, user_input: str):
    """Streaming display: ⏳ thinking preview → ⏺ tool call → ⎿ result → clean response."""
    events = orch.chat_stream(user_input)

    tool_lines: list[str] = []
    response_chunks: list[str] = []
    spinner = Spinner("dots", text=f"  [{AMBER}]⏳[/{AMBER}] [{DIM}]Thinking...[/{DIM}]", style=DIM)

    def _build_display() -> str:
        parts: list[str] = []

        # Tool calls & results
        parts.extend(tool_lines)

        # Clean response text
        raw = "".join(response_chunks)
        clean = _clean_text(raw)
        if clean.strip():
            parts.append(rich_escape(clean.strip()))

        return "\n".join(parts)

    with Live(spinner, console=console, refresh_per_second=30, transient=False) as live:
        for event in events:
            if event.kind == "thinking":
                pass  # Hide thinking — just keep spinner

            elif event.kind == "chunk":
                if not _is_system_message(event.data):
                    response_chunks.append(event.data)
                live.update(_build_display() or spinner)

            elif event.kind == "tool_call":
                data = event.data
                name = data["name"]
                args = data["args"]
                args_str = _format_tool_args(args)
                tool_lines.append(f"  [{AMBER}]⏺[/{AMBER}] [{DIM}]{name}[/{DIM}] {args_str}")
                live.update(_build_display() or spinner)

            elif event.kind == "tool_result":
                data = event.data
                ok = data["exit_code"] == 0
                mark, color = ("✓", GREEN) if ok else ("✗", RED)
                output = data["output"].strip()
                first_line = output.split("\n")[0] if output else "(no output)"
                if len(first_line) > 110:
                    first_line = first_line[:107] + "..."
                tool_lines.append(
                    f"  [{DIM}]⎿[/{DIM}] [{color}]{mark}[/{color}] [{DIM}]{rich_escape(first_line)}  "
                    f"({data['duration_ms']:.0f}ms)[/{DIM}]"
                )
                live.update(_build_display() or spinner)

            elif event.kind == "done":
                final = _build_display()
                live.update(final if final else spinner)

    return len([l for l in tool_lines if "⎿" in l])


# ── One-shot mode ────────────────────────────────────

@app.command()
def ask(
    prompt: str = typer.Argument(..., help="What to ask the agent"),
    model: str = typer.Option("deepseek", "--model", "-m", help="Model to use"),
):
    orch = Orchestrator(model=model)
    start = time.time()

    n_tools = _stream_response(orch, prompt)

    elapsed = time.time() - start
    console.print(f"  [{DIM}]⌂[/{DIM}] [{DIM}]{n_tools} tools · {elapsed:.1f}s[/{DIM}]")


# ── REPL mode ─────────────────────────────────────────

@app.command()
def repl(
    model: str = typer.Option("deepseek", "--model", "-m", help="Default model"),
):
    orch = Orchestrator(model=model)

    # Startup banner
    console.print()
    console.print(f"  [{AMBER}]╭─ X-Agent ──────────────────────────╮[/{AMBER}]")
    console.print(f"  [{AMBER}]│[/{AMBER}] [{WHITE}]{orch.model}[/{WHITE}] · {len(tool_registry._tools)} tools · /help       [{AMBER}]│[/{AMBER}]")
    console.print(f"  [{AMBER}]╰────────────────────────────────────╯[/{AMBER}]")
    turn = 0

    while True:
        prompt_main = f"\n  [{AMBER}]⏣[/{AMBER}] "

        try:
            user_input = _read_input(prompt_main).strip()
        except (KeyboardInterrupt, EOFError):
            console.print(f"\n  [{DIM}]⏣ exit[/{DIM}]")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            _handle_slash(user_input, orch, model)
            continue

        turn += 1

        # Stream with full Claude Code display
        start = time.time()
        n_tools = _stream_response(orch, user_input)
        elapsed = time.time() - start

        # Token-style summary line
        if n_tools:
            console.print(f"  [{DIM}]⌂[/{DIM}] [{DIM}]{n_tools} tools · {elapsed:.1f}s[/{DIM}]")
        console.print()


# ── Slash commands ─────────────────────────────────────

def _handle_slash(cmd: str, orch: Orchestrator, current_model: str):
    parts = cmd.split(maxsplit=1)
    action = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if action in ("/exit", "/quit"):
        console.print(f"  [{DIM}]⏣ exit[/{DIM}]")
        sys.exit(0)
    elif action == "/help":
        console.print(f"""
  [{AMBER}]Commands[/{AMBER}]
    /model <name>    Switch model (deepseek, qwen-vl, ollama)
    /explore         Browse latest ClawHub skills
    /search <query>  Search ClawHub for skills
    /install <slug>  Install a skill from ClawHub
    /uninstall <name>  Remove an installed skill
    /skills          List installed skills
    /memory          Show recent memories
    /clear           Clear conversation
    /stats           Session stats
    /help            This help
    /exit            Quit

  [{AMBER}]X-Agent[/{AMBER}] [{DIM}]— AI Agent Framework · {len(tool_registry._tools)} tools[/{DIM}]

  [{AMBER}]Tips[/{AMBER}]
    End a line with \\\\ for multiline input
    Ctrl+C to interrupt  ·  Ctrl+D to exit
""")
    elif action == "/model":
        orch.model = arg or current_model
        console.print(f"  [{AMBER}]⏣[/{AMBER}] [{DIM}]model →[/{DIM}] {orch.model}")
    elif action == "/memory":
        _show_memory()
    elif action == "/explore":
        _explore_skills()
    elif action == "/skills":
        _show_skills()
    elif action == "/search":
        _search_skills(arg)
    elif action == "/install":
        _install_skill(arg)
    elif action == "/uninstall":
        _uninstall_skill(arg)
    elif action == "/clear":
        orch.reset()
        console.print(f"  [{DIM}]⏣ conversation cleared[/{DIM}]")
    elif action == "/stats":
        stats = orch.stats()
        console.print()
        for k, v in stats.items():
            console.print(f"  [{DIM}]{k}[/{DIM}]  {v}")
        console.print()
    else:
        console.print(f"  [{RED}]Unknown: {action}[/{RED}]  [{DIM}]type /help[/{DIM}]")


def _explore_skills():
    """Browse latest ClawHub skills."""
    with console.status(f"  [{DIM}]Fetching ClawHub...[/{DIM}]", spinner="dots"):
        import subprocess, re as _re
        try:
            r = subprocess.run(["clawhub", "explore"], capture_output=True, text=True, timeout=30)
            output = r.stdout.strip()
        except Exception as e:
            console.print(f"  [{RED}]Failed: {e}[/{RED}]")
            return
    if not output:
        console.print(f"  [{DIM}]No results[/{DIM}]")
        return
    # Strip ANSI and control characters
    output = _re.sub(r'\x1b\[[0-9;]*m', '', output)
    output = _re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', output)
    console.print(f"\n  [{AMBER}]ClawHub — Latest Skills[/{AMBER}]")
    for line in output.split("\n")[:25]:
        stripped = line.strip()
        if not stripped or stripped.startswith("- "):
            continue
        # Parse: slug  version  time  description
        console.print(f"  [{GREEN}]✦[/{GREEN}] [{DIM}]{stripped[:120]}[/{DIM}]")
    console.print(f"\n  [{DIM}]Install: /install <slug>  |  Search: /search <query>[/{DIM}]")

def _show_memory():
    hot = memory_store.get_hot()
    if hot:
        console.print(f"\n  [{AMBER}]Memories ({len(hot)})[/{AMBER}]")
        for m in hot:
            console.print(f"  [{DIM}]•[/{DIM}] {m.title} [{DIM}]({m.type})[/{DIM}]")
    else:
        console.print(f"  [{DIM}]No memories yet[/{DIM}]")


def _show_skills():
    from core.skills import skills as skill_registry
    if skill_registry.skills:
        console.print(f"\n  [{AMBER}]Skills[/{AMBER}]")
        for name, skill in skill_registry.skills.items():
            console.print(f"  [{DIM}]•[/{DIM}] {name} [{DIM}]v{skill.version}[/{DIM}]")
            console.print(f"    {skill.description[:80]}")
    else:
        console.print(f"  [{DIM}]No skills installed. Try /search <query>[/{DIM}]")


def _search_skills(query: str):
    if not query.strip():
        console.print(f"  [{RED}]Usage: /search <query>[/{RED}]")
        return
    from core.skills import skills as skill_registry
    with console.status(f"  [{DIM}]Searching ClawHub...[/{DIM}]", spinner="dots"):
        results = skill_registry.search(query)
    if not results:
        console.print(f"  [{DIM}]No skills found[/{DIM}]")
        return
    console.print(f"\n  [{AMBER}]ClawHub: {query}[/{AMBER}]")
    for r in results[:10]:
        score = f" [{DIM}]({r['score']})[/{DIM}]" if r.get("score") else ""
        console.print(f"  [{GREEN}]✦[/{GREEN}] [bold]{r['slug']}[/bold] — {r['name']}{score}")
    console.print(f"\n  [{DIM}]To install: /install <slug>[/{DIM}]")


def _install_skill(slug: str):
    if not slug.strip():
        console.print(f"  [{RED}]Usage: /install <slug>[/{RED}]")
        return
    from core.skills import skills as skill_registry
    with console.status(f"  [{DIM}]Installing {slug}...[/{DIM}]", spinner="dots"):
        ok, msg = skill_registry.install(slug)
    if ok:
        console.print(f"  [{GREEN}]✓ Installed {slug}[/{GREEN}]")
    else:
        console.print(f"  [{RED}]Failed: {msg[:300]}[/{RED}]")


def _uninstall_skill(name: str):
    if not name.strip():
        console.print(f"  [{RED}]Usage: /uninstall <name>[/{RED}]")
        return
    from core.skills import skills as skill_registry
    if skill_registry.uninstall(name):
        console.print(f"  [{GREEN}]✓ Removed {name}[/{GREEN}]")
    else:
        console.print(f"  [{RED}]Skill '{name}' not found[/{RED}]")


# ── Other modes ────────────────────────────────────────

@app.command()
def tui(
    model: str = typer.Option("deepseek", "--model", "-m"),
):
    from tui.app import AgentTUI
    import os
    os.environ["AGENT_MODEL"] = model
    AgentTUI().run()


def main():
    if len(sys.argv) == 1:
        _setup_api_keys()
        repl(model="deepseek")
    else:
        app()


if __name__ == "__main__":
    main()
