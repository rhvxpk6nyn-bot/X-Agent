# X-Agent Windows Version

This folder is the Windows entry for X-Agent.

The Windows version is separated from the macOS desktop toolkit. It uses:

```text
core/platform/win/
```

## Requirements

- Windows 10 or Windows 11
- Python 3.12 or newer
- Git

## Download

```powershell
git clone https://github.com/rhvxpk6nyn-bot/X-Agent.git
cd X-Agent
```

## Start The Web UI

Double-click:

```text
windows\start-web.bat
```

Or run in PowerShell:

```powershell
.\windows\start-web.bat
```

Then open:

```text
http://127.0.0.1:9531/
```

## Windows Features

Available:

- Web UI chat
- Memory
- File read/write/edit tools
- Shell commands through Windows
- Open Windows apps by common names
- System info
- Browser navigation
- Screenshot capture

Limited:

- Browser click/type/run_js actions are not enabled on Windows yet.
- Apple Music control is macOS-only.

## Common App Names

Examples:

```text
Chrome
Edge
Notepad
Calculator
Explorer
Terminal
PowerShell
Settings
VS Code
PyCharm
WeChat
```
