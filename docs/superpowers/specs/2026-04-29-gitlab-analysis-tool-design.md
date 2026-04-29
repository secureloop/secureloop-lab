# GitLab Analysis Tool — Design

**Date:** 2026-04-29
**Status:** Draft for review

## Purpose

Provide a read-only inventory script for a self-hosted GitLab 17.x instance. Given a personal access token and an endpoint, produce a Markdown report listing groups, projects, and (when permissions allow) users. This is the first iteration; later iterations may add pipelines, runners, CI variables, hooks, or audit data.

## Scope

In scope:
- Authenticated read-only calls to GitLab REST API v4
- Inventory of: instance version, groups, projects, users
- Markdown report output
- Graceful handling when the token lacks admin scope (e.g. `/users` returns 403)

Out of scope (deferred):
- Pipelines, jobs, runners
- CI/CD variables, deploy keys, hooks
- SSH keys, audit events, SAML/SCIM
- Per-project member listings
- Writing/modifying any GitLab state

## Layout

New top-level directory at the repo root:

```
gitlab-analysis-tool/
├── README.md
├── gitlab-inventory.py
├── config.ini.example
├── config.ini            # gitignored
├── .gitignore
└── reports/
    └── .gitkeep
```

`.gitignore` inside the folder excludes `config.ini` and `reports/*` (keeping `.gitkeep`).

## Configuration

INI format, parsed with stdlib `configparser`.

```ini
[gitlab]
url = https://gitlab.example.com
token = glpat-xxxxxxxxxxxx
verify_tls = true
```

- `url` — base URL of the GitLab instance (no trailing `/api/v4`).
- `token` — personal access token with at least `read_api` scope. Admin token required for the users section.
- `verify_tls` — boolean; defaults to `true`. Allows disabling cert verification for lab/self-signed setups.

CLI flag `--config <path>` overrides the default `config.ini` next to the script.

## Runtime / Dependencies

- Python 3.9+
- Standard library only: `urllib.request`, `urllib.parse`, `json`, `configparser`, `argparse`, `ssl`, `time`, `pathlib`, `datetime`, `sys`.

## API Endpoints Used

All `GET`, all under `<url>/api/v4`:

| Endpoint | Purpose |
|---|---|
| `/version` | Sanity check + record GitLab version |
| `/groups?per_page=100` | All groups visible to the token |
| `/projects?per_page=100&statistics=true` | All projects visible to the token (includes archived) |
| `/users?per_page=100` | All users (admin only; degrades gracefully on 403) |

Auth header: `PRIVATE-TOKEN: <token>`.

## Pagination

GitLab returns `X-Next-Page` and `X-Total-Pages` headers. The script loops while `X-Next-Page` is non-empty, requesting `?page=N&per_page=100`. A 50ms sleep between page requests keeps the load polite.

## Error Handling

- **401 Unauthorized** on `/version`: print clear message ("token rejected — check value and `read_api` scope") and exit non-zero.
- **403 Forbidden** on `/users`: log "users endpoint requires admin — skipped" and record the skip in the report; continue.
- **403 Forbidden** elsewhere: log endpoint and continue (the section will be empty with a note).
- **429 Too Many Requests**: honor `Retry-After`; one retry, then fail.
- **TLS / connection errors**: print the error and exit non-zero. No retry.
- **Other 4xx/5xx**: print status and body excerpt, exit non-zero.

## Report

Markdown file written to `gitlab-analysis-tool/reports/gitlab-inventory-<host>-<YYYYMMDD-HHMMSS>.md`. Path overridable via `--output <path>`.

Sections:

1. **Header** — host, GitLab version, generation timestamp (ISO 8601 UTC), token scope notes.
2. **Summary** — counts of groups / projects / users (or "users skipped").
3. **Groups** — table: `id`, `full_path`, `visibility`, `parent_id`.
4. **Projects** — table: `full_path`, `visibility`, `archived`, `default_branch`, `last_activity_at`, `namespace_kind` (group/user).
5. **Users** — table: `id`, `username`, `state`, `is_admin`, `last_sign_in_at`. Or a single-line note "skipped: admin token required".

A one-line summary is also printed to stdout, e.g.:
`gitlab.example.com (17.8.1): 7 groups, 42 projects, users skipped (no admin)`.

## CLI

```
gitlab-inventory.py [--config PATH] [--output PATH] [--dry-run]
```

- `--dry-run` only calls `/version` and reports reachability + whether the users endpoint is accessible (probes with `per_page=1`).

## Testing / Verification

Manual verification steps in the README:
1. Copy `config.ini.example` → `config.ini`, fill in URL + token.
2. Run `python3 gitlab-inventory.py --dry-run` — confirms reachability.
3. Run `python3 gitlab-inventory.py` — produces a Markdown file under `reports/`.

No automated tests in this first cut; the script's surface is small and entirely external-API-dependent.

## Security Notes

- `config.ini` is gitignored — real tokens never enter the repo.
- Only `read_api` scope required for groups/projects. Admin scope is optional and only needed for the users section.
- TLS verification is on by default; disabling it requires explicit `verify_tls = false` in the config.

## Future Iterations (not implemented now)

- Pipelines & runner inventory (`/projects/:id/pipelines`, `/runners/all`).
- Per-project members (`/projects/:id/members/all`).
- CI/CD variables and protected branches.
- JSON sidecar output for diffing across runs.
- Optional caching of paginated responses to disk.

## Follow-ups implemented

- **2026-04-29** — User activity / dormancy reporting added to the users
  section: `last_activity_on`, `days_since_activity`, and an `interaction`
  classification (`never` / `non-ui-only` / `ui-only` / `active`), plus a
  summary block. No new endpoints; the fields are already returned by the
  admin `/users` listing.
- **2026-04-29** — Per-project feature enablement reporting added to the
  projects section: a `features` column listing enabled features per project
  (issues, mrs, ci, wiki, snippets, registry, packages, pages, lfs,
  service_desk, releases, environments, feature_flags, security, analytics,
  forking) and a "Feature enablement summary" table totalling each feature
  across all projects. Driven by existing `/projects` payload — no new API
  calls. Handles both new `*_access_level` fields and legacy `*_enabled`
  booleans; reports `n/a` for features the GitLab version doesn't return.
- **2026-04-29** — HTML output added alongside Markdown. New `--format`
  flag (`md` / `html` / `both`, default `both`). HTML is a single
  self-contained file (inline CSS, no JS, no external resources) with
  sticky table headers, zebra striping, colour-coded badges for visibility
  / archived / `is_admin` / interaction labels, and chips for enabled
  project features — much more scannable than the wide Markdown tables.
  No additional API calls or dependencies; rendering is driven from the
  same in-memory data as the Markdown path.
- **2026-04-29** — Stable report path + HTTP server. Every default-output
  run also writes `reports/latest.{md,html}` (a copy of the just-written
  timestamped file) so external consumers have a fixed URL to point at.
  Skipped when `--output` is supplied to avoid surprise writes. Added a
  thin `serve.py` wrapper that runs the inventory and serves `reports/`
  over HTTP via `http.server.ThreadingHTTPServer`; defaults to
  `0.0.0.0:8765` because the tool is intended for use inside an isolated
  lab network. `--no-run`, `--bind`, `--port`, `--config` flags supported.
