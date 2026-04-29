#!/usr/bin/env python3
"""Read-only inventory of a self-hosted GitLab 17.x instance.

Produces a Markdown report listing groups, projects, and (admin only) users.
"""
from __future__ import annotations

import argparse
import configparser
import html as html_lib
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


def render_markdown(
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
        per_project_features = [enabled_features(p) for p in projects]
        lines.append("| full_path | visibility | archived | default_branch | last_activity_at | namespace_kind | features |")
        lines.append("|---|---|---|---|---|---|---|")
        for p, feats in zip(projects, per_project_features):
            ns = p.get("namespace") or {}
            lines.append(
                f"| {md_escape(p.get('path_with_namespace'))} "
                f"| {md_escape(p.get('visibility'))} "
                f"| {md_escape(p.get('archived'))} "
                f"| {md_escape(p.get('default_branch'))} "
                f"| {md_escape(p.get('last_activity_at'))} "
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


def _feature_chips(feats: list[str]) -> str:
    if not feats:
        return ""
    return "".join(f'<span class="chip">{_h(f)}</span>' for f in feats)


def render_html(
    base_url: str,
    version: dict[str, str],
    groups: list[dict],
    projects: list[dict],
    users: list[dict] | None,
    users_skip_reason: str | None,
    generated_at: datetime,
) -> str:
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
        out.append("<thead><tr><th>id</th><th>full_path</th><th>visibility</th><th>parent_id</th></tr></thead>")
        out.append("<tbody>")
        for g in groups:
            out.append(
                "<tr>"
                f'<td class="numeric">{_h(g.get("id"))}</td>'
                f'<td class="path">{_h(g.get("full_path"))}</td>'
                f"<td>{_visibility_badge(g.get('visibility'))}</td>"
                f'<td class="numeric">{_h(g.get("parent_id"))}</td>'
                "</tr>"
            )
        out.append("</tbody></table></div>")

    # Projects
    out.append("<h2>Projects</h2>")
    if not projects:
        out.append('<p class="skipped">No projects visible to this token.</p>')
    else:
        per_project_features = [enabled_features(p) for p in projects]
        out.append('<div class="table-wrap"><table>')
        out.append(
            "<thead><tr>"
            "<th>full_path</th><th>visibility</th><th>archived</th>"
            "<th>default_branch</th><th>last_activity_at</th>"
            "<th>namespace_kind</th><th>features</th>"
            "</tr></thead>"
        )
        out.append("<tbody>")
        for p, feats in zip(projects, per_project_features):
            ns = p.get("namespace") or {}
            out.append(
                "<tr>"
                f'<td class="path">{_h(p.get("path_with_namespace"))}</td>'
                f"<td>{_visibility_badge(p.get('visibility'))}</td>"
                f"<td>{_archived_cell(p.get('archived'))}</td>"
                f'<td class="mono">{_h(p.get("default_branch"))}</td>'
                f'<td class="mono">{_h(p.get("last_activity_at"))}</td>'
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
            "<th>id</th><th>username</th><th>state</th><th>is_admin</th>"
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
    return 0


def resolve_output_paths(
    user_path: Path | None,
    formats: list[str],
    base_url: str,
    generated_at: datetime,
) -> dict[str, Path]:
    """Return {format: path} for each requested format.

    With a user-supplied --output and a single format, write to that exact path.
    With multiple formats, treat --output as a base path (extension stripped) and
    append .md / .html. Without --output, use the default reports/ pattern.
    """
    base = user_path.with_suffix("") if user_path else default_output_base(base_url, generated_at)
    if user_path and len(formats) == 1:
        return {formats[0]: user_path}
    ext = {"md": ".md", "html": ".html"}
    return {fmt: base.with_suffix(ext[fmt]) for fmt in formats}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Read-only inventory of a self-hosted GitLab instance.")
    default_config = Path(__file__).resolve().parent / "config.ini"
    parser.add_argument("--config", type=Path, default=default_config, help="Path to config.ini")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output path. With --format both, the extension is replaced with .md and .html.")
    parser.add_argument("--format", choices=["md", "html", "both"], default="both",
                        help="Output format(s). Default: both.")
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

    formats = ["md", "html"] if args.format == "both" else [args.format]
    paths = resolve_output_paths(args.output, formats, url, generated_at)

    renderers = {"md": render_markdown, "html": render_html}
    for fmt, path in paths.items():
        content = renderers[fmt](url, version, groups, projects, users, users_skip_reason, generated_at)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    host = urlparse(url).hostname or url
    user_summary = "users skipped" if users is None else f"{len(users)} users"
    print(f"{host} ({version.get('version', 'unknown')}): {len(groups)} groups, {len(projects)} projects, {user_summary}")
    for fmt, path in paths.items():
        print(f"report ({fmt}): {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
