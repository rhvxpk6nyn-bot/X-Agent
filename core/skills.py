"""Skill loader — discovers SKILL.md files, installs from ClawHub."""

import subprocess
import json
from pathlib import Path

import yaml

from core.config import AGENT_HOME

SKILLS_DIR = AGENT_HOME / "skills"
INSTALLED_DIR = SKILLS_DIR / "installed"
MARKETPLACE_DIR = SKILLS_DIR / "marketplace"
# Legacy: skills previously installed under the project directory
LEGACY_INSTALLED_DIR = AGENT_HOME.parent / "agent" / "skills" / "installed"


class Skill:
    def __init__(self, name: str, description: str, path: Path,
                 version: str = "", homepage: str = "",
                 metadata: dict | None = None):
        self.name = name
        self.description = description
        self.path = path
        self.version = version
        self.homepage = homepage
        self.metadata = metadata or {}
        self._body: str | None = None

    @property
    def body(self) -> str:
        if self._body is None:
            skill_md = self.path / "SKILL.md"
            if skill_md.exists():
                text = skill_md.read_text()
                if text.startswith("---"):
                    parts = text.split("---", 2)
                    self._body = parts[2].strip() if len(parts) >= 3 else text
                else:
                    self._body = text
            else:
                self._body = ""
        return self._body

    @classmethod
    def from_dir(cls, directory: Path) -> "Skill | None":
        skill_md = directory / "SKILL.md"
        if not skill_md.exists():
            return None
        text = skill_md.read_text()
        frontmatter = {}
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                frontmatter = yaml.safe_load(parts[1]) or {}

        return cls(
            name=frontmatter.get("name", directory.name),
            description=frontmatter.get("description", ""),
            path=directory,
            version=frontmatter.get("version", ""),
            homepage=frontmatter.get("homepage", ""),
            metadata=frontmatter.get("metadata", {}),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "homepage": self.homepage,
        }


class SkillRegistry:
    def __init__(self):
        self._skills: dict[str, Skill] = {}
        INSTALLED_DIR.mkdir(parents=True, exist_ok=True)
        MARKETPLACE_DIR.mkdir(parents=True, exist_ok=True)
        self._discover()

    def _discover(self):
        self._skills.clear()
        for base in [INSTALLED_DIR, LEGACY_INSTALLED_DIR]:
            if not base.exists():
                continue
            for d in base.iterdir():
                if d.is_dir():
                    skill = Skill.from_dir(d)
                    if skill:
                        self._skills[skill.name] = skill

    @property
    def skills(self) -> dict[str, Skill]:
        return self._skills

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def match(self, user_message: str) -> Skill | None:
        msg_lower = user_message.lower()
        for skill in self._skills.values():
            desc_lower = skill.description.lower()
            words = set(desc_lower.split()) - {"the", "a", "an", "is", "when", "for", "use", "this", "skill", "should", "be", "used", "to", "and", "or", "in", "on", "at", "by", "with"}
            matches = sum(1 for w in words if w in msg_lower)
            if matches >= 2:
                return skill
        return None

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Search ClawHub for skills."""
        try:
            result = subprocess.run(
                ["clawhub", "search", query, "--limit", str(limit)],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                return []
            # clawhub search outputs: "slug  name  (score)"
            results = []
            for line in result.stdout.strip().split("\n"):
                if line.startswith("- Searching") or not line.strip():
                    continue
                line = line.strip()
                if not line:
                    continue
                parts = line.rsplit("(", 1)
                score = ""
                if len(parts) == 2 and parts[1].endswith(")"):
                    score = parts[1][:-1]
                    line = parts[0].strip()
                # Split remaining into slug and name
                tokens = line.split(None, 1)
                if len(tokens) >= 2:
                    results.append({
                        "slug": tokens[0],
                        "name": tokens[1],
                        "score": score,
                    })
                elif len(tokens) == 1:
                    results.append({
                        "slug": tokens[0],
                        "name": tokens[0],
                        "score": score,
                    })
            return results
        except Exception:
            return []

    def install(self, slug: str, force: bool = False) -> tuple[bool, str]:
        """Install a skill from ClawHub by slug."""
        try:
            cmd = ["clawhub", "install", slug, "--dir", str(INSTALLED_DIR)]
            if force:
                cmd.append("--force")
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                self._discover()
                return True, result.stdout.strip()
            return False, result.stderr.strip() or result.stdout.strip()
        except FileNotFoundError:
            return False, "clawhub CLI not found. Install it: npm i -g @anthropic/clawhub"
        except Exception as e:
            return False, str(e)

    def uninstall(self, name: str) -> bool:
        skill = self._skills.get(name)
        if skill:
            import shutil
            shutil.rmtree(skill.path)
            del self._skills[name]
            return True
        return False


skills = SkillRegistry()
