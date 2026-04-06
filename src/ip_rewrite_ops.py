#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass, field
import difflib
import fnmatch
import ipaddress
import os
import socket
import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterable, Mapping, Sequence


DEFAULT_ALLOWED_GLOBS = [
    "**/.env",
    "**/.env.*",
    "**/.gitignore",
    "**/.dockerignore",
    "**/.npmrc",
    "**/.tool-versions",
    "**/*.env",
    "**/*.json",
    "**/*.jsonc",
    "**/*.yml",
    "**/*.yaml",
    "**/*.toml",
    "**/*.ini",
    "**/*.cfg",
    "**/*.conf",
    "**/*.js",
    "**/*.cjs",
    "**/*.mjs",
    "**/*.ts",
    "**/*.tsx",
    "**/*.jsx",
    "**/*.py",
    "**/*.sh",
    "**/*.ps1",
    "**/*.md",
    "**/*.txt",
    "**/Dockerfile",
    "**/Caddyfile",
    "**/docker-compose.yml",
    "**/docker-compose.yaml",
    "**/compose.yml",
    "**/compose.yaml",
    "**/*.service",
    "**/*.timer",
]

DEFAULT_ALLOWED_FILENAMES = {
    "Caddyfile",
    "Dockerfile",
    ".gitignore",
    ".dockerignore",
    ".npmrc",
    ".tool-versions",
}

DEFAULT_ALLOWED_SUFFIXES = {
    ".json",
    ".jsonc",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".js",
    ".cjs",
    ".mjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".py",
    ".sh",
    ".ps1",
    ".md",
    ".txt",
    ".service",
    ".timer",
}

DEFAULT_EXCLUDED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".cache",
    ".pytest_cache",
    ".mypy_cache",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "tmp",
    "output",
}

TEXT_ENCODING = "utf-8"


@dataclass(slots=True)
class HostIdentity:
    public_ip: str | None
    private_ip: str | None
    hostname: str
    fqdn: str
    ip_candidates: list[str] = field(default_factory=list)
    source: str = "local"


@dataclass(slots=True)
class FileRewrite:
    path: Path
    before: str
    after: str
    replacements: dict[str, int]

    @property
    def changed(self) -> bool:
        return self.before != self.after

    def preview(self, context_lines: int = 2) -> str:
        before_lines = self.before.splitlines()
        after_lines = self.after.splitlines()
        diff = difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=str(self.path),
            tofile=str(self.path),
            lineterm="",
            n=context_lines,
        )
        return "\n".join(diff)


@dataclass(slots=True)
class RewritePlan:
    root: Path
    replacements: dict[str, str]
    files: list[FileRewrite]
    files_scanned: int
    files_allowed: int

    @property
    def changed_files(self) -> int:
        return sum(1 for item in self.files if item.changed)

    @property
    def total_replacements(self) -> int:
        return sum(sum(item.replacements.values()) for item in self.files)


@dataclass(slots=True)
class RewriteResult:
    applied: list[Path]
    skipped: list[Path]


def _env_value(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _is_ip(value: str | None) -> bool:
    if not value:
        return False
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _local_ip_candidates() -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    try:
        host = socket.gethostname()
        _, _, addresses = socket.gethostbyname_ex(host)
        for address in addresses:
            try:
                parsed = ipaddress.ip_address(address)
            except ValueError:
                continue
            if parsed.is_loopback:
                continue
            if address not in seen:
                seen.add(address)
                candidates.append(address)
    except OSError:
        pass

    try:
        result = subprocess.run(
            ["hostname", "-I"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            for token in result.stdout.split():
                try:
                    parsed = ipaddress.ip_address(token)
                except ValueError:
                    continue
                if parsed.is_loopback:
                    continue
                if token not in seen:
                    seen.add(token)
                    candidates.append(token)
    except Exception:
        pass

    return candidates


def detect_host_identity() -> HostIdentity:
    hostname = _env_value("OMNI_HOSTNAME") or socket.gethostname()
    fqdn = _env_value("OMNI_FQDN") or socket.getfqdn()
    public_ip = _env_value("OMNI_PUBLIC_IP")
    private_ip = _env_value("OMNI_PRIVATE_IP")

    candidates = _local_ip_candidates()
    if not private_ip:
        private_ip = candidates[0] if candidates else None
    if not public_ip:
        public_ip = _env_value("OMNI_PUBLIC_IPV4") or None

    source = "env" if any(_env_value(name) for name in ("OMNI_HOSTNAME", "OMNI_FQDN", "OMNI_PUBLIC_IP", "OMNI_PRIVATE_IP")) else "local"
    return HostIdentity(
        public_ip=public_ip if _is_ip(public_ip) else None,
        private_ip=private_ip if _is_ip(private_ip) else None,
        hostname=hostname or "unknown",
        fqdn=fqdn or hostname or "unknown",
        ip_candidates=[candidate for candidate in candidates if _is_ip(candidate)],
        source=source,
    )


def normalize_root(root: str | Path) -> Path:
    return Path(root).expanduser().resolve()


def is_allowed_rewrite_file(
    path: Path,
    allowed_globs: Sequence[str] | None = None,
    *,
    relative_to: Path | None = None,
) -> bool:
    globs = list(allowed_globs or DEFAULT_ALLOWED_GLOBS)
    name = path.name
    if name.startswith(".env"):
        return True
    if name in DEFAULT_ALLOWED_FILENAMES:
        return True
    if path.suffix.lower() in DEFAULT_ALLOWED_SUFFIXES:
        return True
    rel = path.as_posix().lstrip("/")
    if relative_to is not None:
        try:
            rel = path.relative_to(relative_to).as_posix()
        except ValueError:
            rel = path.as_posix().lstrip("/")
    if any(fnmatch.fnmatch(rel, pattern) for pattern in globs):
        return True
    return False


def is_excluded_dir(path: Path, *, relative_to: Path | None = None) -> bool:
    parts = path.parts
    if relative_to is not None:
        try:
            parts = path.relative_to(relative_to).parts
        except ValueError:
            parts = path.parts
    return any(part in DEFAULT_EXCLUDED_DIR_NAMES for part in parts)


def iter_allowed_files(root: str | Path, allowed_globs: Sequence[str] | None = None) -> Iterable[Path]:
    root_path = normalize_root(root)
    if root_path.is_file():
        if root_path.is_symlink() or is_excluded_dir(root_path, relative_to=root_path.parent):
            return
        if is_allowed_rewrite_file(root_path, allowed_globs, relative_to=root_path.parent):
            yield root_path
        return

    for candidate in root_path.rglob("*"):
        if not candidate.is_file():
            continue
        if candidate.is_symlink():
            continue
        if is_excluded_dir(candidate, relative_to=root_path):
            continue
        if is_allowed_rewrite_file(candidate, allowed_globs, relative_to=root_path):
            yield candidate


def read_text_file(path: Path) -> str | None:
    try:
        return path.read_text(encoding=TEXT_ENCODING)
    except UnicodeDecodeError:
        return None
    except OSError:
        return None


def build_file_rewrite(path: Path, replacements: Mapping[str, str]) -> FileRewrite | None:
    original = read_text_file(path)
    if original is None:
        return None

    updated = original
    counts: dict[str, int] = {}
    for old, new in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        if not old:
            continue
        count = updated.count(old)
        if count:
            updated = updated.replace(old, new)
            counts[old] = count

    if not counts:
        return None
    return FileRewrite(path=path, before=original, after=updated, replacements=counts)


def build_rewrite_plan(
    root: str | Path,
    replacements: Mapping[str, str],
    *,
    allowed_globs: Sequence[str] | None = None,
) -> RewritePlan:
    root_path = normalize_root(root)
    file_rewrites: list[FileRewrite] = []
    scanned = 0
    allowed = 0
    for file_path in iter_allowed_files(root_path, allowed_globs=allowed_globs):
        scanned += 1
        file_rewrite = build_file_rewrite(file_path, replacements)
        if file_rewrite is None:
            continue
        allowed += 1
        file_rewrites.append(file_rewrite)
    return RewritePlan(
        root=root_path,
        replacements=dict(replacements),
        files=file_rewrites,
        files_scanned=scanned,
        files_allowed=allowed,
    )


def preview_rewrite_plan(plan: RewritePlan, *, context_lines: int = 2, max_files: int = 20) -> str:
    lines: list[str] = []
    lines.append(f"root: {plan.root}")
    lines.append(f"scanned: {plan.files_scanned}")
    lines.append(f"matched: {plan.changed_files}")
    lines.append(f"replacements: {plan.total_replacements}")
    lines.append("")

    for item in plan.files[:max_files]:
        lines.append(f"FILE {item.path}")
        for old, count in sorted(item.replacements.items()):
            new = plan.replacements.get(old, "")
            lines.append(f"  {old} -> {new} ({count})")
        preview = item.preview(context_lines=context_lines).strip()
        if preview:
            lines.append(preview)
        lines.append("")

    if len(plan.files) > max_files:
        lines.append(f"... {len(plan.files) - max_files} more files")
    return "\n".join(lines).rstrip()


def apply_rewrite_plan(plan: RewritePlan) -> RewriteResult:
    applied: list[Path] = []
    skipped: list[Path] = []
    for item in plan.files:
        if not item.changed:
            skipped.append(item.path)
            continue
        item.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding=TEXT_ENCODING, delete=False, dir=str(item.path.parent)) as tmp:
            tmp.write(item.after)
            tmp_path = Path(tmp.name)
        tmp_path.replace(item.path)
        applied.append(item.path)
    return RewriteResult(applied=applied, skipped=skipped)


def collect_references(root: str | Path, needles: Sequence[str], *, allowed_globs: Sequence[str] | None = None) -> RewritePlan:
    replacements = {needle: needle for needle in needles}
    plan = build_rewrite_plan(root, replacements, allowed_globs=allowed_globs)
    return plan


def detect_and_plan(
    root: str | Path,
    *,
    target_public_ip: str | None = None,
    target_private_ip: str | None = None,
    target_hostname: str | None = None,
    allowed_globs: Sequence[str] | None = None,
) -> tuple[HostIdentity, RewritePlan]:
    identity = detect_host_identity()
    replacements: dict[str, str] = {}

    if identity.public_ip and target_public_ip and identity.public_ip != target_public_ip:
        replacements[identity.public_ip] = target_public_ip
    if identity.private_ip and target_private_ip and identity.private_ip != target_private_ip:
        replacements[identity.private_ip] = target_private_ip
    if identity.hostname and target_hostname and identity.hostname != target_hostname:
        replacements[identity.hostname] = target_hostname
    if identity.fqdn and target_hostname and identity.fqdn != target_hostname:
        replacements[identity.fqdn] = target_hostname

    plan = build_rewrite_plan(root, replacements, allowed_globs=allowed_globs)
    return identity, plan
