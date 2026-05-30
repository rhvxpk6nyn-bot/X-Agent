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

MAX_TOOL_TURNS = 10
MAX_CONSECUTIVE_SAME_TOOL = 3
TOOL_RESULT_MAX_CHARS = 16000


@dataclass
class StreamEvent:
    """Structured event for streaming display."""
    kind: str  # "thinking", "chunk", "tool_call", "tool_result", "done"
    data: str | dict | None = None

    @classmethod
    def thinking(cls, text: str) -> "StreamEvent":
        return cls(kind="thinking", data=text)

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

SYSTEM_PROMPT = """You are X-Agent, an AI agent running on macOS. Execute tasks directly — never describe, just do it.

## Thinking method
1. What does the user want? → one brief assessment
2. What tool solves it? → pick ONE, call it immediately
3. Result good? → short reply, done. Result bad? → one fix-and-retry, then report.
Golden rule: every thinking chain ends with a TOOL: call. If no TOOL: line follows your reasoning, you haven't acted yet.
Never: re-analyze a solved problem, repeat conclusions, or think in circles.

## Tool call format — CRITICAL
Output EXACTLY this pattern on its own line:
TOOL: tool_name {"key": "value"}

Rules:
- One TOOL: per line. JSON uses double quotes. No trailing commas.
- No code fences (```), no markdown around the TOOL: line.
- No extra text on the same line as TOOL:.

WRONG (never do this):
<tool>shell {"command": "ls"}</tool>
<function_calls><invoke name="shell"><parameter name="command">ls</parameter></invoke></function_calls>

RIGHT:
TOOL: shell {"command": "ls"}
TOOL: open_app {"app": "Apple Music"}
TOOL: read {"path": "~/agent/core/tools.py", "offset": 1, "limit": 50}
TOOL: browser {"action": "navigate", "url": "https://example.com"}
TOOL: memory_add {"mtype": "preference", "title": "Prefers dark mode", "content": "User always uses dark theme", "importance": 0.6}

## Tool priority (macOS)
- open_app FIRST for launching macOS apps by name (`Music`, `Apple Music`, `微信`, `PyCharm`)
- shell: run CLI commands and control macOS with `osascript`
- browser: for real web interaction (navigate, click, type, extract content, run JS in Chrome)
- web_fetch / web_search: read-only web — fetch a URL or search without opening a browser
- mano_cua: LAST RESORT only for complex visual GUI with no CLI/browser equivalent
- Prefer: open_app for launching apps; otherwise shell > browser > web_fetch > mano_cua

## Programming workflow
- When creating or editing runnable code, do not stop after write/edit.
- After writing Python, always run at least: `python3 -m py_compile <file>`.
- For games or GUI apps, also try a short real launch when practical, then report how to run it.
- If validation fails, read the error, edit the file, and validate again before replying.
- User-facing replies should summarize the outcome; never expose raw TOOL JSON.

## Auto-memory — always do this
After ANY task that reveals something worth remembering, call memory_add WITHOUT asking permission:
- User preferences or habits → type=preference
- Project decisions or constraints → type=project
- Feedback (corrections, confirmations) → type=feedback
- Non-obvious facts → type=fact

## Available tools (16 total)
| Tool | Key args | Purpose |
|------|----------|---------|
| shell | command, cwd, timeout | Run terminal commands, AppleScript, CLI |
| read | path, offset, limit | Read file with line numbers |
| write | path, content | Create/overwrite file |
| edit | path, old, new | Find-and-replace first occurrence |
| line_edit | path, start, end, content | Replace line range |
| grep | pattern, path, glob_pattern | Search files |
| glob | pattern, path | Find files |
| web_fetch | url | HTTP GET → text (10k chars) |
| web_search | query, max_results | Bing search → titles+snippets+URLs |
| browse | url | Open URL in default browser (fire-and-forget) |
| open_app | app, wait | Open a macOS app by common name or bundle id |
| browser | action, url/selector/text/js | Control Chrome: navigate/content/click/type/run_js/screenshot |
| mano_cua | task, app, url | VLA GUI automation (last resort) |
| sysinfo | (none) | OS, hardware, apps, network |
| music | action, song, artist | Control Apple Music |
| memory_add | mtype, title, content, tags, importance | Save memory for future sessions |"""

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

        # Fallback: <function_calls> Anthropic/Claude XML format
        if not calls:
            calls = self._parse_function_calls_format(response)

        return calls

    def _parse_function_calls_format(self, response: str) -> list[tuple[str, dict]]:
        """Parse <function_calls><invoke name="..."><parameter name="...">...</invoke> (Anthropic format)."""
        calls = []
        known_tools = {"write", "read", "edit", "line_edit", "grep", "glob",
                       "shell", "web_fetch", "web_search", "browse", "open_app", "mano_cua",
                       "sysinfo", "music", "memory_add", "browser"}

        invoke_pattern = re.compile(
            r"<invoke\s+name=\"(\w+)\">(.*?)</invoke>", re.DOTALL | re.IGNORECASE
        )
        param_pattern = re.compile(
            r"<parameter\s+name=\"(\w+)\">(.*?)</parameter>", re.DOTALL | re.IGNORECASE
        )

        for m in invoke_pattern.finditer(response):
            tool_name = m.group(1)
            if tool_name not in known_tools:
                continue
            params_str = m.group(2)
            args = {}
            for pm in param_pattern.finditer(params_str):
                pname = pm.group(1)
                pval = pm.group(2).strip()
                args[pname] = pval
            if args:
                calls.append((tool_name, args))
        return calls

    def _parse_xml_tool_format(self, response: str) -> list[tuple[str, dict]]:
        """Parse <tool>name ... JSON ... format (some models default to this)."""
        calls = []
        known_tools = {"write", "read", "edit", "line_edit", "grep", "glob",
                       "shell", "web_fetch", "web_search", "browse", "mano_cua",
                       "sysinfo", "music", "memory_add", "browser"}

        # Find <tool>NAME — also capture same-line JSON if present
        tool_pattern = re.compile(r"<tool>\s*(\w+)\s*>?", re.IGNORECASE)
        matches = list(tool_pattern.finditer(response))

        for i, m in enumerate(matches):
            tool_name = m.group(1)
            if tool_name not in known_tools:
                continue
            body_start = m.end()

            # Check for same-line JSON (e.g. <tool>shell {"command": "ls"})
            same_line_end = response.find("\n", body_start)
            if same_line_end == -1:
                same_line_end = len(response)
            same_line = response[body_start:same_line_end].strip()
            if same_line.startswith("{"):
                try:
                    args = json.loads(same_line)
                    calls.append((tool_name, args))
                    continue
                except json.JSONDecodeError:
                    pass

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

            json_match = re.search(r"\{.*?\}", body, re.DOTALL)
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
        """Store user+assistant messages. Strips TOOL: lines to keep history clean."""
        clean = self._strip_tool_lines(full_response)
        if all_tool_results:
            brief = " | ".join(f"{r.tool}: {r.output[:120]}" for r in all_tool_results[-5:])
            clean += f"\n[tools used: {brief}]"
        self.messages.append({"role": "user", "content": user_message})
        self.messages.append({"role": "assistant", "content": clean})

    def chat(self, user_message: str) -> str:
        self._assemble_context(user_message)
        msgs = self._format_messages(user_message)

        full_response = ""
        all_tool_results: list[ToolResult] = []

        for turn in range(MAX_TOOL_TURNS):
            try:
                response = chat(messages=msgs, model=self.model, stream=False)
            except Exception as e:
                all_tool_results.append(ToolResult("error", str(e), -1, 0))
                break

            tool_calls = self._parse_tool_calls(response)
            if not tool_calls:
                full_response += response
                if self._should_continue(response, "stop"):
                    msgs.append({"role": "assistant", "content": response})
                    msgs.append({"role": "user", "content": "[continue]"})
                    continue
                break

            full_response += response
            results = self._execute_tools(tool_calls)
            all_tool_results.extend(results)

            msgs.append({"role": "assistant", "content": response})
            msgs.append({"role": "user", "content": self._format_tool_result_text(results)})

            # Always add continue prompt after tool results for non-streaming
            msgs.append({"role": "user", "content": "[continue]"})

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
        consecutive_same_tool = 0
        last_tool_key: tuple[str, str] | None = None  # (tool_name, json_args)

        for turn in range(MAX_TOOL_TURNS):
            try:
                response = chat(messages=msgs, model=self.model, stream=True)
            except Exception as e:
                yield StreamEvent.chunk(f"\n[stream error: {e}]")
                break

            buffer = ""
            reasoning = ""
            finish_reason = "unknown"
            for chunk in response:
                if isinstance(chunk, dict):
                    if "_reasoning" in chunk:
                        reasoning += chunk["_reasoning"]
                        yield StreamEvent.thinking(chunk["_reasoning"])
                    else:
                        finish_reason = chunk.get("_finish_reason", "unknown")
                else:
                    buffer += chunk
                    yield StreamEvent.chunk(chunk)

            tool_calls = self._parse_tool_calls(buffer)
            if not tool_calls:
                full_response += buffer
                if self._should_continue(buffer, finish_reason):
                    msgs.append({"role": "assistant", "content": buffer})
                    msgs.append({"role": "user", "content": "[continue]"})
                    continue
                break

            # Detect tool loops: same tool with same args called repeatedly
            for name, args in tool_calls:
                args_key = (name, json.dumps(args, sort_keys=True))
                if args_key == last_tool_key:
                    consecutive_same_tool += 1
                else:
                    consecutive_same_tool = 0
                    last_tool_key = args_key

                if consecutive_same_tool >= MAX_CONSECUTIVE_SAME_TOOL:
                    yield StreamEvent.chunk("\n[stopped: same tool called repeatedly]")
                    all_tool_results.append(
                        ToolResult("loop_break", json.dumps(args), "Repeated tool call detected", 0, 0))
                    # Force exit the outer loop
                    full_response += buffer
                    self._store_conversation(user_message, full_response, all_tool_results)
                    yield StreamEvent.done()
                    return

            full_response += buffer
            for name, args in tool_calls:
                yield StreamEvent.tool_call(name, args)

            results = self._execute_tools(tool_calls)
            all_tool_results.extend(results)

            for r in results:
                yield StreamEvent.tool_result(r.tool, r.output, r.exit_code, r.duration_ms)

            msgs.append({"role": "assistant", "content": buffer})
            msgs.append({"role": "user", "content": self._format_tool_result_text(results)})

            # If API truncated during tool call, request continuation
            if finish_reason == "length":
                msgs.append({"role": "user", "content": "[continue]"})

        self._store_conversation(user_message, full_response, all_tool_results)
        yield StreamEvent.done()

    @staticmethod
    def _should_continue(buffer: str, finish_reason: str) -> bool:
        """Continue only when the API explicitly truncated output."""
        return finish_reason == "length"

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
