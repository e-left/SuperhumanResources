"""Collect source text; interpretation is left to Gemini. Never execute repo code."""

import os
from pathlib import Path
import re
import subprocess


class AnalysisError(Exception):
    pass


SKIP_DIRS = {
    "node_modules", "vendor", "dist", "build", "coverage", "__pycache__",
    "venv", "target", "Pods", "data",
}
SKIP_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "uv.lock", "Cargo.lock", "Gemfile.lock", "composer.lock",
}
TEXT_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json",
    ".md", ".sql", ".prisma", ".yaml", ".yml", ".toml", ".go",
    ".rs", ".java", ".kt", ".swift", ".rb", ".php", ".cs", ".cpp",
    ".c", ".h", ".html", ".css", ".graphql", ".proto", ".sh",
}
TEXT_FILENAMES = {"Dockerfile", "Makefile", "requirements.txt", "go.mod"}
MAX_FILE_BYTES = 80_000
MAX_TOTAL_BYTES = 600_000
MAX_FILES = 150


def github_url(value: str) -> str:
    if not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?", value):
        raise AnalysisError("use a public repository URL: https://github.com/owner/repo")
    parts = value.rstrip("/").split("/")[-2:]
    if any(part in {".", "..", ".git"} for part in parts):
        raise AnalysisError("invalid GitHub repository URL")
    return value.rstrip("/")


def clone(repo_url: str, destination: Path) -> None:
    url = github_url(repo_url)
    # No interactive credentials, local hooks, LFS downloads, or submodules.
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1"}
    try:
        subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "-c", "credential.helper=",
             "clone", "--depth=1", "--single-branch", "--", url, str(destination)],
            env=env, capture_output=True, check=True, timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise AnalysisError("GitHub clone timed out after 60 seconds") from exc
    except subprocess.CalledProcessError as exc:
        raise AnalysisError("GitHub clone failed; check the URL, public access, and network") from exc
    except FileNotFoundError as exc:
        raise AnalysisError("git is required to clone a GitHub repository") from exc


def project_root(root: Path, subdir: str) -> Path:
    root = root.resolve()
    target = (root / subdir).resolve()
    if not target.is_relative_to(root) or not target.is_dir():
        raise AnalysisError("subdir must be an existing directory inside the repository")
    return target


def collect_files(root: Path) -> dict:
    root = root.resolve()
    if not root.is_dir():
        raise AnalysisError("repository path must be an existing directory")
    candidates = []
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS
                         and not (Path(directory) / d).is_symlink())
        for name in sorted(files):
            path = Path(directory) / name
            if (name.startswith(".") or name in SKIP_FILES or path.is_symlink()
                    or name.endswith((".min.js", ".d.ts", ".generated.ts", ".generated.py"))):
                continue
            if path.suffix.lower() not in TEXT_SUFFIXES and name not in TEXT_FILENAMES:
                continue
            if any(word in name.lower() for word in ("secret", "credential", "private_key")):
                continue
            candidates.append(path)

    # Manifests and README first; the remaining source files have stable ordering.
    candidates.sort(key=lambda p: (p.name.lower() not in {
        "readme.md", "package.json", "pyproject.toml", "requirements.txt", "go.mod",
    }, p.relative_to(root).as_posix()))
    selected = []
    skipped = []
    total = 0
    for path in candidates:
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        if size > MAX_FILE_BYTES or total + size > MAX_TOTAL_BYTES or len(selected) >= MAX_FILES:
            skipped.append(relative)
            continue
        with path.open("rb") as file:
            raw = file.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES or total + len(raw) > MAX_TOTAL_BYTES:
            skipped.append(relative)
            continue
        if b"\x00" in raw:
            continue
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            skipped.append(relative)
            continue
        selected.append({"path": relative, "content": content})
        total += len(raw)
    if not selected:
        raise AnalysisError("no supported source or documentation files found")
    return {"files": selected, "omitted_files": skipped}
