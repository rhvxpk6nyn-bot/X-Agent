# X-Agent

X-Agent is a desktop AI agent with a web UI, memory, tools, and platform-specific desktop actions.

## Downloads

- macOS version: use the project root directly.
- Windows version: see `windows/README.md`.

The macOS and Windows desktop toolkits are separated in code:

- macOS tools: `core/platform/mac/`
- Windows tools: `core/platform/win/`

## macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn web.backend.server:app --host 127.0.0.1 --port 9531
```

Open:

```text
http://127.0.0.1:9531/
```

macOS supports Apple Music control and Chrome automation through AppleScript.

## Windows

Use the separate Windows entry:

```text
windows/README.md
windows/start-web.bat
```

Windows supports the web UI, chat, memory, file tools, shell commands, app launching, system info, browser navigation, and screenshots.

Windows browser DOM actions such as click/type/run_js are not enabled yet.
