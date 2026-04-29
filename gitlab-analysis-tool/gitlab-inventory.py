#!/usr/bin/env python3
"""Read-only inventory of a self-hosted GitLab 17.x instance.

Produces a Markdown report listing groups, projects, and (admin only) users.
"""
from __future__ import annotations

import argparse
import configparser
import json
import ssl
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

PER_PAGE = 100
PAGE_SLEEP_SECONDS = 0.05
USER_AGENT = "secureloop-gitlab-inventory/0.1"


class GitLabClient:
    def __init__(self, base_url: str, token: str, verify_tls: bool) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.ssl_context: ssl.SSLContext | None = None
        if not verify_tls:
            self.ssl_context = ssl.create_default_context()
            self.ssl_context.check_hostname = False
            self.ssl_context.verify_mode = ssl.CERT_NONE

    def _request(self, path: str, params: dict[str, Any] | None = None) -> tuple[Any, dict[str, str]]:
        url = f"{self.base_url}/api/v4{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        req = Request(url, headers={
            "PRIVATE-TOKEN": self.token,
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        })
        try:
            with urlopen(req, context=self.ssl_context, timeout=30) as resp:
                body = resp.read()
                headers = {k: v for k, v in resp.headers.items()}
                return json.loads(body) if body else None, headers
        except HTTPError as e:
            # Retry once on 429.
            if e.code == 429:
                retry_after = int(e.headers.get("Retry-After", "2"))
                time.sleep(retry_after)
                with urlopen(req, context=self.ssl_context, timeout=30) as resp:
                    body = resp.read()
                    headers = {k: v for k, v in resp.headers.items()}
                    return json.loads(body) if body else None, headers
            raise

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        data, _ = self._request(path, params)
        return data

    def paginate(self, path: str, params: dict[str, Any] | None = None) -> Iterable[dict]:
        page = 1
        params = dict(params or {})
        params["per_page"] = PER_PAGE
        while True:
            params["page"] = page
            data, headers = self._request(path, params)
            if not data:
                return
            for item in data:
                yield item
            next_page = headers.get("X-Next-Page", "").strip()
            if not next_page:
                return
            page = int(next_page)
            time.sleep(PAGE_SLEEP_SECONDS)


def load_config(path: Path) -> tuple[str, str, bool]:
    if not path.is_file():
        sys.exit(f"error: config file not found: {path}")
    parser = configparser.ConfigParser()
    parser.read(path)
    if "gitlab" not in parser:
        sys.exit(f"error: config file {path} is missing [gitlab] section")
    section = parser["gitlab"]
    url = section.get("url", "").strip()
    token = section.get("token", "").strip()
    verify_tls = section.getboolean("verify_tls", True)
    if not url or not token:
        sys.exit("error: config must set both 'url' and 'token' under [gitlab]")
    if token == "glpat-REPLACE-ME":
        sys.exit("error: replace the placeholder token in config.ini")
    return url, token, verify_tls


def fetch_version(client: GitLabClient) -> dict[str, str]:
    try:
        return client.get("/version") or {}
    except HTTPError as e:
        if e.code == 401:
            sys.exit("error: token rejected (401) — check value and 'read_api' scope")
        sys.exit(f"error: GET /version failed: HTTP {e.code} — {e.read().decode('utf-8', 'replace')[:200]}")
    except URLError as e:
        sys.exit(f"error: cannot reach GitLab: {e.reason}")


def fetch_groups(client: GitLabClient) -> list[dict]:
    return list(client.paginate("/groups", {"all_available": "true", "order_by": "path", "sort": "asc"}))


def fetch_projects(client: GitLabClient) -> list[dict]:
    return list(client.paginate("/projects", {"statistics": "true", "order_by": "path", "sort": "asc"}))


def fetch_users(client: GitLabClient) -> tuple[list[dict] | None, str | None]:
    """Returns (users, skip_reason). users is None when skipped."""
    try:
        return list(client.paginate("/users", {"order_by": "id", "sort": "asc"})), None
    except HTTPError as e:
        if e.code in (401, 403):
            return None, f"admin token required (HTTP {e.code})"
        return None, f"unexpected HTTP {e.code}"


def md_escape(value: Any) -> str:
    if value is None:
        return ""
    s = str(value)
    return s.replace("|", "\\|").replace("\n", " ")


def parse_date(value: Any) -> date | None:
    """Accept an ISO date or datetime string; return only the date component."""
    if not value:
        return None
    s = str(value)
    # Trim trailing 'Z' so fromisoformat works on stdlib < 3.11.
    if s.endswith("Z"):
        s = s[:-1]
    try:
        if "T" in s:
            return datetime.fromisoformat(s).date()
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def days_since(value: Any, today: date) -> int | None:
    parsed = parse_date(value)
    if parsed is None:
        return None
    return (today - parsed).days


def classify_interaction(user: dict) -> str:
    """Classify a user by which activity fields are populated.

    last_activity_on is updated by UI, API, and git over HTTP/SSH.
    last_sign_in_at is updated only by UI sign-ins.
    """
    activity = parse_date(user.get("last_activity_on"))
    sign_in = parse_date(user.get("last_sign_in_at"))
    if activity is None and sign_in is None:
        return "never"
    if activity is not None and sign_in is None:
        return "non-ui-only"
    if activity is None and sign_in is not None:
        return "ui-only"
    return "active"


def render_report(
    base_url: str,
    version: dict[str, str],
    groups: list[dict],
    projects: list[dict],
    users: list[dict] | None,
    users_skip_reason: str | None,
    generated_at: datetime,
) -> str:
    host = urlparse(base_url).hostname or base_url
    lines: list[str] = []
    lines.append(f"# GitLab Inventory — {host}")
    lines.append("")
    lines.append(f"- **Host:** {host}")
    lines.append(f"- **GitLab version:** {version.get('version', 'unknown')} ({version.get('revision', '')})")
    lines.append(f"- **Generated:** {generated_at.isoformat(timespec='seconds')}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Groups: **{len(groups)}**")
    lines.append(f"- Projects: **{len(projects)}**")
    if users is None:
        lines.append(f"- Users: _skipped — {users_skip_reason}_")
    else:
        lines.append(f"- Users: **{len(users)}**")
    lines.append("")

    lines.append("## Groups")
    lines.append("")
    if not groups:
        lines.append("_No groups visible to this token._")
    else:
        lines.append("| id | full_path | visibility | parent_id |")
        lines.append("|---|---|---|---|")
        for g in groups:
            lines.append(
                f"| {md_escape(g.get('id'))} "
                f"| {md_escape(g.get('full_path'))} "
                f"| {md_escape(g.get('visibility'))} "
                f"| {md_escape(g.get('parent_id'))} |"
            )
    lines.append("")

    lines.append("## Projects")
    lines.append("")
    if not projects:
        lines.append("_No projects visible to this token._")
    else:
        lines.append("| full_path | visibility | archived | default_branch | last_activity_at | namespace_kind |")
        lines.append("|---|---|---|---|---|---|")
        for p in projects:
            ns = p.get("namespace") or {}
            lines.append(
                f"| {md_escape(p.get('path_with_namespace'))} "
                f"| {md_escape(p.get('visibility'))} "
                f"| {md_escape(p.get('archived'))} "
                f"| {md_escape(p.get('default_branch'))} "
                f"| {md_escape(p.get('last_activity_at'))} "
                f"| {md_escape(ns.get('kind'))} |"
            )
    lines.append("")

    lines.append("## Users")
    lines.append("")
    if users is None:
        lines.append(f"_Skipped: {users_skip_reason}._")
    elif not users:
        lines.append("_No users returned._")
    else:
        today = generated_at.date()
        labels = [classify_interaction(u) for u in users]
        counts = {
            "never": labels.count("never"),
            "non-ui-only": labels.count("non-ui-only"),
            "ui-only": labels.count("ui-only"),
            "active": labels.count("active"),
        }
        lines.append("### User activity summary")
        lines.append("")
        lines.append(f"- never interacted: **{counts['never']}**")
        lines.append(f"- non-UI only (git/API): **{counts['non-ui-only']}**")
        lines.append(f"- UI-only (no activity day): **{counts['ui-only']}**")
        lines.append(f"- active (UI + activity): **{counts['active']}**")
        lines.append("")
        lines.append(
            "_`last_activity_on` covers UI, API, and git over HTTP/SSH (date-only "
            "granularity); `last_sign_in_at` is UI sign-ins only._"
        )
        lines.append("")
        lines.append("| id | username | state | is_admin | last_sign_in_at | last_activity_on | days_since_activity | interaction |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for u, label in zip(users, labels):
            d_activity = days_since(u.get("last_activity_on"), today)
            lines.append(
                f"| {md_escape(u.get('id'))} "
                f"| {md_escape(u.get('username'))} "
                f"| {md_escape(u.get('state'))} "
                f"| {md_escape(u.get('is_admin'))} "
                f"| {md_escape(u.get('last_sign_in_at'))} "
                f"| {md_escape(u.get('last_activity_on'))} "
                f"| {md_escape(d_activity)} "
                f"| {md_escape(label)} |"
            )
    lines.append("")

    return "\n".join(lines)


def default_output_path(base_url: str, generated_at: datetime) -> Path:
    host = (urlparse(base_url).hostname or "gitlab").replace(":", "_")
    stamp = generated_at.strftime("%Y%m%d-%H%M%S")
    reports_dir = Path(__file__).resolve().parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir / f"gitlab-inventory-{host}-{stamp}.md"


def run_dry_run(client: GitLabClient, base_url: str) -> int:
    version = fetch_version(client)
    print(f"reachable: {base_url} (GitLab {version.get('version', 'unknown')})")
    try:
        client.get("/users", {"per_page": 1})
        print("users endpoint: accessible (admin token)")
    except HTTPError as e:
        if e.code in (401, 403):
            print(f"users endpoint: NOT accessible (HTTP {e.code}) — non-admin token")
        else:
            print(f"users endpoint: unexpected HTTP {e.code}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Read-only inventory of a self-hosted GitLab instance.")
    default_config = Path(__file__).resolve().parent / "config.ini"
    parser.add_argument("--config", type=Path, default=default_config, help="Path to config.ini")
    parser.add_argument("--output", type=Path, default=None, help="Path to write the Markdown report")
    parser.add_argument("--dry-run", action="store_true", help="Only check reachability and users-endpoint access")
    args = parser.parse_args(argv)

    url, token, verify_tls = load_config(args.config)
    client = GitLabClient(url, token, verify_tls)

    if args.dry_run:
        return run_dry_run(client, url)

    generated_at = datetime.now(timezone.utc)
    version = fetch_version(client)
    groups = fetch_groups(client)
    projects = fetch_projects(client)
    users, users_skip_reason = fetch_users(client)

    report = render_report(url, version, groups, projects, users, users_skip_reason, generated_at)
    output_path = args.output or default_output_path(url, generated_at)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")

    host = urlparse(url).hostname or url
    user_summary = "users skipped" if users is None else f"{len(users)} users"
    print(f"{host} ({version.get('version', 'unknown')}): {len(groups)} groups, {len(projects)} projects, {user_summary}")
    print(f"report: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
