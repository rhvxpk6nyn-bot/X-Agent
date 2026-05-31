"""Abstract base class for platform toolkits."""

from abc import ABC, abstractmethod


class BasePlatformToolkit(ABC):
    """Every platform must implement this interface.

    Cross-platform tools (shell, read, write, edit, grep, glob, etc.)
    live in core/tools.py and do NOT go through this class.
    """

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Human-readable platform name: 'macOS' or 'Windows'."""
        ...

    @property
    @abstractmethod
    def tool_names(self) -> list[str]:
        """Names of platform-specific tools provided by this toolkit."""
        ...

    @abstractmethod
    def open_app(self, app: str, wait: bool = False) -> str:
        """Open a desktop application by common name or path."""
        ...

    @abstractmethod
    def browser(self, action: str, url: str = "",
                selector: str = "", text: str = "", js: str = "") -> str:
        """Control a web browser (navigate, click, type, extract, screenshot)."""
        ...

    @abstractmethod
    def sysinfo(self) -> str:
        """Gather system info: OS, CPU, RAM, disk, dev tools."""
        ...

    def music(self, action: str = "play", song: str = "",
              artist: str = "", album: str = "", playlist: str = "") -> str:
        """Control music playback. Returns error if unavailable on this platform."""
        return "[error] Music control not available on this platform"

    def volume(self, action: str = "get", level: int | None = None, step: int = 10) -> str:
        """Control system output volume. Returns error if unavailable."""
        return "[error] Volume control not available on this platform"

    @abstractmethod
    def get_system_prompt_appendix(self) -> str:
        """Return platform-specific sections for the system prompt.

        This is appended to the base system prompt and should cover:
        - Platform identity (OS name)
        - Tool priority specific to this platform
        - Platform-only tool documentation
        """
        ...
