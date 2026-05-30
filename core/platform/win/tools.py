"""Windows platform toolkit - open_app, browser, sysinfo."""

import os
import subprocess
import time
import webbrowser
from pathlib import Path

from core.platform.base import BasePlatformToolkit


class WinToolkit(BasePlatformToolkit):
    """Windows-specific tools: open_app, browser, sysinfo.
    music() inherits the base default: returns error (not available on Windows).
    """

    @property
    def platform_name(self) -> str:
        return "Windows"

    @property
    def tool_names(self) -> list[str]:
        return ["open_app", "browser", "sysinfo"]

    # ── open_app ──────────────────────────────────────

    def open_app(self, app: str, wait: bool = False) -> str:
        """Open a Windows application by common name or path."""
        if not app.strip():
            return "[error] app name required"

        aliases = {
            "chrome": "chrome",
            "google chrome": "chrome",
            "谷歌浏览器": "chrome",
            "edge": "microsoft-edge:",
            "microsoft edge": "microsoft-edge:",
            "wechat": "WeChat",
            "微信": "WeChat",
            "notepad": "notepad",
            "记事本": "notepad",
            "calculator": "calc",
            "计算器": "calc",
            "explorer": "explorer",
            "文件管理器": "explorer",
            "terminal": "wt",
            "windows terminal": "wt",
            "cmd": "cmd",
            "命令提示符": "cmd",
            "powershell": "powershell",
            "settings": "ms-settings:",
            "设置": "ms-settings:",
            "pycharm": "pycharm",
            "vscode": "code",
            "visual studio code": "code",
        }

        raw = app.strip()
        target = aliases.get(raw.lower(), raw)

        errors = []

        # Strategy 1: os.startfile for known executables and URI schemes.
        simple_exes = {"notepad", "calc", "explorer", "cmd", "powershell",
                       "write", "mspaint", "winword", "excel", "pycharm",
                       "code", "chrome"}
        if target in simple_exes:
            try:
                os.startfile(f"{target}.exe")
                return f"Opened app: {target}"
            except Exception as e:
                errors.append(f"startfile: {e}")

        if target.endswith(":"):
            try:
                os.startfile(target)
                return f"Opened app: {target}"
            except Exception as e:
                errors.append(f"startfile uri: {e}")

        # Strategy 2: cmd /c start for everything else
        try:
            cmd = ["cmd", "/c", "start", ""]
            if wait:
                cmd.append("/WAIT")
            cmd.append(target)
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if r.returncode == 0 and not r.stderr.strip():
                return f"Opened app: {target}"
            if r.stderr.strip():
                errors.append(r.stderr.strip())
        except Exception as e:
            errors.append(str(e))

        return f"[error] Could not open app '{app}' as '{target}'. " + " | ".join(e for e in errors if e)

    # ── browser ───────────────────────────────────────

    def browser(self, action: str, url: str = "", selector: str = "",
                text: str = "", js: str = "") -> str:
        """Open browser pages and take screenshots on Windows.

        DOM automation is intentionally not faked here. Without a browser
        automation dependency or an active WebDriver/CDP client, click/type/js
        would be unreliable, so those actions return an explicit error.
        action: navigate | content | click | type | run_js | screenshot
        """
        action = action.lower().strip()

        if action == "navigate":
            if not url:
                return "[error] url required"
            webbrowser.open(url)
            time.sleep(2)
            return f"Navigated to: {url}"

        elif action == "screenshot":
            try:
                from PIL import ImageGrab
                path = f"C:\\Temp\\browser_{int(time.time())}.png"
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                img = ImageGrab.grab()
                img.save(path, "PNG")
                return f"Screenshot saved: {path}"
            except ImportError:
                return "[error] PIL/Pillow required for screenshots. Install: pip install Pillow"
            except Exception as e:
                return f"[error] Screenshot failed: {e}"

        elif action in {"content", "click", "type", "run_js"}:
            return (
                f"[error] browser action '{action}' is not available in the Windows toolkit yet. "
                "Use web_fetch for read-only pages, or add a real browser automation dependency."
            )

        else:
            return "[error] Unknown action. Use: navigate, content, click, type, run_js, screenshot"

    # ── sysinfo ───────────────────────────────────────

    def sysinfo(self) -> str:
        """Gather system info via PowerShell/WMI."""
        import platform, os, shutil
        sections = []

        sections.append(f"OS: {platform.system()} {platform.release()} ({platform.machine()})")

        # CPU via PowerShell
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_Processor | Select-Object -ExpandProperty Name"],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0 and r.stdout.strip():
                sections.append(f"CPU: {r.stdout.strip()}")
        except Exception:
            pass

        # RAM via PowerShell
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB)"],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0 and r.stdout.strip():
                sections.append(f"RAM: {r.stdout.strip()} GB")
        except Exception:
            pass

        # Disk via PowerShell
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-PSDrive C | ForEach-Object { '{0}GB used / {1}GB total' -f "
                 "[math]::Round(($_.Used)/1GB), [math]::Round(($_.Used+$_.Free)/1GB) }"],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0 and r.stdout.strip():
                sections.append(f"Disk: {r.stdout.strip()}")
        except Exception:
            pass

        # Dev tools (check python and python3 on Windows)
        tools_found = [t for t in ["python", "python3", "node", "npm", "git", "pip", "pip3", "docker", "go"]
                       if shutil.which(t)]
        if tools_found:
            sections.append(f"Tools: {', '.join(tools_found)}")

        sections.append(f"User: {os.environ.get('USERNAME', 'unknown')}  Home: {Path.home()}")

        return "\n".join(sections)

    # ── system prompt appendix ────────────────────────

    def get_system_prompt_appendix(self) -> str:
        return _WIN_PROMPT_APPENDIX


_WIN_PROMPT_APPENDIX = """## Available tools (16 total)
| Tool | Key args | Purpose |
|------|----------|---------|
| shell | command, cwd, timeout | Run PowerShell, CMD, or CLI commands |
| read | path, offset, limit | Read file with line numbers |
| write | path, content | Create/overwrite file |
| edit | path, old, new | Find-and-replace first occurrence |
| line_edit | path, start, end, content | Replace line range |
| grep | pattern, path, glob_pattern | Search files |
| glob | pattern, path | Find files |
| web_fetch | url | HTTP GET → text (10k chars) |
| web_search | query, max_results | Bing search → titles+snippets+URLs |
| browse | url | Open URL in default browser (fire-and-forget) |
| open_app | app, wait | Open a Windows app by common name (uses cmd start) |
| browser | action, url/selector/text/js | Windows browser helper: navigate/screenshot; DOM actions return explicit unsupported errors |
| mano_cua | task, app, url | VLA GUI automation (if CLI installed) |
| sysinfo | (none) | OS, hardware, apps, network |
| music | action, song, artist | Not available on Windows |
| memory_add | mtype, title, content, tags, importance | Save memory for future sessions |"""
