"""X-Agent tool system — shell, file, search, edit, web, GUI."""

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


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
    if old not in content:
        return f"[error] String not found in {path}. Use read first to check exact content."
    content = content.replace(old, new, 1)
    p.write_text(content)
    # Show context of the edit
    idx = content.find(new)
    line_num = content[:idx].count("\n") + 1
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


def browse(url: str) -> str:
    """Open URL in default browser."""
    import webbrowser
    webbrowser.open(url)
    return f"Opened {url}"


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
    """Control Apple Music via AppleScript. Actions: play, pause, playpause, next, previous, current, search, open."""
    import shutil
    if not shutil.which("osascript"):
        return "[error] osascript not available (macOS only)"

    action = action.lower()
    try:
        if action == "play":
            if song:
                # Search library for song, optionally filter by artist/album
                query_parts = [f'name contains "{song}"']
                if artist:
                    query_parts.append(f'artist contains "{artist}"')
                if album:
                    query_parts.append(f'album contains "{album}"')
                query = " and ".join(query_parts)
                script = f'''
                tell application "Music"
                    set found to (first track whose {query})
                    play found
                    return "Playing: " & name of found & " — " & artist of found
                end tell
                '''
            elif playlist:
                script = f'''
                tell application "Music"
                    play playlist "{playlist}"
                    return "Playing playlist: {playlist}"
                end tell
                '''
            else:
                script = '''
                tell application "Music"
                    play
                    return "Resumed playback"
                end tell
                '''
        elif action == "pause":
            script = 'tell application "Music" to pause\nreturn "Paused"'
        elif action == "playpause":
            script = 'tell application "Music" to playpause\nreturn "Toggled play/pause"'
        elif action == "next":
            script = 'tell application "Music" to next track\nreturn "Skipped to next"'
        elif action == "previous":
            script = 'tell application "Music" to previous track\nreturn "Went to previous"'
        elif action == "current":
            script = '''
            tell application "Music"
                if player state is playing then
                    set t to current track
                    return "Now playing: " & name of t & " — " & artist of t & " (" & album of t & ")"
                else
                    return "Not playing"
                end if
            end tell
            '''
        elif action == "search":
            if not song:
                return "[error] song name required for search"
            script = f'''
            tell application "Music"
                activate
                tell application "System Events"
                    keystroke "f" using command down
                    delay 0.3
                    keystroke "a" using command down
                    keystroke "{song}"
                end tell
                return "Searched for: {song}"
            end tell
            '''
        elif action == "open":
            script = 'tell application "Music" to activate\nreturn "Opened Music app"'
        else:
            return f"[error] Unknown action: {action}. Use: play, pause, playpause, next, previous, current, search, open"

        osa_cmd = ["osascript", "-e", script]
        result = subprocess.run(osa_cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            err = result.stderr.strip()
            # Give a helpful error
            if "Can't get" in err or "does not understand" in err:
                return f"[error] Song not found in your library: {song}"
            return f"[error] {err}"
        return result.stdout.strip() or "(ok)"
    except subprocess.TimeoutExpired:
        return "[error] Music command timed out"


def sysinfo() -> str:
    """Gather comprehensive system info: OS, hardware, disk, apps, dev tools, network."""
    import platform
    sections = []

    # ── OS ──
    sections.append("## Operating System")
    sections.append(f"  System:   {platform.system()} {platform.release()}")
    sections.append(f"  Version:  {platform.version()}")
    sections.append(f"  Arch:     {platform.machine()}")
    try:
        r = subprocess.run(["sw_vers"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            for line in r.stdout.strip().split("\n"):
                sections.append(f"  {line.strip()}")
    except Exception:
        pass

    # ── Hardware ──
    sections.append("\n## Hardware")
    try:
        r = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            sections.append(f"  CPU:      {r.stdout.strip()}")
    except Exception:
        pass
    try:
        r = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            mem_bytes = int(r.stdout.strip())
            sections.append(f"  RAM:      {mem_bytes // (1024**3)} GB")
    except Exception:
        pass
    try:
        r = subprocess.run(["sysctl", "-n", "hw.model"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            sections.append(f"  Model:    {r.stdout.strip()}")
    except Exception:
        pass

    # ── Disk ──
    sections.append("\n## Disk Usage")
    try:
        r = subprocess.run(["df", "-h", "/"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            lines = r.stdout.strip().split("\n")
            if len(lines) >= 2:
                parts = lines[1].split()
                if len(parts) >= 5:
                    sections.append(f"  Root:     {parts[2]} used / {parts[1]} total ({parts[4]} used)")
    except Exception:
        pass
    try:
        r = subprocess.run(["df", "-h", str(Path.home())], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            lines = r.stdout.strip().split("\n")
            if len(lines) >= 2:
                parts = lines[1].split()
                if len(parts) >= 5:
                    sections.append(f"  Home:     {parts[2]} used / {parts[1]} total ({parts[4]} used)")
    except Exception:
        pass

    # ── Installed Apps ──
    sections.append("\n## Installed Applications (top 40)")
    app_dirs = [Path("/Applications"), Path.home() / "Applications"]
    apps_found = []
    for ad in app_dirs:
        if ad.exists():
            for item in sorted(ad.iterdir()):
                if item.suffix == ".app" and not item.name.startswith("."):
                    apps_found.append(item.stem)
    if apps_found:
        sections.append("  " + ", ".join(apps_found[:40]))
    else:
        sections.append("  (none found)")

    # ── Dev Tools ──
    sections.append("\n## Development Tools")
    tools_list = [
        ("python3", ["python3", "--version"]),
        ("python", ["python", "--version"]),
        ("node", ["node", "--version"]),
        ("npm", ["npm", "--version"]),
        ("git", ["git", "--version"]),
        ("pip3", ["pip3", "--version"]),
        ("brew", ["brew", "--version"]),
        ("docker", ["docker", "--version"]),
        ("go", ["go", "version"]),
        ("rustc", ["rustc", "--version"]),
    ]
    import shutil
    for name, cmd in tools_list:
        try:
            path = shutil.which(name)
            if path:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                ver = r.stdout.strip().split("\n")[0][:80]
                sections.append(f"  {name}:  {ver}  ({path})")
            else:
                sections.append(f"  {name}:  (not installed)")
        except Exception:
            sections.append(f"  {name}:  (error checking)")

    # ── Network ──
    sections.append("\n## Network")
    sections.append(f"  Hostname: {platform.node()}")
    try:
        r = subprocess.run(["ifconfig", "en0"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            for line in r.stdout.split("\n"):
                line = line.strip()
                if "inet " in line and "netmask" in line:
                    sections.append(f"  en0:      {line}")
                    break
    except Exception:
        pass

    # ── Home Directory ──
    sections.append("\n## Home Directory Overview")
    home = Path.home()
    try:
        top_items = sorted([p for p in home.iterdir() if not p.name.startswith(".")],
                          key=lambda p: (not p.is_dir(), p.name.lower()))
        dirs = [f"{p.name}/" for p in top_items if p.is_dir()][:20]
        files = [p.name for p in top_items if p.is_file()][:10]
        if dirs:
            sections.append("  Dirs:  " + ", ".join(dirs))
        if files:
            sections.append("  Files: " + ", ".join(files))
    except Exception:
        pass

    # ── Shell & User ──
    sections.append("\n## Shell & User")
    import os
    sections.append(f"  User:     {os.environ.get('USER', 'unknown')}")
    sections.append(f"  Shell:    {os.environ.get('SHELL', 'unknown')}")
    sections.append(f"  Home:     {home}")
    sections.append(f"  PATH:     {os.environ.get('PATH', '')[:300]}")

    return "\n".join(sections)


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
tools.register("browse", browse)
tools.register("mano_cua", mano_cua)
tools.register("sysinfo", sysinfo)
tools.register("music", music)
