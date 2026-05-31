"""X-Agent tool system — shell, file, search, edit, web, GUI."""

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from core.platform import get_toolkit

_platform = get_toolkit()


@dataclass
class ToolResult:
    tool: str
    command: str
    output: str
    exit_code: int = 0
    duration_ms: float = 0
    error: str = ""


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Callable] = {}
        self._results: list[ToolResult] = []

    def register(self, name: str, fn: Callable):
        self._tools[name] = fn

    def call(self, name: str, **kwargs) -> ToolResult:
        if name not in self._tools:
            return ToolResult(tool=name, command="", output="", error=f"Unknown tool: {name}")
        start = time.time()
        try:
            output = self._tools[name](**kwargs)
            result = ToolResult(
                tool=name,
                command=json.dumps(kwargs, ensure_ascii=False),
                output=str(output),
                duration_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            result = ToolResult(
                tool=name,
                command=json.dumps(kwargs, ensure_ascii=False),
                output="",
                error=str(e),
                exit_code=1,
                duration_ms=(time.time() - start) * 1000,
            )
        self._results.append(result)
        return result

    @property
    def last_results(self) -> list[ToolResult]:
        return self._results[-20:]


# ── Tool implementations ─────────────────────────────

def _resolve_path(path: str, cwd: str | None = None) -> Path:
    p = Path(path)
    if not p.is_absolute() and cwd:
        p = Path(cwd) / p
    return p.expanduser().resolve()


def shell(command: str, cwd: str | None = None, timeout: int = 120_000) -> str:
    """Execute a shell command. Returns stdout or error details."""
    result = subprocess.run(
        command, shell=True, capture_output=True, text=True,
        cwd=cwd or str(Path.cwd()),
        timeout=timeout / 1000,
    )
    output = result.stdout
    if result.returncode != 0:
        output += f"\n[exit code: {result.returncode}]"
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
    return output.strip() or "(ok)"


def read_file(path: str, offset: int = 0, limit: int | None = None) -> str:
    """Read a file with optional slicing by line number."""
    p = _resolve_path(path)
    if not p.exists():
        return f"[error] File not found: {path}"
    if p.is_dir():
        return f"[error] Is a directory: {path}"
    lines = p.read_text().split("\n")
    total = len(lines)
    if limit:
        lines = lines[offset:offset + limit]
    elif offset:
        lines = lines[offset:]
    # Add line numbers for reference
    numbered = []
    for i, line in enumerate(lines):
        numbered.append(f"{(offset + i + 1):>4} | {line}")
    return "\n".join(numbered)


def write_file(path: str, content: str) -> str:
    """Write content to a file. Creates parent directories if needed."""
    p = _resolve_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"Written {len(content)} bytes to {p}"


def edit_file(path: str, old: str, new: str) -> str:
    """Find and replace a string in a file. Only replaces the first occurrence."""
    p = _resolve_path(path)
    if not p.exists():
        return f"[error] File not found: {path}"
    content = p.read_text()
    idx = content.find(old)
    if idx < 0:
        return f"[error] String not found in {path}. Use read first to check exact content."
    # Line number of the edit, computed from the original match position
    line_num = content[:idx].count("\n") + 1
    content = content[:idx] + new + content[idx + len(old):]
    p.write_text(content)
    return f"Edited {path} (line ~{line_num})"


def line_edit(path: str, start: int, end: int, content: str) -> str:
    """Replace lines start-end (1-indexed, inclusive) with new content."""
    p = _resolve_path(path)
    if not p.exists():
        return f"[error] File not found: {path}"
    lines = p.read_text().split("\n")
    if start < 1 or end > len(lines):
        return f"[error] Line range {start}-{end} out of bounds (file has {len(lines)} lines)"
    new_lines = lines[:start - 1] + content.split("\n") + lines[end:]
    p.write_text("\n".join(new_lines))
    return f"Replaced lines {start}-{end} in {path}"


def grep(pattern: str, path: str = ".", glob_pattern: str = "*",
         max_results: int = 30, ignore_case: bool = True) -> str:
    """Search for a regex pattern in files. Uses system grep for speed, falls back to Python."""
    base = _resolve_path(path)
    if not base.exists():
        return f"[error] Path not found: {path}"

    # Try system grep first (much faster for large codebases)
    try:
        import shutil
        if shutil.which("grep") and glob_pattern == "*":
            cmd = ["grep", "-rn", "--include=*"]
            if ignore_case:
                cmd.append("-i")
            cmd.extend(["-m", str(max_results), pattern, str(base)])
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
            )
            if result.returncode in (0, 1):  # 0=matches found, 1=no matches
                output = result.stdout.strip()
                if not output:
                    return f"No matches for '{pattern}' in {path}"
                # Truncate to max_results lines
                lines = output.split("\n")[:max_results]
                return f"Found {len(lines)} matches:\n" + "\n".join(lines)
            # On error (returncode > 1), fall through to Python fallback
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass  # Fall through to Python fallback

    # Python fallback
    import re
    files = list(base.rglob(glob_pattern)) if base.is_dir() else [base]
    results = []
    count = 0

    for fp in files:
        if not fp.is_file() or fp.suffix in (".pyc", ".pyo", ".so", ".dylib", ".bin"):
            continue
        try:
            text = fp.read_text()
        except (UnicodeDecodeError, PermissionError, OSError):
            continue
        flags = re.IGNORECASE if ignore_case else 0
        for line_num, line in enumerate(text.split("\n"), 1):
            try:
                if re.search(pattern, line, flags):
                    rel = fp.relative_to(base) if base.is_dir() else fp.name
                    results.append(f"{rel}:{line_num}: {line.strip()[:200]}")
                    count += 1
                    if count >= max_results:
                        break
            except re.error:
                return f"[error] Invalid regex pattern: {pattern}"
        if count >= max_results:
            break

    if not results:
        return f"No matches for '{pattern}' in {path}"
    return f"Found {count} matches:\n" + "\n".join(results)


def glob_files(pattern: str, path: str = ".") -> str:
    """Find files matching a glob pattern. e.g. '**/*.py' or 'src/**/*.tsx'."""
    base = _resolve_path(path)
    if not base.exists():
        return f"[error] Path not found: {path}"

    files = sorted(base.glob(pattern))
    # Filter to files only, skip hidden and common ignores
    result = []
    for f in files:
        if f.is_file() and not any(p.startswith(".") for p in f.parts if p != "."):
            rel = f.relative_to(base)
            result.append(str(rel))
    if not result:
        return f"No files matching '{pattern}' in {path}"
    return "\n".join(result[:50])


def web_fetch(url: str) -> str:
    """Fetch URL content as text."""
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace")[:10000]
    except Exception as e:
        return f"Fetch failed: {e}"


def web_search(query: str, max_results: int = 8) -> str:
    """Search the web using Bing. Returns titles + snippets + URLs."""
    import urllib.request
    import urllib.parse
    try:
        qs = urllib.parse.urlencode({"q": query, "count": str(max_results), "setlang": "zh-CN"})
        url = f"https://www.bing.com/search?{qs}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"Search failed: {e}"

    import re
    results = []
    # Bing result blocks: li.b_algo > h2 > a for title+url, div/p.b_caption for snippet
    blocks = re.findall(
        r'<li[^>]*class="[^"]*b_algo[^"]*"[^>]*>.*?<a[^>]*href="(https?://[^"]*)"[^>]*>(.*?)</a>',
        html, re.DOTALL | re.IGNORECASE
    )
    snippets = re.findall(
        r'<(?:div|p)[^>]*class="[^"]*b_caption[^"]*"[^>]*>\s*<p[^>]*>(.*?)</p>',
        html, re.DOTALL | re.IGNORECASE
    )
    if not snippets:
        snippets = re.findall(
            r'<(?:div|p)[^>]*class="[^"]*(?:b_lineclamp|b_algoSlug|b_caption)[^"]*"[^>]*>(.*?)</(?:div|p)>',
            html, re.DOTALL | re.IGNORECASE
        )

    for i, (raw_url, title) in enumerate(blocks[:max_results]):
        title = re.sub(r"<[^>]+>", "", title).strip()
        if not title:
            continue
        snippet = ""
        if i < len(snippets):
            snippet = re.sub(r"<[^>]+>", "", snippets[i]).strip()
        results.append(f"{title}\n  {snippet}\n  {raw_url}")

    if not results:
        return f"No results found for '{query}'"
    return f"Search: {query}\n" + "\n\n".join(results)


def browse(url: str) -> str:
    """Open URL in default browser."""
    import webbrowser
    webbrowser.open(url)
    return f"Opened {url}"


def open_app(app: str, wait: bool = False) -> str:
    """Open an application by common name (platform-specific)."""
    return _platform.open_app(app, wait)


def mano_cua(task: str, app: str | None = None, url: str | None = None,
             local: bool = False, max_steps: int = 15, timeout: int = 120_000) -> str:
    """Run GUI automation via mano-cua CLI. timeout in milliseconds."""
    import shutil
    if not shutil.which("mano-cua"):
        return "[error] mano-cua CLI not found. Install it: npm i -g @anthropic/mano-cua"

    cmd = ["mano-cua", "run", task, "--max-steps", str(max_steps)]
    if app:
        cmd.extend(["--app", app])
    if url:
        cmd.extend(["--url", url])
    if local:
        cmd.append("--local")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout / 1000)
        return result.stdout or result.stderr or "(no output)"
    except subprocess.TimeoutExpired:
        return f"[error] mano_cua timed out after {timeout / 1000:.0f}s"
    except FileNotFoundError:
        return "[error] mano-cua CLI not found. Install it: npm i -g @anthropic/mano-cua"


def music(action: str = "play", song: str = "", artist: str = "",
          album: str = "", playlist: str = "") -> str:
    """Control music playback (platform-specific: Apple Music on macOS, unavailable on Windows)."""
    return _platform.music(action, song, artist, album, playlist)


def volume(action: str = "get", level: int | None = None, step: int = 10) -> str:
    """Control system output volume with the current platform toolkit."""
    return _platform.volume(action, level, step)


def sysinfo() -> str:
    """Gather essential system info (platform-specific)."""
    return _platform.sysinfo()


def memory_add(mtype: str = "note", title: str = "", content: str = "",
               tags: str = "", importance: float = 0.5) -> str:
    """Save a memory for later recall. Use proactively: user preferences, project decisions,
    feedback patterns, facts worth remembering across sessions.
    mtype: note, fact, rule, feedback, preference, project, reference
    importance: 0.1 (trivial) to 1.0 (critical), default 0.5"""
    from core.memory import store, Memory
    import time
    mem = Memory(
        memory_id=f"auto-{time.time_ns()}",
        mtype=mtype,
        title=title,
        content=content,
        tags=[t.strip() for t in tags.split(",") if t.strip()],
        importance=importance,
    )
    store.add(mem, "warm")
    return f"Memory saved: {title} (type={mtype}, importance={importance})"


def browser(action: str, url: str = "", selector: str = "",
            text: str = "", js: str = "") -> str:
    """Control browser with the current platform toolkit."""
    return _platform.browser(action, url, selector, text, js)


# ── Global instance ──────────────────────────────────

tools = ToolRegistry()
tools.register("shell", shell)
tools.register("read", read_file)
tools.register("write", write_file)
tools.register("edit", edit_file)
tools.register("line_edit", line_edit)
tools.register("grep", grep)
tools.register("glob", glob_files)
tools.register("web_fetch", web_fetch)
tools.register("web_search", web_search)
tools.register("browse", browse)
tools.register("open_app", open_app)
tools.register("mano_cua", mano_cua)
tools.register("sysinfo", sysinfo)
tools.register("music", music)
tools.register("volume", volume)
tools.register("memory_add", memory_add)
tools.register("browser", browser)
