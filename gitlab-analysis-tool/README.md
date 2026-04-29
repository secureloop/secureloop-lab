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

Full inventory:

```bash
python3 gitlab-inventory.py
```

Custom config or output path:

```bash
python3 gitlab-inventory.py --config /path/to/config.ini --output /tmp/report.md
```

Reports are written to `reports/gitlab-inventory-<host>-<YYYYMMDD-HHMMSS>.md`
by default. The `reports/` directory is gitignored.

## What it collects

Calls only `GET` endpoints under `/api/v4`:

- `/version` — instance version
- `/groups` — all groups visible to the token (paginated)
- `/projects` — all projects visible to the token, including archived (paginated)
- `/users` — all users (admin only; gracefully skipped on 403). Each user is
  classified by activity (see below).

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
