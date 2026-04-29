# GitLab Analysis Tool

Read-only inventory of a self-hosted GitLab 17.x instance. Produces a Markdown
report listing groups, projects, and (if the token has admin scope) users.

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

Full inventory (writes both Markdown and HTML by default):

```bash
python3 gitlab-inventory.py
```

Pick a single format:

```bash
python3 gitlab-inventory.py --format html
python3 gitlab-inventory.py --format md
```

Custom config or output path:

```bash
python3 gitlab-inventory.py --config /path/to/config.ini --output /tmp/report.html --format html
# With --format both, --output is treated as a base; the extension is replaced:
python3 gitlab-inventory.py --output /tmp/report   # writes /tmp/report.md and /tmp/report.html
```

Reports are written to `reports/gitlab-inventory-<host>-<YYYYMMDD-HHMMSS>.{md,html}`
by default. The `reports/` directory is gitignored. The HTML file is fully
self-contained (inline CSS, no JS, no external resources) so you can open it
straight from your file system. It uses sticky table headers and zebra rows
so the wide projects/users tables stay readable when scrolling.

## What it collects

Calls only `GET` endpoints under `/api/v4`:

- `/version` — instance version
- `/groups` — all groups visible to the token (paginated)
- `/projects` — all projects visible to the token, including archived (paginated).
  Each project shows which features are enabled (see "Project feature columns").
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
