#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


API_BASE = "https://api.github.com"

C = type("C", (), {
    "CYN": "\033[36m",
    "R": "\033[0m",
})()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class GitHubTarget:
    owner: str
    repo: str

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"


def load_global_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_global_config(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def parse_repo_slug(value: str, default_owner: str = "") -> GitHubTarget:
    raw = str(value or "").strip().strip("/")
    if "/" in raw:
        owner, repo = raw.split("/", 1)
        return GitHubTarget(owner=owner, repo=repo)
    if not default_owner:
        raise ValueError("GitHub repo slug inválido; usa owner/repo o configura un owner por defecto.")
    return GitHubTarget(owner=default_owner, repo=raw)


def build_headers(token: str, *, accept: str = "application/vnd.github+json") -> Dict[str, str]:
    headers = {
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "omnisync",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def request_json(method: str, url: str, *, token: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=build_headers(token), method=method.upper())
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API {err.code}: {body}") from err
    except urllib.error.URLError as err:
        raise RuntimeError(f"GitHub network error: {err}") from err


def gh_cli_token() -> str:
    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=False, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def gh_device_auth() -> str:
    client_id = "Iv1.37586c2f99b0d11f"
    device_url = "https://github.com/login/device/code"
    token_url = "https://github.com/login/oauth/access_token"

    print("  Initiating GitHub Device Flow...")

    payload = json.dumps({
        "client_id": client_id,
        "scope": "repo",
    }).encode("utf-8")
    request = urllib.request.Request(
        device_url,
        data=payload,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            device_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub device flow not available: {body}. Use PAT instead.")
    except Exception as e:
        raise RuntimeError(f"Failed to start device auth: {e}")

    device_code = device_data.get("device_code", "")
    user_code = device_data.get("user_code", "")
    verification_uri = device_data.get("verification_uri", "https://github.com/login/device")
    interval = int(device_data.get("interval", 5))

    if not device_code or not user_code:
        raise RuntimeError("GitHub device flow not supported. Use PAT instead.")

    print()
    print(f"  1. Open this URL in your browser:")
    print(f"     {verification_uri}")
    print()
    print(f"  2. Enter this code:")
    print(f"     {C.CYN}{user_code}{C.R}")
    print()
    print("  3. Waiting for authorization...")
    print("     Press Ctrl+C to cancel")

    token_payload = json.dumps({
        "client_id": client_id,
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }).encode("utf-8")

    import time
    deadline = time.time() + 300

    while time.time() < deadline:
        token_request = urllib.request.Request(
            token_url,
            data=token_payload,
            headers={"Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(token_request, timeout=30) as resp:
                token_data = json.loads(resp.read().decode("utf-8"))
                access_token = token_data.get("access_token", "")
                if access_token:
                    print()
                    print("  [OK] GitHub authenticated!")
                    return access_token
                error = token_data.get("error", "")
                if error == "authorization_pending":
                    pass
                elif error == "slow_down":
                    interval += 5
                elif error == "access_denied":
                    raise RuntimeError("Access denied. Please try again.")
                else:
                    raise RuntimeError(f"Auth error: {error}")
        except Exception:
            pass
        time.sleep(interval)

    raise RuntimeError("Timeout waiting for GitHub authorization.")


def github_identity(token: str) -> Dict[str, Any]:
    return request_json("GET", f"{API_BASE}/user", token=token)


def ensure_private_repo(target: GitHubTarget, *, token: str) -> Dict[str, Any]:
    try:
        return request_json("GET", f"{API_BASE}/repos/{target.slug}", token=token)
    except RuntimeError as err:
        if "GitHub API 404" not in str(err):
            raise
    return request_json(
        "POST",
        f"{API_BASE}/user/repos",
        token=token,
        payload={
            "name": target.repo,
            "private": True,
            "description": "Omni Migrate Sync briefcases and restore artifacts",
            "auto_init": True,
        },
    )


def get_file_sha(target: GitHubTarget, path: str, *, token: str) -> str:
    try:
        payload = request_json("GET", f"{API_BASE}/repos/{target.slug}/contents/{urllib.parse.quote(path)}", token=token)
    except RuntimeError as err:
        if "GitHub API 404" in str(err):
            return ""
        raise
    return str(payload.get("sha") or "")


def put_file(target: GitHubTarget, path: str, content: str, *, token: str, message: str) -> Dict[str, Any]:
    sha = get_file_sha(target, path, token=token)
    payload: Dict[str, Any] = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    }
    if sha:
        payload["sha"] = sha
    return request_json(
        "PUT",
        f"{API_BASE}/repos/{target.slug}/contents/{urllib.parse.quote(path)}",
        token=token,
        payload=payload,
    )


def list_directory(target: GitHubTarget, path: str, *, token: str) -> List[Dict[str, Any]]:
    payload = request_json("GET", f"{API_BASE}/repos/{target.slug}/contents/{urllib.parse.quote(path)}", token=token)
    return payload if isinstance(payload, list) else []


def download_text(target: GitHubTarget, path: str, *, token: str) -> str:
    payload = request_json("GET", f"{API_BASE}/repos/{target.slug}/contents/{urllib.parse.quote(path)}", token=token)
    content = str(payload.get("content") or "")
    if not content:
        return ""
    return base64.b64decode(content.encode("ascii")).decode("utf-8")


def latest_briefcase_entry(entries: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    briefcases = [entry for entry in entries if str(entry.get("name", "")).endswith(".json")]
    if not briefcases:
        return None
    return sorted(briefcases, key=lambda item: str(item.get("name", "")), reverse=True)[0]
