"""macOS platform toolkit — open_app, music, browser, sysinfo."""

import subprocess
import time
from pathlib import Path

from core.platform.base import BasePlatformToolkit


class MacToolkit(BasePlatformToolkit):
    """macOS-specific tools: open_app, music (Apple Music), browser (Chrome), sysinfo."""

    @property
    def platform_name(self) -> str:
        return "macOS"

    @property
    def tool_names(self) -> list[str]:
        return ["open_app", "music", "browser", "sysinfo"]

    # ── open_app ──────────────────────────────────────

    def open_app(self, app: str, wait: bool = False) -> str:
        """Open a macOS application by common name or bundle id."""
        if not app.strip():
            return "[error] app name required"

        aliases = {
            "apple music": "Music",
            "music": "Music",
            "音乐": "Music",
            "safari": "Safari",
            "chrome": "Google Chrome",
            "google chrome": "Google Chrome",
            "谷歌浏览器": "Google Chrome",
            "wechat": "WeChat",
            "微信": "WeChat",
            "pycharm": "PyCharm",
            "final cut": "Final Cut Pro",
            "final cut pro": "Final Cut Pro",
            "剪映": "剪映专业版",
            "keynote": "Keynote",
            "pages": "Pages",
            "numbers": "Numbers",
            "finder": "Finder",
            "terminal": "Terminal",
            "终端": "Terminal",
            "settings": "System Settings",
            "system settings": "System Settings",
            "系统设置": "System Settings",
        }

        raw = app.strip()
        target = aliases.get(raw.lower(), raw)

        commands = [
            ["open", "-a", target],
            ["open", "-b", raw],
        ]
        if wait:
            commands[0].insert(1, "-W")

        errors = []
        for cmd in commands:
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            except Exception as e:
                errors.append(str(e))
                continue
            if result.returncode == 0:
                return f"Opened app: {target}"
            errors.append((result.stderr or result.stdout or "").strip())

        return f"[error] Could not open app '{app}' as '{target}'. " + " | ".join(e for e in errors if e)

    # ── music (Apple Music via AppleScript) ───────────

    def music(self, action: str = "play", song: str = "", artist: str = "",
              album: str = "", playlist: str = "") -> str:
        """Control Apple Music via AppleScript. Actions: play, pause, playpause, next, previous, current, search, open."""
        import shutil
        if not shutil.which("osascript"):
            return "[error] osascript not available (macOS only)"

        def _osa(s: str) -> str:
            return s.replace("\\", "\\\\").replace('"', '\\"')

        action = action.lower()
        song_s, artist_s, album_s, playlist_s = _osa(song), _osa(artist), _osa(album), _osa(playlist)

        try:
            if action == "play":
                if song_s:
                    query_parts = [f'name contains "{song_s}"']
                    if artist_s:
                        query_parts.append(f'artist contains "{artist_s}"')
                    if album_s:
                        query_parts.append(f'album contains "{album_s}"')
                    query = " and ".join(query_parts)
                    script = f'''
                    tell application "Music"
                        set found to (first track whose {query})
                        play found
                        return "Playing: " & name of found & " — " & artist of found
                    end tell
                    '''
                elif playlist_s:
                    script = f'''
                    tell application "Music"
                        play playlist "{playlist_s}"
                        return "Playing playlist: {playlist_s}"
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
                if not song_s:
                    return "[error] song name required for search"
                script = f'''
                tell application "Music"
                    activate
                    tell application "System Events"
                        keystroke "f" using command down
                        delay 0.3
                        keystroke "a" using command down
                        keystroke "{song_s}"
                    end tell
                    return "Searched for: {song_s}"
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
                if "Can't get" in err or "does not understand" in err:
                    return f"[error] Song not found in your library: {song}"
                return f"[error] {err}"
            return result.stdout.strip() or "(ok)"
        except subprocess.TimeoutExpired:
            return "[error] Music command timed out"

    # ── browser (Chrome via AppleScript + JS) ─────────

    def browser(self, action: str, url: str = "", selector: str = "",
                text: str = "", js: str = "") -> str:
        """Control Google Chrome via AppleScript + JS injection.
        action: navigate | content | click | type | run_js | screenshot
        """
        def _osa(script: str, timeout_val: int = 20) -> tuple[str, str]:
            r = subprocess.run(["osascript", "-e", script],
                               capture_output=True, text=True, timeout=timeout_val)
            return r.stdout.strip(), r.stderr.strip()

        def _js(code: str) -> str:
            escaped = code.replace("\\", "\\\\").replace('"', '\\"')
            out, err = _osa(
                f'tell application "Google Chrome"\n'
                f'  execute active tab of first window javascript "{escaped}"\n'
                f'end tell'
            )
            return out or (f"[error] {err}" if err else "(no result)")

        action = action.lower().strip()

        if action == "navigate":
            if not url:
                return "[error] url required"
            esc = url.replace("\\", "\\\\").replace('"', '\\"')
            out, err = _osa(
                f'tell application "Google Chrome"\n'
                f'  if (count of windows) = 0 then make new window\n'
                f'  set URL of active tab of first window to "{esc}"\n'
                f'  activate\n'
                f'end tell'
            )
            if err and "error" in err.lower():
                return f"[error] {err}"
            time.sleep(2)
            return f"Navigated to: {url}"

        elif action == "content":
            if selector:
                esc = selector.replace("'", "\\'")
                code = f"(function(){{var e=document.querySelector('{esc}');return e?e.innerText.trim().slice(0,8000):'[not found]'}})()"
            else:
                code = "document.body.innerText.trim().slice(0,8000)"
            return _js(code)

        elif action == "click":
            if not selector:
                return "[error] selector required"
            esc = selector.replace("'", "\\'").replace('"', '\\"')
            code = (
                "(function(){"
                f"var el=document.querySelector('{esc}');"
                "if(!el){"
                f"  var all=document.querySelectorAll('a,button,input,[role=button]');"
                f"  for(var i=0;i<all.length;i++){{if(all[i].textContent.trim().includes('{esc}')){{el=all[i];break;}}}}"
                "}"
                "if(el){el.click();return 'clicked: '+(el.textContent.trim().slice(0,60)||el.tagName);}"
                f"return '[error] not found: {esc}';"
                "})()"
            )
            return _js(code)

        elif action == "type":
            if not selector or not text:
                return "[error] selector and text required"
            esc_sel = selector.replace("'", "\\'")
            esc_text = text.replace("\\", "\\\\").replace("'", "\\'")
            code = (
                "(function(){"
                f"var el=document.querySelector('{esc_sel}');"
                "if(!el)return '[error] element not found';"
                "el.focus();"
                f"el.value='{esc_text}';"
                "el.dispatchEvent(new Event('input',{bubbles:true}));"
                "el.dispatchEvent(new Event('change',{bubbles:true}));"
                "return 'typed into: '+(el.name||el.id||el.tagName);"
                "})()"
            )
            return _js(code)

        elif action == "run_js":
            if not js:
                return "[error] js required"
            return _js(js)

        elif action == "screenshot":
            path = f"/tmp/browser_{int(time.time())}.png"
            r = subprocess.run(["screencapture", "-x", path],
                               capture_output=True, text=True, timeout=10)
            return f"Screenshot saved: {path}" if r.returncode == 0 else f"[error] {r.stderr}"

        else:
            return "[error] Unknown action. Use: navigate, content, click, type, run_js, screenshot"

    # ── sysinfo ───────────────────────────────────────

    def sysinfo(self) -> str:
        """Gather essential system info at startup."""
        import platform, os, shutil
        sections = []

        sections.append(f"OS: {platform.system()} {platform.release()} ({platform.machine()})")

        try:
            r = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                sections.append(f"CPU: {r.stdout.strip()}")
        except Exception:
            pass
        try:
            r = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                sections.append(f"RAM: {int(r.stdout.strip()) // (1024**3)} GB")
        except Exception:
            pass

        try:
            r = subprocess.run(["df", "-h", str(Path.home())], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                parts = r.stdout.strip().split("\n")[1].split()
                if len(parts) >= 5:
                    sections.append(f"Disk: {parts[2]} used / {parts[1]} total ({parts[4]} used)")
        except Exception:
            pass

        tools_found = [t for t in ["python3", "node", "npm", "git", "pip3", "brew", "docker", "go"] if shutil.which(t)]
        if tools_found:
            sections.append(f"Tools: {', '.join(tools_found)}")

        sections.append(f"User: {os.environ.get('USER', 'unknown')}  Shell: {os.environ.get('SHELL', 'unknown')}  Home: {Path.home()}")

        return "\n".join(sections)

    # ── system prompt appendix ────────────────────────

    def get_system_prompt_appendix(self) -> str:
        return _MAC_PROMPT_APPENDIX


_MAC_PROMPT_APPENDIX = """## Available tools (16 total)
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
