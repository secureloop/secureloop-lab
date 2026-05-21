# GitLab Analysis Tool

Read-only inventory of a self-hosted GitLab 17.x instance. Produces a clear
JSON inventory plus clear and anonymized Markdown/HTML reports listing groups,
projects, and (if the token has admin scope) users.

## Requirements

- Python 3.9+ (standard library only — no `pip install` needed)
- A GitLab personal access token with `read_api` scope. For the users section,
  an admin token is required; without it the script skips that section and
  continues.

## Setup

```bash
cp config.ini.example config.ini
# edit config.ini and set url + token
```

`config.ini` is gitignored so the token does not enter the repo.

## Usage

Reachability check:

```bash
python3 gitlab-inventory.py --dry-run
```

Full inventory (writes clear JSON plus clear and anonymized Markdown/HTML by default):

```bash
python3 gitlab-inventory.py
```

Pick a single format:

```bash
python3 gitlab-inventory.py --format html
python3 gitlab-inventory.py --format md
```

Pick a privacy variant:

```bash
python3 gitlab-inventory.py --privacy clear       # clear reports only
python3 gitlab-inventory.py --privacy anonymized  # anonymized reports only
python3 gitlab-inventory.py --privacy both        # default
```

Render reports from an existing clear inventory JSON without calling GitLab:

```bash
python3 gitlab-inventory.py --from-json reports/latest.json --privacy both
```

Custom config or output path:

```bash
python3 gitlab-inventory.py --config /path/to/config.ini --output /tmp/report.html --format html --privacy clear
# With multiple report artifacts, --output is treated as a base; the extension is replaced:
python3 gitlab-inventory.py --output /tmp/report   # writes /tmp/report.json, clear reports, and anonymized reports
```

Tune the inactivity threshold (days without a commit on the default branch
before a repo is flagged `inactive`):

```bash
python3 gitlab-inventory.py --inactive-days 90   # default: 180
```

Reports are written to timestamped files under `reports/` by default:

- `gitlab-inventory-<host>-<YYYYMMDD-HHMMSS>.json` — clear canonical inventory
- `gitlab-inventory-<host>-<YYYYMMDD-HHMMSS>.{md,html}` — clear reports
- `gitlab-inventory-<host>-<YYYYMMDD-HHMMSS>-anonymized.{md,html}` — anonymized reports

The `reports/` directory is gitignored. The HTML files are fully self-contained
(inline CSS, no JS, no external resources) so you can open them straight from
your file system. They use sticky table headers and zebra rows so the wide
projects/users tables stay readable when scrolling.

For convenience, every default live inventory run also writes stable copies:
`reports/latest.json`, `reports/latest.md`, `reports/latest.html`,
`reports/latest-anonymized.md`, and `reports/latest-anonymized.html`.
This only happens when `--output` is not supplied; with an explicit `--output`
only the requested output base is written. When rendering with `--from-json`,
the JSON source is reused and only report files are regenerated.

## Serving reports over HTTP

`serve.py` runs the inventory and starts a tiny HTTP server on
`reports/`, so you can open the latest report from a browser at a
stable URL.

```bash
python3 serve.py                 # runs the inventory, then serves on 0.0.0.0:8765
python3 serve.py --no-run        # skip the inventory; just serve what's already in reports/
python3 serve.py --port 9000     # custom port
python3 serve.py --bind 127.0.0.1 # localhost only
python3 serve.py --config /path/to/config.ini
```

Open `http://<host>:8765/latest.html` (or `latest-anonymized.html`,
`latest.md`, `latest-anonymized.md`, `latest.json`).

The server binds `0.0.0.0` by default because this tool is intended for
use inside an isolated lab network. The clear reports and `latest.json`
include user data and admin metadata — do **not** expose the port on the
public internet. If that ever becomes a concern, pass `--bind 127.0.0.1`
or put it behind a real reverse proxy with auth.

## Inventory JSON and anonymization

The JSON inventory is the clear canonical source for report generation. It is
not an anonymized artifact and should be handled like the clear reports.

The JSON inventory is normalized: it contains only the fields consumed by the
reports plus derived values such as commit state. It does not persist full
GitLab API responses.

The anonymized reports are derived from an in-memory copy of the clear inventory.
They replace host, group paths, project paths, usernames, names, emails, user IDs,
group IDs, parent group IDs, group-member references, and branch names with
deterministic placeholders such as `group-001`, `project-001`, `user-001`, and
`branch-001`. Operational metadata such as visibility, feature enablement,
roles, activity states, and timestamps is preserved so the report remains useful.

## What it collects

Calls only `GET` endpoints under `/api/v4`:

- `/version` — instance version
- `/groups` — all groups visible to the token (paginated)
- `/projects` — all projects visible to the token, including archived (paginated).
  Each project shows which features are enabled (see "Project feature columns").
- `/projects/:id/repository/commits?per_page=1` — one extra call per non-empty
  project to fetch the latest commit on the default branch (see "Repository
  activity"). Skipped for projects with no `default_branch` (empty repo).
- `/users` — all users (admin only; gracefully skipped on 403). Each user is
  classified by activity (see below).

## Project feature columns

GitLab lets each project enable or disable many built-in features. The
projects table includes a `features` column listing the short names of the
features that are currently enabled on that project. Below the table, a
"Feature enablement summary" shows how many projects use each feature.

A feature is considered enabled when its `*_access_level` field is anything
other than `disabled` (e.g. `private`, `enabled`, `public`), or — for older
boolean-style fields — when the `*_enabled` flag is true.

Tracked features (short name → GitLab field):

| short | GitLab field |
|---|---|
| issues | `issues_access_level` / `issues_enabled` |
| mrs | `merge_requests_access_level` / `merge_requests_enabled` |
| ci | `builds_access_level` / `jobs_enabled` |
| wiki | `wiki_access_level` / `wiki_enabled` |
| snippets | `snippets_access_level` / `snippets_enabled` |
| registry | `container_registry_access_level` / `container_registry_enabled` |
| packages | `packages_enabled` |
| pages | `pages_access_level` |
| lfs | `lfs_enabled` |
| service_desk | `service_desk_enabled` |
| releases | `releases_access_level` |
| environments | `environments_access_level` |
| feature_flags | `feature_flags_access_level` |
| security | `security_and_compliance_access_level` |
| analytics | `analytics_access_level` |
| forking | `forking_access_level` |

Features whose fields are not returned by your GitLab version appear as
`n/a` in the summary instead of `0 / N`.

## Repository activity

The Projects table includes three commit-derived columns:

- `last_commit_at` — `committed_date` of the most recent commit on the
  project's default branch. Distinct from `last_activity_at`, which also bumps
  on issue/MR/comment activity. Empty for repos that have never seen a commit.
- `days_since_commit` — `today − last_commit_at` in whole days, or empty for
  empty repos.
- `commit_state` — derived label:
  - `empty` — `default_branch` is null (no commit ever).
  - `inactive` — last commit is at least `--inactive-days` old (default 180).
  - `active` — last commit is more recent than that.
  - `unknown` — the commits lookup failed for an unexpected reason; counted
    in the summary but rare.

A "Repository activity summary" block above the Projects table totals each
state. The threshold used in that block reflects whatever `--inactive-days`
value the run used.

Cost: one extra `GET /repository/commits?per_page=1` per non-empty project.
On instances with thousands of projects this adds noticeable wall time but no
heavy load (one tiny request per project).

## User activity columns

For each user the report shows `last_sign_in_at`, `last_activity_on`,
`days_since_activity`, and an `interaction` label.

- `last_sign_in_at` — datetime of the last **UI** sign-in. Only UI logins
  update this field.
- `last_activity_on` — date (day-level granularity) of the last interaction
  of any kind: UI, API, or **git over HTTP/SSH**. This is what tells you a
  user has touched the instance even if they never logged into the web UI.
- `days_since_activity` — `today − last_activity_on` in whole days, or empty
  if the user has no recorded activity day.
- `interaction` — derived label:
  - `never` — both fields null; the account has not interacted at all.
  - `non-ui-only` — has activity but never signed into the UI (typical for
    git-only or API-only consumers, including bot/service accounts).
  - `ui-only` — has a sign-in but no activity day (rare; treat as edge case).
  - `active` — both fields populated.

A short summary block above the table totals each label so you can scan the
instance at a glance.

Caveat: very old accounts predating GitLab's tracking of these fields may
show `null` even if they once interacted. Not a concern for a fresh 17.x
instance.

The GitLab v4 API does not separately expose "last git operation" vs. "last
API call" timestamps; `last_activity_on` is the only signal that aggregates
non-UI activity, which is why it is the primary column.

## Configuration reference

```ini
[gitlab]
url = https://gitlab.example.com   # base URL, no trailing /api/v4
token = glpat-xxxxxxxxxxxx         # PAT with read_api (admin for users)
verify_tls = true                  # set to false only for self-signed lab certs
```
