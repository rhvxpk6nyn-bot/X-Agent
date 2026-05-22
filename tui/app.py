"""X-Agent Terminal UI — Textual-powered TUI."""

import os
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import (
    Header, Footer, Input, TextLog, ListView, ListItem, Label,
    Static, RichLog,
)
from textual.widget import Widget
from textual.screen import Screen
from textual.reactive import reactive

from core.orchestrator import Orchestrator
from core.config import config


class Sidebar(Widget):
    """Left navigation sidebar."""
    def compose(self) -> ComposeResult:
        yield Static("✖ X-Agent", classes="logo")
        yield Static("[dim]Menu[/dim]", classes="section")
        yield ListView(
            ListItem(Label("  Chat")),
            ListItem(Label("  Memory")),
            ListItem(Label("  Skills")),
            ListItem(Label("  Config")),
        )


class ChatView(Widget):
    """Main chat area."""
    def compose(self) -> ComposeResult:
        yield RichLog(highlight=True, markup=True, wrap=True, id="chat-log")
        yield Input(placeholder="Message X-Agent... (/help for commands)", id="chat-input")


class StatusBar(Widget):
    """Bottom status bar."""
    model = reactive("deepseek")
    tools_active = reactive(0)

    def compose(self) -> ComposeResult:
        yield Static(f"● {self.model}  ·  0 tools", id="status-text")

    def watch_model(self, value: str):
        self.query_one("#status-text", Static).update(
            f"● {value}  ·  {self.tools_active} tools"
        )


class AgentTUI(App):
    """X-Agent TUI."""

    CSS = """
    Sidebar {
        width: 22;
        background: #0f0f12;
        border-right: solid #1c1c22;
        padding: 1 2;
    }
    Sidebar .logo {
        color: #60a5fa;
        bold: true;
        padding: 1 0;
    }
    Sidebar .section {
        color: #5b5b66;
        text-style: bold;
        padding: 1 0 0 0;
    }
    ListView {
        background: #0f0f12;
    }
    ListView > ListItem {
        color: #8b8b90;
        background: #0f0f12;
        padding: 1;
    }
    ListView > ListItem.--highlight {
        background: #1c1c22;
        color: #93c5fd;
    }
    ChatView {
        background: #0a0a0d;
    }
    #chat-log {
        height: 1fr;
        background: #0a0a0d;
    }
    #chat-input {
        dock: bottom;
        background: #141418;
        border: solid #22222a;
        color: #e4e4e7;
        padding: 1 2;
    }
    #chat-input:focus {
        border: solid #60a5fa;
    }
    StatusBar {
        dock: bottom;
        height: 1;
        background: #0f0f12;
        color: #5b5b66;
        padding: 0 2;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+l", "clear", "Clear"),
    ]

    def __init__(self):
        super().__init__()
        self.orch = Orchestrator(model=os.environ.get("AGENT_MODEL", "deepseek"))

    def compose(self) -> ComposeResult:
        yield Header()
        yield Horizontal(
            Sidebar(),
            ChatView(),
        )
        yield StatusBar()

    def on_mount(self):
        chat_log = self.query_one("#chat-log", RichLog)
        model = os.environ.get("AGENT_MODEL", "deepseek")
        chat_log.write(f"[bold #60a5fa]✖ X-Agent[/bold #60a5fa] [dim]· {model} · ready[/dim]\n")

    def on_input_submitted(self, event: Input.Submitted):
        user_input = event.value.strip()
        if not user_input:
            return

        chat_log = self.query_one("#chat-log", RichLog)
        chat_log.write(f"\n[bold #93c5fd]▸[/bold #93c5fd] {user_input}")

        if user_input.startswith("/"):
            self._handle_command(user_input, chat_log)
        else:
            response = self.orch.chat(user_input)
            chat_log.write(f"\n{response}\n")

        event.input.value = ""

    def _handle_command(self, cmd: str, chat_log: RichLog):
        parts = cmd.split(maxsplit=1)
        action = parts[0].lower()
        if action == "/clear":
            chat_log.clear()
        elif action == "/exit":
            self.exit()
        elif action == "/model":
            arg = parts[1] if len(parts) > 1 else ""
            if arg:
                self.orch.model = arg
                chat_log.write(f"[dim]Model → {arg}[/dim]")
        else:
            chat_log.write(f"[red]Unknown: {action}[/red]")

    def action_clear(self):
        self.query_one("#chat-log", RichLog).clear()
