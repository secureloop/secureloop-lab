#!/usr/bin/env python3
"""Read-only inventory of a self-hosted GitLab 17.x instance.

Produces clear and anonymized reports from a normalized JSON inventory.
"""
from __future__ import annotations

import argparse
import configparser
import copy
import html as html_lib
import json
import shutil
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
COMMIT_SLEEP_SECONDS = 0.02
MEMBER_SLEEP_SECONDS = 0.05
INACTIVE_DAYS_DEFAULT = 180
USER_AGENT = "secureloop-gitlab-inventory/0.1"

ACCESS_LEVEL_NAMES = {
    10: "Guest",
    20: "Reporter",
    30: "Developer",
    40: "Maintainer",
    50: "Owner",
}


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


# (short_name, access_level_field, legacy_boolean_field)
# Newer GitLab fields use *_access_level with values disabled/private/enabled/public;
# legacy fields are simple booleans. Prefer access_level when both exist.
PROJECT_FEATURES: list[tuple[str, str | None, str | None]] = [
    ("issues", "issues_access_level", "issues_enabled"),
    ("mrs", "merge_requests_access_level", "merge_requests_enabled"),
    ("ci", "builds_access_level", "jobs_enabled"),
    ("wiki", "wiki_access_level", "wiki_enabled"),
    ("snippets", "snippets_access_level", "snippets_enabled"),
    ("registry", "container_registry_access_level", "container_registry_enabled"),
    ("packages", None, "packages_enabled"),
    ("pages", "pages_access_level", None),
    ("lfs", None, "lfs_enabled"),
    ("service_desk", None, "service_desk_enabled"),
    ("releases", "releases_access_level", None),
    ("environments", "environments_access_level", None),
    ("feature_flags", "feature_flags_access_level", None),
    ("security", "security_and_compliance_access_level", None),
    ("analytics", "analytics_access_level", None),
    ("forking", "forking_access_level", None),
]


def is_feature_enabled(project: dict, access_field: str | None, legacy_field: str | None) -> bool | None:
    """Return True if enabled, False if disabled, None if the API didn't return either field."""
    if access_field and access_field in project:
        val = project.get(access_field)
        return val is not None and val != "disabled"
    if legacy_field and legacy_field in project:
        return bool(project.get(legacy_field))
    return None


def enabled_features(project: dict) -> list[str]:
    return [name for name, access_f, legacy_f in PROJECT_FEATURES
            if is_feature_enabled(project, access_f, legacy_f)]


_UNKNOWN_COMMIT = object()


def fetch_group_members(client: GitLabClient, group_id: int) -> list[dict]:
    """Fetch direct (non-inherited) members of a single group, ordered by access level descending."""
    try:
        return list(client.paginate(
            f"/groups/{group_id}/members",
            {"order_by": "access_level", "sort": "desc"},
        ))
    except HTTPError:
        return []


def fetch_all_group_members(client: GitLabClient, groups: list[dict]) -> dict[int, list[dict]]:
    """Return {group_id: [member, ...]} for every group. One paginated call per group."""
    result: dict[int, list[dict]] = {}
    for g in groups:
        gid = g.get("id")
        if gid is not None:
            result[gid] = fetch_group_members(client, gid)
            time.sleep(MEMBER_SLEEP_SECONDS)
    return result


def fetch_last_commit(client: GitLabClient, project_id: int) -> dict | None | object:
    """Fetch the most recent commit on the default branch.

    Returns the commit dict, None for an empty repo (404 / empty list), or the
    sentinel _UNKNOWN_COMMIT if the call failed for another reason.
    """
    try:
        data = client.get(f"/projects/{project_id}/repository/commits", {"per_page": 1})
    except HTTPError as e:
        if e.code == 404:
            return None
        return _UNKNOWN_COMMIT
    except URLError:
        return _UNKNOWN_COMMIT
    if not data:
        return None
    return data[0]


def classify_commit_state(
    project: dict,
    last_commit: dict | None | object,
    today: date,
    inactive_days: int,
) -> tuple[str, str | None, int | None]:
    """Return (state, last_commit_at, days_since_commit)."""
    if not project.get("default_branch"):
        return "empty", None, None
    if last_commit is _UNKNOWN_COMMIT:
        return "unknown", None, None
    if last_commit is None:
        return "empty", None, None
    committed_at = last_commit.get("committed_date")  # type: ignore[union-attr]
    days = days_since(committed_at, today)
    if days is None:
        return "unknown", committed_at, None
    state = "inactive" if days >= inactive_days else "active"
    return state, committed_at, days


def fetch_commit_info(
    client: GitLabClient,
    projects: list[dict],
    today: date,
    inactive_days: int,
) -> list[dict]:
    """Build per-project commit info, mirroring the projects list order."""
    info: list[dict] = []
    for p in projects:
        if not p.get("default_branch"):
            state, committed_at, days = classify_commit_state(p, None, today, inactive_days)
        else:
            commit = fetch_last_commit(client, p.get("id"))
            state, committed_at, days = classify_commit_state(p, commit, today, inactive_days)
            time.sleep(COMMIT_SLEEP_SECONDS)
        info.append({"state": state, "last_commit_at": committed_at, "days_since_commit": days})
    return info


def normalize_version(version: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": version.get("version"),
        "revision": version.get("revision"),
    }


def normalize_group(group: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": group.get("id"),
        "full_path": group.get("full_path"),
        "visibility": group.get("visibility"),
        "parent_id": group.get("parent_id"),
    }


def normalize_group_member(member: dict[str, Any]) -> dict[str, Any]:
    return {
        "username": member.get("username"),
        "name": member.get("name"),
        "email": member.get("email"),
        "access_level": member.get("access_level"),
    }


def normalize_project(project: dict[str, Any]) -> dict[str, Any]:
    namespace = project.get("namespace") or {}
    normalized = {
        "path_with_namespace": project.get("path_with_namespace"),
        "visibility": project.get("visibility"),
        "archived": project.get("archived"),
        "default_branch": project.get("default_branch"),
        "last_activity_at": project.get("last_activity_at"),
        "namespace": {"kind": namespace.get("kind")},
    }
    for _, access_field, legacy_field in PROJECT_FEATURES:
        if access_field and access_field in project:
            normalized[access_field] = project.get(access_field)
        if legacy_field and legacy_field in project:
            normalized[legacy_field] = project.get(legacy_field)
    return normalized


def normalize_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user.get("id"),
        "username": user.get("username"),
        "email": user.get("email"),
        "state": user.get("state"),
        "is_admin": user.get("is_admin"),
        "last_sign_in_at": user.get("last_sign_in_at"),
        "last_activity_on": user.get("last_activity_on"),
    }


def build_inventory(
    base_url: str,
    version: dict[str, Any],
    groups: list[dict[str, Any]],
    projects: list[dict[str, Any]],
    commit_info: list[dict[str, Any]],
    users: list[dict[str, Any]] | None,
    users_skip_reason: str | None,
    generated_at: datetime,
    inactive_days: int,
    group_members: dict[int, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Build the clear canonical inventory persisted as JSON.

    The inventory stores only fields consumed by the reports, not full GitLab
    API responses.
    """
    normalized_members: dict[str, list[dict[str, Any]]] = {}
    for group_id, members in group_members.items():
        normalized_members[str(group_id)] = [normalize_group_member(m) for m in members]

    return {
        "schema_version": 1,
        "privacy": "clear",
        "base_url": base_url,
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "inactive_days": inactive_days,
        "version": normalize_version(version),
        "groups": [normalize_group(g) for g in groups],
        "group_members": normalized_members,
        "projects": [normalize_project(p) for p in projects],
        "commit_info": [dict(info) for info in commit_info],
        "users": None if users is None else [normalize_user(u) for u in users],
        "users_skip_reason": users_skip_reason,
    }


def collect_inventory(
    client: GitLabClient,
    base_url: str,
    generated_at: datetime,
    inactive_days: int,
) -> dict[str, Any]:
    version = fetch_version(client)
    groups = fetch_groups(client)
    projects = fetch_projects(client)
    commit_info = fetch_commit_info(client, projects, generated_at.date(), inactive_days)
    users, users_skip_reason = fetch_users(client)
    group_members = fetch_all_group_members(client, groups)
    return build_inventory(
        base_url, version, groups, projects, commit_info,
        users, users_skip_reason, generated_at, inactive_days, group_members,
    )


def load_inventory_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        sys.exit(f"error: inventory JSON not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"error: invalid inventory JSON {path}: {e}")
    if not isinstance(data, dict):
        sys.exit(f"error: inventory JSON {path} must contain an object")
    return data


def write_inventory_json(inventory: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def inventory_generated_at(inventory: dict[str, Any]) -> datetime:
    value = inventory.get("generated_at")
    if isinstance(value, datetime):
        return value
    if not value:
        sys.exit("error: inventory is missing generated_at")
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        sys.exit(f"error: inventory has invalid generated_at: {value}")


def inventory_group_members_for_render(inventory: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = {}
    for key, members in (inventory.get("group_members") or {}).items():
        try:
            group_id = int(key)
        except (TypeError, ValueError):
            continue
        result[group_id] = list(members or [])
    return result


def render_from_inventory(fmt: str, inventory: dict[str, Any]) -> str:
    renderers = {"md": render_markdown, "html": render_html}
    generated_at = inventory_generated_at(inventory)
    return renderers[fmt](
        str(inventory.get("base_url") or ""),
        inventory.get("version") or {},
        inventory.get("groups") or [],
        inventory.get("projects") or [],
        inventory.get("commit_info") or [],
        inventory.get("users"),
        inventory.get("users_skip_reason"),
        generated_at,
        int(inventory.get("inactive_days") or INACTIVE_DAYS_DEFAULT),
        group_members=inventory_group_members_for_render(inventory),
    )


def _next_alias(mapping: dict[Any, int], key: Any) -> int:
    if key not in mapping:
        mapping[key] = len(mapping) + 1
    return mapping[key]


def anonymize_inventory(inventory: dict[str, Any]) -> dict[str, Any]:
    anonymized = copy.deepcopy(inventory)
    anonymized["privacy"] = "anonymized"
    anonymized["base_url"] = "https://gitlab.example.invalid"

    groups = inventory.get("groups") or []
    group_id_aliases: dict[Any, int] = {}
    for group in sorted(groups, key=lambda g: str(g.get("full_path") or "")):
        group_id = group.get("id")
        if group_id is not None:
            _next_alias(group_id_aliases, group_id)

    group_path_aliases: dict[str, str] = {}

    def anonymize_group_path(path: Any) -> Any:
        if not path:
            return path
        segments = str(path).split("/")
        aliases: list[str] = []
        for index in range(len(segments)):
            prefix = "/".join(segments[:index + 1])
            if prefix not in group_path_aliases:
                group_path_aliases[prefix] = f"group-{len(group_path_aliases) + 1:03d}"
            aliases.append(group_path_aliases[prefix])
        return "/".join(aliases)

    for group in sorted(groups, key=lambda g: str(g.get("full_path") or "")):
        anonymize_group_path(group.get("full_path"))

    project_path_aliases: dict[str, str] = {}

    def anonymize_project_path(path: Any) -> Any:
        if not path:
            return path
        text = str(path)
        segments = text.split("/")
        if text not in project_path_aliases:
            project_path_aliases[text] = f"project-{len(project_path_aliases) + 1:03d}"
        project_alias = project_path_aliases[text]
        if len(segments) == 1:
            return project_alias
        namespace_aliases = []
        for index in range(len(segments) - 1):
            namespace_aliases.append(anonymize_group_path("/".join(segments[:index + 1])))
        return "/".join(namespace_aliases + [project_alias])

    branch_aliases: dict[Any, int] = {}

    def anonymize_branch(branch: Any) -> Any:
        if not branch:
            return branch
        return f"branch-{_next_alias(branch_aliases, branch):03d}"

    anonymized_groups = anonymized.get("groups") or []
    for group in anonymized_groups:
        original_id = group.get("id")
        original_parent_id = group.get("parent_id")
        group["id"] = group_id_aliases.get(original_id) if original_id is not None else None
        group["parent_id"] = group_id_aliases.get(original_parent_id) if original_parent_id is not None else None
        group["full_path"] = anonymize_group_path(group.get("full_path"))

    user_aliases_by_key: dict[tuple[str, Any], int] = {}

    def register_user(user_id: Any, username: Any, email: Any) -> int:
        keys = []
        if user_id is not None:
            keys.append(("id", user_id))
        if username:
            keys.append(("username", username))
        if email:
            keys.append(("email", email))
        for key in keys:
            if key in user_aliases_by_key:
                alias = user_aliases_by_key[key]
                break
        else:
            alias = len(set(user_aliases_by_key.values())) + 1
        for key in keys:
            user_aliases_by_key[key] = alias
        return alias

    for user in sorted(inventory.get("users") or [], key=lambda u: str(u.get("username") or u.get("id") or "")):
        register_user(user.get("id"), user.get("username"), user.get("email"))
    for _, members in sorted((inventory.get("group_members") or {}).items(), key=lambda item: str(item[0])):
        for member in sorted(members or [], key=lambda m: str(m.get("username") or m.get("email") or "")):
            register_user(None, member.get("username"), member.get("email"))

    def anonymized_user_values(user_id: Any, username: Any, email: Any) -> tuple[int, str, str, str]:
        alias = register_user(user_id, username, email)
        return alias, f"user-{alias:03d}", f"User {alias:03d}", f"user-{alias:03d}@example.invalid"

    if anonymized.get("users") is not None:
        for user in anonymized.get("users") or []:
            alias, username, _, email = anonymized_user_values(
                user.get("id"), user.get("username"), user.get("email"),
            )
            user["id"] = alias
            user["username"] = username
            user["email"] = email

    anonymized_members: dict[str, list[dict[str, Any]]] = {}
    for original_group_id, members in (inventory.get("group_members") or {}).items():
        try:
            group_key: Any = int(original_group_id)
        except (TypeError, ValueError):
            group_key = original_group_id
        anonymized_group_id = group_id_aliases.get(group_key)
        if anonymized_group_id is None:
            continue
        anonymized_members[str(anonymized_group_id)] = []
        for member in members or []:
            _, username, name, email = anonymized_user_values(
                None, member.get("username"), member.get("email"),
            )
            anonymized_members[str(anonymized_group_id)].append({
                "username": username,
                "name": name,
                "email": email,
                "access_level": member.get("access_level"),
            })
    anonymized["group_members"] = anonymized_members

    for project in anonymized.get("projects") or []:
        project["path_with_namespace"] = anonymize_project_path(project.get("path_with_namespace"))
        project["default_branch"] = anonymize_branch(project.get("default_branch"))

    return anonymized


def render_markdown(
    base_url: str,
    version: dict[str, str],
    groups: list[dict],
    projects: list[dict],
    commit_info: list[dict],
    users: list[dict] | None,
    users_skip_reason: str | None,
    generated_at: datetime,
    inactive_days: int,
    group_members: dict[int, list[dict]] | None = None,
) -> str:
    if group_members is None:
        group_members = {}

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
        lines.append("| id | full_path | visibility | parent_id | members |")
        lines.append("|---|---|---|---|---|")
        for g in groups:
            gid = g.get("id")
            member_count = len(group_members.get(gid, [])) if gid is not None else ""
            lines.append(
                f"| {md_escape(gid)} "
                f"| {md_escape(g.get('full_path'))} "
                f"| {md_escape(g.get('visibility'))} "
                f"| {md_escape(g.get('parent_id'))} "
                f"| {md_escape(member_count)} |"
            )
    lines.append("")

    # Group Membership section
    lines.append("## Group Membership")
    lines.append("")
    lines.append(
        "_Only direct members are shown. Members inherited from parent groups are not listed._"
    )
    lines.append("")
    if not groups:
        lines.append("_No groups visible to this token._")
    else:
        for g in sorted(groups, key=lambda x: x.get("full_path", "")):
            gid = g.get("id")
            full_path = g.get("full_path", str(gid))
            members = group_members.get(gid, []) if gid is not None else []
            member_label = f"{len(members)} member{'s' if len(members) != 1 else ''}"
            lines.append(f"### {md_escape(full_path)} ({member_label})")
            lines.append("")
            if not members:
                lines.append("_No direct members._")
            else:
                lines.append("| username | name | email | role | access_level |")
                lines.append("|---|---|---|---|---|")
                for m in members:
                    level = m.get("access_level")
                    role = ACCESS_LEVEL_NAMES.get(level, str(level)) if level is not None else ""
                    lines.append(
                        f"| {md_escape(m.get('username'))} "
                        f"| {md_escape(m.get('name'))} "
                        f"| {md_escape(m.get('email'))} "
                        f"| {md_escape(role)} "
                        f"| {md_escape(level)} |"
                    )
            lines.append("")
    lines.append("")

    lines.append("## Projects")
    lines.append("")
    if not projects:
        lines.append("_No projects visible to this token._")
    else:
        per_project_features = [enabled_features(p) for p in projects]
        commit_states = [info["state"] for info in commit_info]
        commit_counts = {
            "empty": commit_states.count("empty"),
            "inactive": commit_states.count("inactive"),
            "active": commit_states.count("active"),
            "unknown": commit_states.count("unknown"),
        }
        lines.append("### Repository activity summary")
        lines.append("")
        lines.append(f"- empty (no commit ever): **{commit_counts['empty']}**")
        lines.append(f"- inactive (≥ {inactive_days} days since last commit): **{commit_counts['inactive']}**")
        lines.append(f"- active (< {inactive_days} days since last commit): **{commit_counts['active']}**")
        if commit_counts["unknown"]:
            lines.append(f"- unknown (commit lookup failed): **{commit_counts['unknown']}**")
        lines.append("")
        lines.append(
            "_`last_commit_at` is the most recent commit on the default branch, "
            "obtained via one extra API call per non-empty project. It differs from "
            "`last_activity_at`, which also covers issues, MRs, and comments._"
        )
        lines.append("")
        lines.append("| full_path | visibility | archived | default_branch | last_activity_at | last_commit_at | days_since_commit | commit_state | namespace_kind | features |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for p, feats, info in zip(projects, per_project_features, commit_info):
            ns = p.get("namespace") or {}
            lines.append(
                f"| {md_escape(p.get('path_with_namespace'))} "
                f"| {md_escape(p.get('visibility'))} "
                f"| {md_escape(p.get('archived'))} "
                f"| {md_escape(p.get('default_branch'))} "
                f"| {md_escape(p.get('last_activity_at'))} "
                f"| {md_escape(info.get('last_commit_at'))} "
                f"| {md_escape(info.get('days_since_commit'))} "
                f"| {md_escape(info.get('state'))} "
                f"| {md_escape(ns.get('kind'))} "
                f"| {md_escape(', '.join(feats))} |"
            )
        lines.append("")
        lines.append("### Feature enablement summary")
        lines.append("")
        lines.append(
            "_For each feature, how many projects have it enabled. `n/a` means the API "
            "response did not include that feature field for any project (e.g. feature "
            "not available on this instance)._"
        )
        lines.append("")
        total = len(projects)
        lines.append("| feature | enabled in |")
        lines.append("|---|---|")
        for name, access_f, legacy_f in PROJECT_FEATURES:
            states = [is_feature_enabled(p, access_f, legacy_f) for p in projects]
            known = [s for s in states if s is not None]
            if not known:
                cell = "n/a"
            else:
                enabled_count = sum(1 for s in known if s)
                cell = f"{enabled_count} / {len(known)}" + ("" if len(known) == total else f" (of {total})")
            lines.append(f"| {name} | {cell} |")
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
        lines.append("| id | username | email | state | is_admin | last_sign_in_at | last_activity_on | days_since_activity | interaction |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for u, label in zip(users, labels):
            d_activity = days_since(u.get("last_activity_on"), today)
            lines.append(
                f"| {md_escape(u.get('id'))} "
                f"| {md_escape(u.get('username'))} "
                f"| {md_escape(u.get('email'))} "
                f"| {md_escape(u.get('state'))} "
                f"| {md_escape(u.get('is_admin'))} "
                f"| {md_escape(u.get('last_sign_in_at'))} "
                f"| {md_escape(u.get('last_activity_on'))} "
                f"| {md_escape(d_activity)} "
                f"| {md_escape(label)} |"
            )
    lines.append("")

    return "\n".join(lines)


HTML_STYLE = """
:root {
  --fg: #1d1d1f; --bg: #fafafa; --muted: #666; --border: #ddd;
  --th-bg: #f4f4f4; --row-alt: #f7f7f7; --row-hover: #eef5ff;
}
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
       color: var(--fg); background: var(--bg); margin: 1.5em auto; max-width: 96%;
       padding: 0 1em; line-height: 1.4; }
h1 { border-bottom: 2px solid var(--border); padding-bottom: 0.3em; margin-top: 0; }
h2 { margin-top: 2em; border-bottom: 1px solid var(--border); padding-bottom: 0.2em; }
h3 { margin-top: 1.5em; }
ul.summary { list-style: none; padding: 0; }
ul.summary li { padding: 2px 0; }
.meta { color: var(--muted); font-size: 0.92em; margin-bottom: 1em; }
.footnote { color: var(--muted); font-size: 0.88em; font-style: italic; }
.skipped { color: var(--muted); font-style: italic; }
.table-wrap { overflow: auto; max-height: 75vh; border: 1px solid var(--border);
              border-radius: 4px; background: white; margin-bottom: 1em; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { padding: 5px 10px; text-align: left; border-bottom: 1px solid #eee;
         white-space: nowrap; vertical-align: top; }
thead th { position: sticky; top: 0; background: var(--th-bg);
           border-bottom: 2px solid var(--border); z-index: 1; }
tbody tr:nth-child(even) { background: var(--row-alt); }
tbody tr:hover { background: var(--row-hover); }
td.path, td.mono { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; }
td.numeric { text-align: right; font-variant-numeric: tabular-nums; }
.chip { display: inline-block; padding: 1px 7px; margin: 1px 2px; font-size: 11px;
        border-radius: 10px; background: #eaf3ff; color: #0969da;
        border: 1px solid #c4dcff; }
.badge { display: inline-block; padding: 1px 7px; font-size: 11px;
         border-radius: 3px; font-weight: 500; }
.v-public   { background: #fff0d6; color: #5a4100; }
.v-internal { background: #e6f3ff; color: #1457a8; }
.v-private  { background: #f3f3f3; color: #555; }
.archived-true  { background: #ffe1e1; color: #8a1f1f; }
.archived-false { color: #888; }
.bool-true  { color: #0e5a25; font-weight: 600; }
.bool-false { color: #888; }
.i-never       { background: #ffd9d9; color: #8a1f1f; }
.i-non-ui-only { background: #fff3c4; color: #5a4100; }
.i-ui-only     { background: #d6e9ff; color: #0a3d80; }
.i-active      { background: #d9f5e1; color: #0e5a25; }
.r-empty    { background: #f3d6ff; color: #5a1f7a; }
.r-inactive { background: #ffd9d9; color: #8a1f1f; }
.r-active   { background: #d9f5e1; color: #0e5a25; }
.r-unknown  { background: #f3f3f3; color: #555; }
.role-owner      { background: #ffe1e1; color: #8a1f1f; }
.role-maintainer { background: #fff3c4; color: #5a4100; }
.role-developer  { background: #d9f5e1; color: #0e5a25; }
.role-reporter   { background: #eaf3ff; color: #0969da; }
.role-guest      { background: #f3f3f3; color: #555; }
"""


def _h(value: Any) -> str:
    """HTML-escape a value, rendering None as empty string."""
    if value is None:
        return ""
    return html_lib.escape(str(value), quote=True)


def _visibility_badge(value: Any) -> str:
    if not value:
        return ""
    klass = {"public": "v-public", "internal": "v-internal", "private": "v-private"}.get(str(value), "v-private")
    return f'<span class="badge {klass}">{_h(value)}</span>'


def _bool_badge(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        s = "true" if value else "false"
    else:
        s = str(value).lower()
    klass = "bool-true" if s == "true" else "bool-false"
    return f'<span class="{klass}">{_h(s)}</span>'


def _archived_cell(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).lower()
    klass = "archived-true" if s == "true" else "archived-false"
    return f'<span class="badge {klass}">{_h(s)}</span>'


def _interaction_badge(label: str) -> str:
    klass = {
        "never": "i-never",
        "non-ui-only": "i-non-ui-only",
        "ui-only": "i-ui-only",
        "active": "i-active",
    }.get(label, "")
    return f'<span class="badge {klass}">{_h(label)}</span>'


def _commit_state_badge(state: str) -> str:
    klass = {
        "empty": "r-empty",
        "inactive": "r-inactive",
        "active": "r-active",
        "unknown": "r-unknown",
    }.get(state, "")
    return f'<span class="badge {klass}">{_h(state)}</span>'


def _role_badge(access_level: int | None) -> str:
    if access_level is None:
        return ""
    name = ACCESS_LEVEL_NAMES.get(access_level, str(access_level))
    klass = {
        50: "role-owner",
        40: "role-maintainer",
        30: "role-developer",
        20: "role-reporter",
        10: "role-guest",
    }.get(access_level, "role-guest")
    return f'<span class="badge {klass}">{_h(name)}</span>'


def _feature_chips(feats: list[str]) -> str:
    if not feats:
        return ""
    return "".join(f'<span class="chip">{_h(f)}</span>' for f in feats)


def render_html(
    base_url: str,
    version: dict[str, str],
    groups: list[dict],
    projects: list[dict],
    commit_info: list[dict],
    users: list[dict] | None,
    users_skip_reason: str | None,
    generated_at: datetime,
    inactive_days: int,
    group_members: dict[int, list[dict]] | None = None,
) -> str:
    if group_members is None:
        group_members = {}

    host = urlparse(base_url).hostname or base_url
    out: list[str] = []
    out.append("<!doctype html>")
    out.append('<html lang="en">')
    out.append("<head>")
    out.append('<meta charset="utf-8">')
    out.append(f"<title>GitLab Inventory — {_h(host)}</title>")
    out.append(f"<style>{HTML_STYLE}</style>")
    out.append("</head>")
    out.append("<body>")
    out.append(f"<h1>GitLab Inventory — {_h(host)}</h1>")
    out.append('<div class="meta">')
    out.append(f"<div><strong>Host:</strong> {_h(host)}</div>")
    out.append(
        f"<div><strong>GitLab version:</strong> {_h(version.get('version', 'unknown'))} "
        f"({_h(version.get('revision', ''))})</div>"
    )
    out.append(f"<div><strong>Generated:</strong> {_h(generated_at.isoformat(timespec='seconds'))}</div>")
    out.append("</div>")

    # Summary
    out.append("<h2>Summary</h2>")
    out.append('<ul class="summary">')
    out.append(f"<li>Groups: <strong>{len(groups)}</strong></li>")
    out.append(f"<li>Projects: <strong>{len(projects)}</strong></li>")
    if users is None:
        out.append(f'<li>Users: <span class="skipped">skipped — {_h(users_skip_reason)}</span></li>')
    else:
        out.append(f"<li>Users: <strong>{len(users)}</strong></li>")
    out.append("</ul>")

    # Groups
    out.append("<h2>Groups</h2>")
    if not groups:
        out.append('<p class="skipped">No groups visible to this token.</p>')
    else:
        out.append('<div class="table-wrap"><table>')
        out.append("<thead><tr><th>id</th><th>full_path</th><th>visibility</th><th>parent_id</th><th>members</th></tr></thead>")
        out.append("<tbody>")
        for g in groups:
            gid = g.get("id")
            member_count = len(group_members.get(gid, [])) if gid is not None else ""
            out.append(
                "<tr>"
                f'<td class="numeric">{_h(g.get("id"))}</td>'
                f'<td class="path">{_h(g.get("full_path"))}</td>'
                f"<td>{_visibility_badge(g.get('visibility'))}</td>"
                f'<td class="numeric">{_h(g.get("parent_id"))}</td>'
                f'<td class="numeric">{_h(member_count)}</td>'
                "</tr>"
            )
        out.append("</tbody></table></div>")

    # Group Membership
    out.append("<h2>Group Membership</h2>")
    out.append(
        '<p class="footnote">Only direct members are shown. '
        "Members inherited from parent groups are not listed.</p>"
    )
    if not groups:
        out.append('<p class="skipped">No groups visible to this token.</p>')
    else:
        for g in sorted(groups, key=lambda x: x.get("full_path", "")):
            gid = g.get("id")
            full_path = g.get("full_path", str(gid))
            members = group_members.get(gid, []) if gid is not None else []
            member_label = f"{len(members)} member{'s' if len(members) != 1 else ''}"
            out.append(f"<h3>{_h(full_path)} <small>({_h(member_label)})</small></h3>")
            if not members:
                out.append('<p class="skipped">No direct members.</p>')
            else:
                out.append('<div class="table-wrap"><table>')
                out.append(
                    "<thead><tr>"
                    "<th>username</th><th>name</th><th>email</th><th>role</th><th>access_level</th>"
                    "</tr></thead>"
                )
                out.append("<tbody>")
                for m in members:
                    level = m.get("access_level")
                    out.append(
                        "<tr>"
                        f'<td class="mono">{_h(m.get("username"))}</td>'
                        f"<td>{_h(m.get('name'))}</td>"
                        f'<td class="mono">{_h(m.get("email"))}</td>'
                        f"<td>{_role_badge(level)}</td>"
                        f'<td class="numeric">{_h(level)}</td>'
                        "</tr>"
                    )
                out.append("</tbody></table></div>")

    # Projects
    out.append("<h2>Projects</h2>")
    if not projects:
        out.append('<p class="skipped">No projects visible to this token.</p>')
    else:
        per_project_features = [enabled_features(p) for p in projects]
        commit_states = [info["state"] for info in commit_info]
        commit_counts = {k: commit_states.count(k) for k in ("empty", "inactive", "active", "unknown")}

        out.append("<h3>Repository activity summary</h3>")
        out.append('<ul class="summary">')
        out.append(f'<li>{_commit_state_badge("empty")} (no commit ever): <strong>{commit_counts["empty"]}</strong></li>')
        out.append(f'<li>{_commit_state_badge("inactive")} (≥ {inactive_days} days since last commit): <strong>{commit_counts["inactive"]}</strong></li>')
        out.append(f'<li>{_commit_state_badge("active")} (&lt; {inactive_days} days since last commit): <strong>{commit_counts["active"]}</strong></li>')
        if commit_counts["unknown"]:
            out.append(f'<li>{_commit_state_badge("unknown")} (commit lookup failed): <strong>{commit_counts["unknown"]}</strong></li>')
        out.append("</ul>")
        out.append(
            '<p class="footnote"><code>last_commit_at</code> is the most recent '
            "commit on the default branch (one extra API call per non-empty "
            "project). <code>last_activity_at</code> also covers issues, MRs, "
            "and comments.</p>"
        )

        out.append('<div class="table-wrap"><table>')
        out.append(
            "<thead><tr>"
            "<th>full_path</th><th>visibility</th><th>archived</th>"
            "<th>default_branch</th><th>last_activity_at</th>"
            "<th>last_commit_at</th><th>days_since_commit</th><th>commit_state</th>"
            "<th>namespace_kind</th><th>features</th>"
            "</tr></thead>"
        )
        out.append("<tbody>")
        for p, feats, info in zip(projects, per_project_features, commit_info):
            ns = p.get("namespace") or {}
            out.append(
                "<tr>"
                f'<td class="path">{_h(p.get("path_with_namespace"))}</td>'
                f"<td>{_visibility_badge(p.get('visibility'))}</td>"
                f"<td>{_archived_cell(p.get('archived'))}</td>"
                f'<td class="mono">{_h(p.get("default_branch"))}</td>'
                f'<td class="mono">{_h(p.get("last_activity_at"))}</td>'
                f'<td class="mono">{_h(info.get("last_commit_at"))}</td>'
                f'<td class="numeric">{_h(info.get("days_since_commit"))}</td>'
                f'<td>{_commit_state_badge(info.get("state", ""))}</td>'
                f"<td>{_h(ns.get('kind'))}</td>"
                f"<td>{_feature_chips(feats)}</td>"
                "</tr>"
            )
        out.append("</tbody></table></div>")

        # Feature enablement summary
        out.append("<h3>Feature enablement summary</h3>")
        out.append(
            '<p class="footnote">For each feature, how many projects have it '
            "enabled. <code>n/a</code> means the API response did not include "
            "that feature field for any project (e.g. feature not available on "
            "this instance).</p>"
        )
        total = len(projects)
        out.append('<div class="table-wrap"><table>')
        out.append("<thead><tr><th>feature</th><th>enabled in</th></tr></thead>")
        out.append("<tbody>")
        for name, access_f, legacy_f in PROJECT_FEATURES:
            states = [is_feature_enabled(p, access_f, legacy_f) for p in projects]
            known = [s for s in states if s is not None]
            if not known:
                cell = '<span class="skipped">n/a</span>'
            else:
                enabled_count = sum(1 for s in known if s)
                suffix = "" if len(known) == total else f' <span class="footnote">(of {total})</span>'
                cell = f"<strong>{enabled_count}</strong> / {len(known)}{suffix}"
            out.append(f'<tr><td><span class="chip">{_h(name)}</span></td><td>{cell}</td></tr>')
        out.append("</tbody></table></div>")

    # Users
    out.append("<h2>Users</h2>")
    if users is None:
        out.append(f'<p class="skipped">Skipped: {_h(users_skip_reason)}.</p>')
    elif not users:
        out.append('<p class="skipped">No users returned.</p>')
    else:
        today = generated_at.date()
        labels = [classify_interaction(u) for u in users]
        counts = {k: labels.count(k) for k in ("never", "non-ui-only", "ui-only", "active")}

        out.append("<h3>User activity summary</h3>")
        out.append('<ul class="summary">')
        out.append(f'<li>{_interaction_badge("never")} interacted: <strong>{counts["never"]}</strong></li>')
        out.append(f'<li>{_interaction_badge("non-ui-only")} (git/API only): <strong>{counts["non-ui-only"]}</strong></li>')
        out.append(f'<li>{_interaction_badge("ui-only")} (no activity day): <strong>{counts["ui-only"]}</strong></li>')
        out.append(f'<li>{_interaction_badge("active")} (UI + activity): <strong>{counts["active"]}</strong></li>')
        out.append("</ul>")
        out.append(
            '<p class="footnote"><code>last_activity_on</code> covers UI, API, '
            "and git over HTTP/SSH (date-only granularity); "
            "<code>last_sign_in_at</code> is UI sign-ins only.</p>"
        )

        out.append('<div class="table-wrap"><table>')
        out.append(
            "<thead><tr>"
            "<th>id</th><th>username</th><th>email</th><th>state</th><th>is_admin</th>"
            "<th>last_sign_in_at</th><th>last_activity_on</th>"
            "<th>days_since_activity</th><th>interaction</th>"
            "</tr></thead>"
        )
        out.append("<tbody>")
        for u, label in zip(users, labels):
            d_activity = days_since(u.get("last_activity_on"), today)
            out.append(
                "<tr>"
                f'<td class="numeric">{_h(u.get("id"))}</td>'
                f'<td class="mono">{_h(u.get("username"))}</td>'
                f'<td class="mono">{_h(u.get("email"))}</td>'
                f"<td>{_h(u.get('state'))}</td>"
                f"<td>{_bool_badge(u.get('is_admin'))}</td>"
                f'<td class="mono">{_h(u.get("last_sign_in_at"))}</td>'
                f'<td class="mono">{_h(u.get("last_activity_on"))}</td>'
                f'<td class="numeric">{_h(d_activity)}</td>'
                f"<td>{_interaction_badge(label)}</td>"
                "</tr>"
            )
        out.append("</tbody></table></div>")

    out.append("</body></html>")
    return "\n".join(out)


def default_output_base(base_url: str, generated_at: datetime) -> Path:
    """Return the report path *without* extension; callers append .md / .html."""
    host = (urlparse(base_url).hostname or "gitlab").replace(":", "_")
    stamp = generated_at.strftime("%Y%m%d-%H%M%S")
    reports_dir = Path(__file__).resolve().parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir / f"gitlab-inventory-{host}-{stamp}"


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
    # Sample the members endpoint using the first available group.
    groups = fetch_groups(client)
    if groups:
        first_gid = groups[0].get("id")
        try:
            client.get(f"/groups/{first_gid}/members", {"per_page": 1})
            print("members endpoint: accessible")
        except HTTPError as e:
            print(f"members endpoint: HTTP {e.code}")
    else:
        print("members endpoint: no groups to test against")
    return 0


def requested_report_variants(privacy: str) -> list[str]:
    return ["clear", "anonymized"] if privacy == "both" else [privacy]


def resolve_report_paths(
    user_path: Path | None,
    formats: list[str],
    variants: list[str],
    base_url: str,
    generated_at: datetime,
) -> dict[tuple[str, str], Path]:
    """Return {(variant, format): path} for each requested report artifact."""
    if user_path and len(formats) == 1 and len(variants) == 1:
        return {(variants[0], formats[0]): user_path}

    base = user_path.with_suffix("") if user_path else default_output_base(base_url, generated_at)
    ext = {"md": ".md", "html": ".html"}
    paths: dict[tuple[str, str], Path] = {}
    for variant in variants:
        variant_base = base if variant == "clear" else base.with_name(f"{base.name}-anonymized")
        for fmt in formats:
            paths[(variant, fmt)] = variant_base.with_suffix(ext[fmt])
    return paths


def resolve_inventory_json_path(user_path: Path | None, base_url: str, generated_at: datetime) -> Path:
    base = user_path.with_suffix("") if user_path else default_output_base(base_url, generated_at)
    return base.with_suffix(".json")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Read-only inventory of a self-hosted GitLab instance.")
    default_config = Path(__file__).resolve().parent / "config.ini"
    parser.add_argument("--config", type=Path, default=default_config, help="Path to config.ini")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output path/base. Multiple report artifacts replace the extension with .md/.html and add suffixes.")
    parser.add_argument("--format", choices=["md", "html", "both"], default="both",
                        help="Report output format(s). Default: both.")
    parser.add_argument("--privacy", choices=["clear", "anonymized", "both"], default="both",
                        help="Report privacy variant(s). Default: both.")
    parser.add_argument("--from-json", type=Path, default=None,
                        help="Render reports from an existing clear inventory JSON instead of calling GitLab.")
    parser.add_argument("--inactive-days", type=int, default=INACTIVE_DAYS_DEFAULT,
                        help=f"Days without a commit on the default branch before a repo is "
                             f"flagged 'inactive' (default: {INACTIVE_DAYS_DEFAULT}).")
    parser.add_argument("--dry-run", action="store_true", help="Only check reachability and users-endpoint access")
    args = parser.parse_args(argv)

    if args.from_json and args.dry_run:
        parser.error("--dry-run cannot be used with --from-json")

    inventory_json_path: Path | None = None
    if args.from_json:
        inventory = load_inventory_json(args.from_json)
        generated_at = inventory_generated_at(inventory)
    else:
        url, token, verify_tls = load_config(args.config)
        client = GitLabClient(url, token, verify_tls)
        if args.dry_run:
            return run_dry_run(client, url)

        generated_at = datetime.now(timezone.utc)
        inventory = collect_inventory(client, url, generated_at, args.inactive_days)
        inventory_json_path = resolve_inventory_json_path(args.output, url, generated_at)
        write_inventory_json(inventory, inventory_json_path)

    base_url = str(inventory.get("base_url") or "gitlab")
    formats = ["md", "html"] if args.format == "both" else [args.format]
    variants = requested_report_variants(args.privacy)
    report_inventories = {"clear": inventory}
    if "anonymized" in variants:
        report_inventories["anonymized"] = anonymize_inventory(inventory)
    paths = resolve_report_paths(args.output, formats, variants, base_url, generated_at)

    for (variant, fmt), path in paths.items():
        content = render_from_inventory(fmt, report_inventories[variant])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    # Maintain stable copies at reports/latest*.{md,html,json} for serving over HTTP.
    # Only when output goes to the default reports/ directory; if the user
    # passed --output we honour that path exactly and don't write anywhere else.
    latest_paths: dict[str, Path] = {}
    if args.output is None:
        if inventory_json_path is not None:
            latest_json = inventory_json_path.with_name("latest.json")
            shutil.copyfile(inventory_json_path, latest_json)
            latest_paths["json"] = latest_json
        for (variant, fmt), path in paths.items():
            suffix = "" if variant == "clear" else "-anonymized"
            latest = path.with_name(f"latest{suffix}.{fmt}")
            shutil.copyfile(path, latest)
            latest_label = fmt if variant == "clear" else f"{variant} {fmt}"
            latest_paths[latest_label] = latest

    groups = inventory.get("groups") or []
    projects = inventory.get("projects") or []
    users = inventory.get("users")
    group_members = inventory.get("group_members") or {}
    version = inventory.get("version") or {}
    host = urlparse(base_url).hostname or base_url
    user_summary = "users skipped" if users is None else f"{len(users)} users"
    total_memberships = sum(len(v) for v in group_members.values())
    print(
        f"{host} ({version.get('version', 'unknown')}): "
        f"{len(groups)} groups ({total_memberships} direct memberships), "
        f"{len(projects)} projects, {user_summary}"
    )
    if inventory_json_path is not None:
        print(f"inventory (json): {inventory_json_path}")
    elif args.from_json:
        print(f"inventory source (json): {args.from_json}")
    for (variant, fmt), path in paths.items():
        label = fmt if variant == "clear" else f"{variant} {fmt}"
        print(f"report ({label}): {path}")
    for label, path in latest_paths.items():
        print(f"latest ({label}): {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
