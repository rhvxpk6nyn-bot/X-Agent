"""X-Agent orchestrator — multi-turn tool loop, context assembly."""

import json
import re
import time
from dataclasses import dataclass, field
from typing import Iterator, Union

from core.config import config
from core.memory import store as memory_store, Memory
from core.model_router import chat, Message
from core.skills import skills as skill_registry, Skill
from core.tools import tools as tool_registry, ToolResult

MAX_TOOL_TURNS = 5
TOOL_RESULT_MAX_CHARS = 4000


@dataclass
class StreamEvent:
    """Structured event for Claude-style streaming display."""
    kind: str  # "chunk", "tool_call", "tool_result", "done"
    data: str | dict | None = None

    @classmethod
    def chunk(cls, text: str) -> "StreamEvent":
        return cls(kind="chunk", data=text)

    @classmethod
    def tool_call(cls, name: str, args: dict) -> "StreamEvent":
        return cls(kind="tool_call", data={"name": name, "args": args})

    @classmethod
    def tool_result(cls, tool: str, output: str, exit_code: int, duration_ms: float) -> "StreamEvent":
        return cls(kind="tool_result", data={
            "tool": tool, "output": output, "exit_code": exit_code, "duration_ms": duration_ms
        })

    @classmethod
    def done(cls, tokens: dict | None = None) -> "StreamEvent":
        return cls(kind="done", data=tokens or {})

SYSTEM_PROMPT = """You are X-Agent, an AI assistant that executes actions directly — never describe what you would do, actually do it.

## Tool Protocol
To perform ANY action (play music, open app, create file, run code, search, browse, automate GUI), you MUST write a TOOL: line. Text alone does nothing.

### Format (CRITICAL — follow exactly)
Each TOOL: line must be on its own line with NOTHING else:
  TOOL: tool_name {"arg": "value"}

- One TOOL: per line. Multiple actions = multiple TOOL: lines.
- Never put text before or after TOOL: on the same line.
- No code fences (```), no <tool> tags, no markdown around TOOL: lines.
- JSON args must use double quotes: {"key": "value"}

### Examples
  TOOL: shell {"command": "python3 /tmp/game.py"}
  TOOL: write {"path": "/tmp/x.py", "content": "print(1)"}
  TOOL: read {"path": "/tmp/x.py"}
  TOOL: grep {"pattern": "main", "path": "src/"}
  TOOL: music {"action": "play", "song": "Stay"}
  TOOL: mano_cua {"task": "click the search button in Music", "app": "Music"}
  TOOL: browse {"url": "https://example.com"}

### Tools
  shell       {"command": "..."}     — run terminal command
  read        {"path": "...", "offset": 0, "limit": 50}  — read file (with line numbers)
  write       {"path": "...", "content": "..."}   — create/overwrite file
  edit        {"path": "...", "old": "...", "new": "..."} — find & replace first match
  line_edit   {"path": "...", "start": 1, "end": 5, "content": "..."} — replace line range
  grep        {"pattern": "...", "path": "."}   — regex search codebase
  glob        {"pattern": "**/*.py", "path": "."}  — find files by pattern
  web_fetch   {"url": "..."}      — fetch URL text content
  browse      {"url": "..."}      — open URL in default browser
  mano_cua    {"task": "...", "app": "..."}  — GUI desktop automation (macOS)
  sysinfo     {}                 — get full system information
  music       {"action": "play|pause|next|previous|current", "song": "...", "artist": "..."} — Apple Music

### Installing Skills from ClawHub
  TOOL: shell {"command": "clawhub search <keywords>"}
  TOOL: shell {"command": "clawhub install <slug> --dir ~/.agent/skills/installed"}

### Workflow
After each [TOOL RESULT], decide: more tools needed? → write another TOOL: line. Done? → respond in text.
Programming: glob/grep → read → edit/write → shell (test) → fix errors → retry
If a tool fails: read the error, fix the issue, try again."""

TOOL_LINE_RE = re.compile(r"^TOOL:\s*")

# Pre-compiled patterns for _strip_tool_lines (performance)
_TOOL_XML_BLOCK_RE = re.compile(r"<tool>.*?</tool>", re.IGNORECASE | re.DOTALL)
_TOOL_XML_TAG_RE = re.compile(r"</?tool>\s*\w*\s*>?\s*", re.IGNORECASE)
_TOOL_INLINE_RE = re.compile(r'TOOL:\s*\w+\s*\{[^\n]*\}\s*', re.IGNORECASE)

# ── Cached system info (lazy, runs once) ───────────────

_sysinfo_cache: str | None = None

def get_sysinfo() -> str:
    """Return cached system info, gathering on first call."""
    global _sysinfo_cache
    if _sysinfo_cache is None:
        try:
            from core.tools import sysinfo as _sysinfo
            _sysinfo_cache = _sysinfo()
        except Exception:
            _sysinfo_cache = "(sysinfo unavailable)"
    return _sysinfo_cache


# ── Agent context ─────────────────────────────────────

@dataclass
class AgentContext:
    hot_memories: list[Memory] = field(default_factory=list)
    relevant_memories: list[Memory] = field(default_factory=list)
    active_skill: Skill | None = None
    model: str = ""
    tools_used: list[ToolResult] = field(default_factory=list)

    def to_system_prompt(self) -> str:
        parts = [SYSTEM_PROMPT]

        # Hot memories (short, relevant)
        for m in self.hot_memories[:5]:
            parts.append(f"\n[Memory: {m.type}] {m.title}: {m.content[:200]}")

        # Recalled context
        if self.relevant_memories:
            parts.append("\n## Recalled Context")
            for m in self.relevant_memories:
                parts.append(f"- {m.title}: {m.content[:300]}")

        # Active skill
        if self.active_skill:
            parts.append(f"\n## Active Skill: {self.active_skill.name}")
            parts.append(self.active_skill.body[:2000])

        # Computer context (last — reference material, not instructions)
        parts.append("\n## Your Computer")
        parts.append(get_sysinfo())

        return "\n".join(parts)


class Orchestrator:
    """Multi-turn agent loop with tool execution."""

    def __init__(self, model: str | None = None):
        self.model = model or config.default_model
        self.messages: list[dict] = []
        self.context = AgentContext()
        self.last_tool_results: list[ToolResult] = []

    def reset(self):
        """Clear conversation history and context."""
        self.messages.clear()
        self.context = AgentContext()
        self.last_tool_results.clear()

    def _assemble_context(self, user_message: str):
        self.context.hot_memories = memory_store.get_hot()
        self.context.relevant_memories = memory_store.search(user_message)
        self.context.active_skill = skill_registry.match(user_message)
        self.context.model = self.model
        self.last_tool_results = []

    def _format_messages(self, user_message: str) -> list[dict]:
        sys_prompt = self.context.to_system_prompt()
        msgs = [{"role": "system", "content": sys_prompt}]
        msgs.extend(self.messages[-40:])
        msgs.append({"role": "user", "content": user_message})
        return msgs

    def _parse_tool_calls(self, response: str) -> list[tuple[str, dict]]:
        calls = []
        # First try TOOL: format
        for line in response.split("\n"):
            stripped = line.strip()
            if stripped.startswith("```"):
                continue
            if TOOL_LINE_RE.match(stripped):
                payload = TOOL_LINE_RE.sub("", stripped).strip()
                space_idx = payload.find(" ")
                if space_idx == -1:
                    tool_name = payload
                    args = {}
                else:
                    tool_name = payload[:space_idx]
                    args_str = payload[space_idx:].strip()
                    try:
                        args = json.loads(args_str)
                    except json.JSONDecodeError:
                        args = self._recover_json(args_str, tool_name)
                calls.append((tool_name, args))

        # Fallback: parse <tool> XML format (some models may ignore prompt)
        if not calls:
            calls = self._parse_xml_tool_format(response)

        return calls

    def _parse_xml_tool_format(self, response: str) -> list[tuple[str, dict]]:
        """Parse <tool>name ... JSON ... format (some models default to this)."""
        calls = []
        known_tools = {"write", "read", "edit", "line_edit", "grep", "glob",
                       "shell", "web_fetch", "browse", "mano_cua", "sysinfo", "music"}

        # Find <tool>NAME positions
        tool_pattern = re.compile(r"<tool>\s*(\w+)\s*>?\s*$", re.IGNORECASE | re.MULTILINE)
        matches = list(tool_pattern.finditer(response))

        for i, m in enumerate(matches):
            tool_name = m.group(1)
            if tool_name not in known_tools:
                continue
            body_start = m.end()
            body_end = len(response)
            close_m = re.search(r"</tool>", response[body_start:])
            if close_m:
                body_end = body_start + close_m.start()
            else:
                next_m = re.search(r"<tool>", response[body_start:])
                if next_m:
                    body_end = body_start + next_m.start()

            body = response[body_start:body_end].strip()

            try:
                args = json.loads(body)
                calls.append((tool_name, args))
                continue
            except json.JSONDecodeError:
                pass

            json_match = re.search(r"\{.*\}", body, re.DOTALL)
            if json_match:
                try:
                    args = json.loads(json_match.group())
                    calls.append((tool_name, args))
                except json.JSONDecodeError:
                    if tool_name == "shell":
                        calls.append((tool_name, {"command": body}))
                    else:
                        calls.append((tool_name, {}))

        return calls

    def _recover_json(self, raw: str, tool_name: str) -> dict:
        """Best-effort recovery of malformed JSON tool arguments."""
        if tool_name == "shell" and not raw.strip().startswith("{"):
            return {"command": raw}
        fixed = raw.strip()
        # Remove trailing comma before closing brace
        fixed = re.sub(r",\s*}", "}", fixed)
        # Smart/unicode quotes → straight quotes
        fixed = fixed.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")
        # Single-quoted keys/values → double-quoted (only if no double quotes present)
        if "'" in fixed and '"' not in fixed:
            fixed = fixed.replace("'", '"')
        # Missing closing brace
        if fixed.startswith("{") and not fixed.endswith("}"):
            fixed += "}"
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            return {"command": raw}

    def _execute_tools(self, tool_calls: list[tuple[str, dict]]) -> list[ToolResult]:
        results = []
        for tool_name, args in tool_calls:
            result = tool_registry.call(tool_name, **args)
            self.context.tools_used.append(result)
            results.append(result)
        self.last_tool_results.extend(results)
        return results

    def _format_tool_result_text(self, results: list[ToolResult]) -> str:
        """Format tool results as a single message for the model."""
        return "\n".join(
            f"[TOOL RESULT {r.tool}] exit={r.exit_code} ({r.duration_ms:.0f}ms)\n{r.output[:TOOL_RESULT_MAX_CHARS]}"
            for r in results
        )

    def _store_conversation(self, user_message: str, full_response: str,
                            all_tool_results: list[ToolResult]):
        """Store user+assistant messages, preserving TOOL: lines in history."""
        stored = full_response
        if all_tool_results:
            brief = " | ".join(f"{r.tool}: {r.output[:200]}" for r in all_tool_results)
            stored += f"\n[results: {brief}]"
        self.messages.append({"role": "user", "content": user_message})
        self.messages.append({"role": "assistant", "content": stored})

    def chat(self, user_message: str) -> str:
        self._assemble_context(user_message)
        msgs = self._format_messages(user_message)

        full_response = ""
        all_tool_results: list[ToolResult] = []

        for turn in range(MAX_TOOL_TURNS):
            response = chat(messages=msgs, model=self.model, stream=False)

            tool_calls = self._parse_tool_calls(response)
            if not tool_calls:
                full_response += response
                break

            full_response += response
            results = self._execute_tools(tool_calls)
            all_tool_results.extend(results)

            msgs.append({"role": "assistant", "content": response})
            msgs.append({"role": "user", "content": self._format_tool_result_text(results)})

        self._store_conversation(user_message, full_response, all_tool_results)
        return self._strip_tool_lines(full_response)

    def chat_stream(self, user_message: str) -> Iterator[StreamEvent]:
        """Stream chat with multi-turn tool execution.
        Yields StreamEvents: chunk (text), tool_call (before exec), tool_result (after exec), done.
        """
        self._assemble_context(user_message)
        msgs = self._format_messages(user_message)

        full_response = ""
        all_tool_results: list[ToolResult] = []

        for turn in range(MAX_TOOL_TURNS):
            response = chat(messages=msgs, model=self.model, stream=True)

            buffer = ""
            for chunk in response:
                buffer += chunk
                yield StreamEvent.chunk(chunk)

            tool_calls = self._parse_tool_calls(buffer)
            if not tool_calls:
                full_response += buffer
                break

            full_response += buffer
            for name, args in tool_calls:
                yield StreamEvent.tool_call(name, args)

            results = self._execute_tools(tool_calls)
            all_tool_results.extend(results)

            for r in results:
                yield StreamEvent.tool_result(r.tool, r.output, r.exit_code, r.duration_ms)

            msgs.append({"role": "assistant", "content": buffer})
            msgs.append({"role": "user", "content": self._format_tool_result_text(results)})

        self._store_conversation(user_message, full_response, all_tool_results)
        yield StreamEvent.done()

    @staticmethod
    def _strip_tool_lines(text: str) -> str:
        """Strip TOOL: lines AND <tool> XML blocks from display text."""
        text = _TOOL_XML_BLOCK_RE.sub("", text)
        text = _TOOL_XML_TAG_RE.sub("", text)
        text = _TOOL_INLINE_RE.sub("", text)
        return text.strip()

    def stats(self) -> dict:
        return {
            "model": self.model,
            "messages": len(self.messages),
            "tools_used": len(self.context.tools_used),
            "memories_recalled": len(self.context.relevant_memories),
            "active_skill": self.context.active_skill.name if self.context.active_skill else None,
        }


# ── Sub-agent dispatch ───────────────────────────────

@dataclass
class SubAgent:
    name: str
    task: str
    model: str = "deepseek"


def dispatch(sub_agents: list[SubAgent]) -> list[str]:
    results = []
    for agent in sub_agents:
        orch = Orchestrator(model=agent.model)
        result = orch.chat(agent.task)
        results.append(result)
    return results
