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
- `/users` — all users (admin only; gracefully skipped on 403)

## Configuration reference

```ini
[gitlab]
url = https://gitlab.example.com   # base URL, no trailing /api/v4
token = glpat-xxxxxxxxxxxx         # PAT with read_api (admin for users)
verify_tls = true                  # set to false only for self-signed lab certs
```
