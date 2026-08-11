# GitLab Upgrade Runbook — 13.08.2026, 14:00

**Path:** 17.11.7 → 18.2.8 → 18.5.7 → 18.8.11 → 18.11.9
**Deployment:** Omnibus `gitlab-ee` image, single pod on Kubernetes, all services in-pod
**Expected return to service:** 19:00
**Companion documents:** [Pre-flight](gitlab-upgrade-2026-08-13-preflight.md) · [Rollback](gitlab-upgrade-2026-08-13-rollback.md)

> **Do not start this document until the pre-flight go/no-go is signed off.**
> In particular: PostgreSQL must already be ≥ 16.5, and the restore must have been rehearsed.

---

## Timeline and abort ladder

Each hop has a **deadline**. If a hop is not green by its deadline, you stop. Stopping on
a completed required stop is a valid, supported resting place — GitLab is fully functional
on 18.2.8 or 18.5.7 or 18.8.11. Finish the remaining hops in a later window.

| Time | Phase | Deadline | If missed |
|---|---|---|---|
| 13:30 | Pre-window checks | — | Postpone the window |
| 14:00 | Quiesce + final backup | 14:30 | Postpone the window |
| 14:30 | **Hop 1 → 18.2.8** | 15:15 | Roll back to 17.11.7, end window |
| 15:15 | **Hop 2 → 18.5.7** | 16:00 | Stop on 18.2.8, restore service, end window |
| 16:00 | **Hop 3 → 18.8.11** | 16:45 | Stop on 18.5.7, restore service, end window |
| 16:45 | **Hop 4 → 18.11.9** (incl. PG 17.7) | 18:15 | Stop on 18.8.11, restore service, end window |
| 18:15 | Post-window verification | 18:45 | — |
| 18:45 | Restore probes, comms | 19:00 | — |

**The abort decision is time-based, not mood-based.** Check the clock at each gate.

---

## Shell setup

```bash
export NS=gitlab
export STS=gitlab
export POD=gitlab-0
export CTR=gitlab
export GLHOST=gitlab.example.com          # external hostname, for HTTP checks

gl() { kubectl exec -n "$NS" "$POD" -c "$CTR" -- "$@"; }
```

Sanity check:

```bash
gl gitlab-ctl status && kubectl get pods -n "$NS"
```

> Commands run as root inside the `gitlab-ee` image. Do not prefix with `sudo`.
>
> **If the workload is a `Deployment`, not a `StatefulSet`:** substitute `deployment` for
> `statefulset` throughout, and re-resolve `POD` after every scale-up, because the pod name
> changes on each restart:
> ```bash
> export POD=$(kubectl get pods -n "$NS" -l <your-selector> -o jsonpath='{.items[0].metadata.name}')
> ```
> Re-run this after step 5 of every hop, before using `gl`.

---

## Phase A — 13:30 Pre-window checks

```bash
# 1. Current version is what we expect
gl gitlab-rake gitlab:env:info | grep -A2 "GitLab information"

# 2. PostgreSQL is >= 16.5
gl gitlab-psql -c "SELECT version();"

# 3. Background migrations are at zero — MUST be zero rows
gl gitlab-psql -c "SELECT job_class_name, table_name, status FROM batched_background_migrations WHERE status NOT IN (3, 6);"

# 4. No down migrations
gl gitlab-rake db:migrate:status | grep "^  down" || echo "OK: none down"

# 5. All services up
gl gitlab-ctl status

# 6. Free space >= 2x Postgres data dir
gl du -sh /var/opt/gitlab/postgresql/data
gl df -h /var/opt/gitlab
```

- [ ] All six checks pass → proceed
- [ ] Any check fails → **postpone the window**

---

## Phase B — 14:00 Quiesce and final backup

### B1. Announce

Post the broadcast message. Confirm it is visible to users.

### B2. Stop accepting work

Preferred, if licensed (Premium/Ultimate) — **Admin → Settings → General → Maintenance Mode**,
enable, save. This leaves the instance readable while blocking writes.

Fallback, or in addition, stop the web and job services so the backup is consistent:

```bash
gl gitlab-ctl stop puma
gl gitlab-ctl stop sidekiq
gl gitlab-ctl status              # puma and sidekiq should show "down"
```

Postgres, Gitaly and Redis stay up — `gitlab-backup` needs them.

### B3. Final backup

Even though pre-flight took one, take a fresh one now. This is the artifact you restore from.

```bash
gl gitlab-backup create
gl gitlab-ctl backup-etc
gl ls -lh /var/opt/gitlab/backups/ /etc/gitlab/config_backup/
```

### B4. Copy off the pod

```bash
mkdir -p ~/gitlab-upgrade-2026-08-13/window
kubectl cp -n "$NS" -c "$CTR" "$POD:/var/opt/gitlab/backups/"        ~/gitlab-upgrade-2026-08-13/window/backups/
kubectl cp -n "$NS" -c "$CTR" "$POD:/etc/gitlab/config_backup/"      ~/gitlab-upgrade-2026-08-13/window/config/
kubectl cp -n "$NS" -c "$CTR" "$POD:/etc/gitlab/gitlab-secrets.json" ~/gitlab-upgrade-2026-08-13/window/gitlab-secrets.json
ls -lhR ~/gitlab-upgrade-2026-08-13/window/
```

- [ ] Backup tarball present and non-trivial in size
- [ ] `gitlab-secrets.json` present off-pod

### B5. Suspend probes and raise the termination grace period — **critical**

A default liveness probe will restart a pod that is fifteen minutes into a schema
migration. That is how an upgrade becomes a restore. A short `terminationGracePeriodSeconds`
will `SIGKILL` Postgres during shutdown. Fix both, once, for the whole window.

```bash
kubectl patch statefulset "$STS" -n "$NS" --type=json -p='[
  {"op":"remove","path":"/spec/template/spec/containers/0/livenessProbe"},
  {"op":"remove","path":"/spec/template/spec/containers/0/readinessProbe"},
  {"op":"replace","path":"/spec/template/spec/terminationGracePeriodSeconds","value":300}
]'
```

If a path does not exist the patch errors — drop that line and re-run. If a `startupProbe`
exists, remove it too.

Verify:

```bash
kubectl get statefulset "$STS" -n "$NS" -o jsonpath='{.spec.template.spec.containers[0].livenessProbe}{"\n"}'
kubectl get statefulset "$STS" -n "$NS" -o jsonpath='{.spec.template.spec.terminationGracePeriodSeconds}{"\n"}'
```

Expect an empty first line and `300` on the second.

> Readiness removal means the Service routes to the pod even while it boots. That is
> acceptable here because user traffic is already stopped. Both probes are restored in Phase H.

- [ ] Probes removed, grace period 300
- [ ] `~/gitlab-upgrade-2026-08-13/probe-liveness.json` and `probe-readiness.json` present (from pre-flight)

---

## The hop procedure

Every hop follows the same eight steps. Read this once now; each hop below then gives the
exact commands with the version already filled in.

1. **Gate** — background migrations at zero rows.
2. **Scale to zero** — clean shutdown, so the snapshot is consistent.
3. **Snapshot** — the PVC, named for the version you are leaving.
4. **Set image** — the new tag.
5. **Scale up** — pod boots, `reconfigure` runs, migrations run.
6. **Watch** — follow the logs to completion. Do not touch the pod.
7. **Verify** — services up, no down migrations, HTTP healthy, auth works.
8. **Drain** — wait for background migrations to reach zero before the next hop.

**Step 8 is the one that gets skipped and the one that breaks the next hop.** GitLab
refuses to upgrade past a required stop with outstanding batched migrations, and the
error arrives after the pod has already restarted on the new image.

---

## Phase C — 14:30 Hop 1 → 18.2.8

**Deadline 15:15.** Leaving 17.11.7, crossing the 18.0 major boundary.

```bash
# 1. Gate — must return zero rows
gl gitlab-psql -c "SELECT job_class_name, table_name, status FROM batched_background_migrations WHERE status NOT IN (3, 6);"

# 2. Scale to zero
kubectl scale statefulset "$STS" -n "$NS" --replicas=0
kubectl wait --for=delete pod/"$POD" -n "$NS" --timeout=360s

# 3. Snapshot (leaving 17.11.7)
cat <<EOF | kubectl apply -f -
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: gitlab-pre-18-2-8
  namespace: ${NS}
spec:
  volumeSnapshotClassName: <VOLUMESNAPSHOTCLASS>
  source:
    persistentVolumeClaimName: <PVC-NAME>
EOF
kubectl wait --for=jsonpath='{.status.readyToUse}'=true \
  volumesnapshot/gitlab-pre-18-2-8 -n "$NS" --timeout=900s

# 4. Set image
kubectl set image statefulset/"$STS" -n "$NS" "$CTR"=gitlab/gitlab-ee:18.2.8-ee.0

# 5. Scale up
kubectl scale statefulset "$STS" -n "$NS" --replicas=1

# 6. Watch — expect 10-20 minutes. Do not interrupt.
kubectl logs -n "$NS" "$POD" -c "$CTR" -f
```

Watch for `Chef Infra Client finished` and the absence of migration errors. The pod will
appear "unhealthy" for a long stretch — that is expected and is why the probes are off.

```bash
# 7. Verify
gl gitlab-ctl status
gl gitlab-rake gitlab:env:info | grep -A2 "GitLab information"     # expect 18.2.8
gl gitlab-rake db:migrate:status | grep "^  down" || echo "OK: none down"
curl -sS -o /dev/null -w "readiness: %{http_code}\n" "https://${GLHOST}/-/readiness?all=1"

# 8. Drain — repeat until zero rows
gl gitlab-psql -c "SELECT job_class_name, table_name, status, progress FROM batched_background_migrations WHERE status NOT IN (3, 6);"
```

**Version-specific checks for this hop:**

```bash
# git_data_dirs must be gone and Gitaly healthy across the 18.0 boundary
gl gitlab-rake gitlab:gitaly:check

# The CI feature flag survived the upgrade
gl gitlab-rails runner -e production 'puts Feature.enabled?(:ci_only_one_persistent_ref_creation)'
```

**Auth smoke test** — log in through the browser with a **real non-admin LDAP/SAML account**.
Not an admin, not a local account. External auth is the highest-risk area across a major
version boundary and an admin session that is already open proves nothing.

- [ ] Version reads 18.2.8
- [ ] No down migrations
- [ ] `gitlab:gitaly:check` passes, project file tree renders
- [ ] Feature flag `true`
- [ ] **Non-admin external-auth login succeeds**
- [ ] Background migrations back to zero rows
- [ ] Clock is before 15:15

**Go / No-Go for hop 2:** `______`

---

## Phase D — 15:15 Hop 2 → 18.5.7

**Deadline 16:00.**

```bash
# 1. Gate
gl gitlab-psql -c "SELECT job_class_name, table_name, status FROM batched_background_migrations WHERE status NOT IN (3, 6);"

# 2-3. Scale down and snapshot (leaving 18.2.8)
kubectl scale statefulset "$STS" -n "$NS" --replicas=0
kubectl wait --for=delete pod/"$POD" -n "$NS" --timeout=360s
cat <<EOF | kubectl apply -f -
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: gitlab-pre-18-5-7
  namespace: ${NS}
spec:
  volumeSnapshotClassName: <VOLUMESNAPSHOTCLASS>
  source:
    persistentVolumeClaimName: <PVC-NAME>
EOF
kubectl wait --for=jsonpath='{.status.readyToUse}'=true \
  volumesnapshot/gitlab-pre-18-5-7 -n "$NS" --timeout=900s

# 4-5. Upgrade
kubectl set image statefulset/"$STS" -n "$NS" "$CTR"=gitlab/gitlab-ee:18.5.7-ee.0
kubectl scale statefulset "$STS" -n "$NS" --replicas=1

# 6. Watch
kubectl logs -n "$NS" "$POD" -c "$CTR" -f

# 7. Verify
gl gitlab-ctl status
gl gitlab-rake gitlab:env:info | grep -A2 "GitLab information"     # expect 18.5.7
gl gitlab-rake db:migrate:status | grep "^  down" || echo "OK: none down"
curl -sS -o /dev/null -w "readiness: %{http_code}\n" "https://${GLHOST}/-/readiness?all=1"

# 8. Drain
gl gitlab-psql -c "SELECT job_class_name, table_name, status, progress FROM batched_background_migrations WHERE status NOT IN (3, 6);"
```

**Version-specific notes for this hop:**

- A post-deployment migration **finalizes the design-management backfill**. Most instances
  complete within 2 minutes; up to 10 on larger ones. At your size, expect the short end.
- 18.5 changed NGINX routing. The 404-on-non-standard-hostname regression is fixed in
  18.5.2 and you are on 18.5.7 — but verify explicitly, because this one is invisible
  from inside the pod:

```bash
curl -sS -o /dev/null -w "root: %{http_code}\n"    "https://${GLHOST}/"
curl -sS -o /dev/null -w "signin: %{http_code}\n"  "https://${GLHOST}/users/sign_in"
```

Both must return 200 (or 302 for `/`). If you reach GitLab through any additional
hostname or alias, test each one.

- [ ] Version reads 18.5.7
- [ ] No down migrations
- [ ] External hostname returns 200/302, all aliases tested
- [ ] **Non-admin external-auth login succeeds**
- [ ] Background migrations back to zero rows
- [ ] Clock is before 16:00

**Go / No-Go for hop 3:** `______`

---

## Phase E — 16:00 Hop 3 → 18.8.11

**Deadline 16:45.**

```bash
# 1. Gate
gl gitlab-psql -c "SELECT job_class_name, table_name, status FROM batched_background_migrations WHERE status NOT IN (3, 6);"

# 2-3. Scale down and snapshot (leaving 18.5.7)
kubectl scale statefulset "$STS" -n "$NS" --replicas=0
kubectl wait --for=delete pod/"$POD" -n "$NS" --timeout=360s
cat <<EOF | kubectl apply -f -
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: gitlab-pre-18-8-11
  namespace: ${NS}
spec:
  volumeSnapshotClassName: <VOLUMESNAPSHOTCLASS>
  source:
    persistentVolumeClaimName: <PVC-NAME>
EOF
kubectl wait --for=jsonpath='{.status.readyToUse}'=true \
  volumesnapshot/gitlab-pre-18-8-11 -n "$NS" --timeout=900s

# 4-5. Upgrade
kubectl set image statefulset/"$STS" -n "$NS" "$CTR"=gitlab/gitlab-ee:18.8.11-ee.0
kubectl scale statefulset "$STS" -n "$NS" --replicas=1

# 6. Watch
kubectl logs -n "$NS" "$POD" -c "$CTR" -f

# 7. Verify
gl gitlab-ctl status
gl gitlab-rake gitlab:env:info | grep -A2 "GitLab information"     # expect 18.8.11
gl gitlab-rake db:migrate:status | grep "^  down" || echo "OK: none down"
curl -sS -o /dev/null -w "readiness: %{http_code}\n" "https://${GLHOST}/-/readiness?all=1"

# 8. Drain — this one takes longer, see below
gl gitlab-psql -c "SELECT job_class_name, table_name, status, progress FROM batched_background_migrations WHERE status NOT IN (3, 6);"
```

**Version-specific notes for this hop:**

- 18.8 introduces a batched background migration that copies CI build metadata into
  `p_ci_job_definitions`. **Its duration is proportional to your total CI job count**, not
  to repo size. On a small instance this is minutes, but check the `progress` column rather
  than assuming — this is the most likely place for step 8 to run long.
- From 18.8.2, **PATs and deploy keys belonging to blocked users stop working**. You audited
  these in pre-flight section 4.3. Confirm nothing unexpected broke:

```bash
gl gitlab-rails runner -e production '
  User.blocked.each { |u| puts "#{u.username}: #{u.personal_access_tokens.active.count} PATs" }
'
```

- [ ] Version reads 18.8.11
- [ ] No down migrations
- [ ] `p_ci_job_definitions` migration progressing or complete
- [ ] **Non-admin external-auth login succeeds**
- [ ] Background migrations back to zero rows
- [ ] Clock is before 16:45

**Go / No-Go for hop 4:** `______`

---

## Phase F — 16:45 Hop 4 → 18.11.9 — includes automatic PostgreSQL 17.7 upgrade

**Deadline 18:15. Budget 90 minutes. This is the riskiest hop of the window.**

> **Read before starting.** Upgrading to 18.11 on a single-node Linux-package instance
> **automatically upgrades the bundled PostgreSQL to 17.7**. This happens unattended during
> `reconfigure`, needs roughly twice the database size in free space, and **cannot be safely
> interrupted**. A pod restart mid-upgrade leaves a corrupt cluster whose only remedy is the
> snapshot you take in step 3.
>
> Once step 5 starts: do not scale, do not delete the pod, do not `Ctrl-C` anything that
> looks stuck, do not let anyone else touch the namespace.

### Pre-hop gate — stricter than the others

```bash
# Background migrations at zero
gl gitlab-psql -c "SELECT job_class_name, table_name, status FROM batched_background_migrations WHERE status NOT IN (3, 6);"

# Free space MUST exceed 2x the Postgres data directory
gl du -sh /var/opt/gitlab/postgresql/data
gl df -h /var/opt/gitlab
```

- [ ] Background migrations zero
- [ ] **Free space ≥ 2× Postgres data dir** — if not, **stop here and stay on 18.8.11**

### Execute

```bash
# 2-3. Scale down and snapshot (leaving 18.8.11) — this is your only rollback for the PG upgrade
kubectl scale statefulset "$STS" -n "$NS" --replicas=0
kubectl wait --for=delete pod/"$POD" -n "$NS" --timeout=360s
cat <<EOF | kubectl apply -f -
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: gitlab-pre-18-11-9
  namespace: ${NS}
spec:
  volumeSnapshotClassName: <VOLUMESNAPSHOTCLASS>
  source:
    persistentVolumeClaimName: <PVC-NAME>
EOF
kubectl wait --for=jsonpath='{.status.readyToUse}'=true \
  volumesnapshot/gitlab-pre-18-11-9 -n "$NS" --timeout=900s
```

- [ ] **Snapshot `gitlab-pre-18-11-9` confirmed `readyToUse=true` before continuing**

```bash
# 4-5. Upgrade
kubectl set image statefulset/"$STS" -n "$NS" "$CTR"=gitlab/gitlab-ee:18.11.9-ee.0
kubectl scale statefulset "$STS" -n "$NS" --replicas=1

# 6. Watch — expect 30-60 minutes. HANDS OFF.
kubectl logs -n "$NS" "$POD" -c "$CTR" -f
```

Expect to see the PostgreSQL upgrade run before the Rails migrations. Long silences are
normal. If you need reassurance that work is happening rather than hung, from a second
terminal:

```bash
kubectl exec -n "$NS" "$POD" -c "$CTR" -- ps aux | grep -E "pg_upgrade|postgres|initdb"
kubectl exec -n "$NS" "$POD" -c "$CTR" -- df -h /var/opt/gitlab
```

Growing disk usage and a live `pg_upgrade` process mean it is working. **Observe only.**

```bash
# 7. Verify
gl gitlab-ctl status
gl gitlab-rake gitlab:env:info | grep -A2 "GitLab information"     # expect 18.11.9
gl gitlab-psql -c "SELECT version();"                              # expect PostgreSQL 17.7
gl gitlab-rake db:migrate:status | grep "^  down" || echo "OK: none down"
curl -sS -o /dev/null -w "readiness: %{http_code}\n" "https://${GLHOST}/-/readiness?all=1"

# 8. Drain
gl gitlab-psql -c "SELECT job_class_name, table_name, status, progress FROM batched_background_migrations WHERE status NOT IN (3, 6);"
```

- [ ] Version reads 18.11.9
- [ ] **PostgreSQL reports 17.7**
- [ ] No down migrations
- [ ] **Non-admin external-auth login succeeds**
- [ ] Background migrations back to zero rows
- [ ] Clock is before 18:15

---

## Phase G — 18:15 Post-window verification

```bash
# Full instance check
gl gitlab-rake gitlab:check SANITIZE=true

# Gitaly and repository access
gl gitlab-rake gitlab:gitaly:check

# Nothing down
gl gitlab-ctl status
gl gitlab-rake db:migrate:status | grep "^  down" || echo "OK: none down"

# Final background migration state
gl gitlab-psql -c "SELECT job_class_name, table_name, status FROM batched_background_migrations WHERE status NOT IN (3, 6);"
```

Then, through the browser and a real client:

- [ ] Log in as a **non-admin external-auth (LDAP/SAML/OIDC) user**
- [ ] Log in as a second external-auth user from a different group, if applicable
- [ ] Browse a project, view a file, view history
- [ ] `git clone` over **SSH** with an existing key
- [ ] `git clone` over **HTTPS**
- [ ] `git push` a trivial commit to a scratch branch
- [ ] Open a merge request, view its diff
- [ ] Admin → Overview → Users loads
- [ ] Admin → Monitoring → Background migrations shows nothing outstanding
- [ ] Check for anything the pre-flight assumed absent: `gl gitlab-ctl status | grep -E "registry|pages"`

Any failure here: decide whether it is service-affecting. A cosmetic issue is a ticket.
A broken clone or a broken login is a rollback decision — see the
[rollback card](gitlab-upgrade-2026-08-13-rollback.md).

---

## Phase H — 18:45 Restore probes and close out

### H1. Disable maintenance mode

If enabled in B2: **Admin → Settings → General → Maintenance Mode**, disable, save.

If you stopped services manually instead, they were restarted by the upgrades — confirm:

```bash
gl gitlab-ctl status              # puma and sidekiq must show "run"
```

### H2. Restore the probes

```bash
kubectl patch statefulset "$STS" -n "$NS" --type=json -p="[
  {\"op\":\"add\",\"path\":\"/spec/template/spec/containers/0/livenessProbe\",\"value\":$(cat ~/gitlab-upgrade-2026-08-13/probe-liveness.json)},
  {\"op\":\"add\",\"path\":\"/spec/template/spec/containers/0/readinessProbe\",\"value\":$(cat ~/gitlab-upgrade-2026-08-13/probe-readiness.json)}
]"
```

If either file is empty, the workload had no such probe originally — drop that line from
the patch. The saved `statefulset-before.yaml` from pre-flight is the reference if you need
to reconstruct anything by hand.

This triggers one final pod restart. Wait it out and confirm the pod goes `Ready` on its own:

```bash
kubectl rollout status statefulset/"$STS" -n "$NS" --timeout=900s
kubectl get pods -n "$NS"
```

Also restore `terminationGracePeriodSeconds` to its original value if you want it back —
though leaving it at 300 is the safer setting for GitLab and is worth keeping.

- [ ] Probes restored and pod reaches `Ready` **without intervention**
- [ ] `kubectl get pods -n $NS` shows `1/1 Running`

### H3. Persist the change

The image tag was changed imperatively with `kubectl set image`. **If this workload is
managed by Git, Helm, or Argo CD, that change will be reverted on the next sync.**
Update the source of truth to `gitlab/gitlab-ee:18.11.9-ee.0` now, before you close out.

- [ ] Manifest / Helm values / Argo source updated and committed
- [ ] Probe and grace-period changes reflected in the manifest if they were kept

### H4. Communicate

- [ ] Broadcast message removed
- [ ] Users notified that service is restored
- [ ] Known issues, if any, communicated with a ticket reference

### H5. Clean up — **not before tomorrow**

Keep every snapshot until the instance has run a full business day on 18.11.9. Background
migrations may still be finishing and problems often surface under real load.

```bash
# Run on 14.08.2026 or later, NOT during the window
kubectl get volumesnapshot -n "$NS"
# kubectl delete volumesnapshot gitlab-pre-18-2-8 gitlab-pre-18-5-7 gitlab-pre-18-8-11 -n "$NS"
```

Retain `gitlab-pre-18-11-9` and the off-pod backup for at least a week.

---

## Window record

| Phase | Started | Finished | Outcome |
|---|---|---|---|
| B — Quiesce + backup | | | |
| C — Hop 1 → 18.2.8 | | | |
| D — Hop 2 → 18.5.7 | | | |
| E — Hop 3 → 18.8.11 | | | |
| F — Hop 4 → 18.11.9 + PG 17.7 | | | |
| G — Verification | | | |
| H — Close out | | | |

**Final version reached:** `__________`
**Service restored at:** `__________`
**Follow-up items:** `__________`
