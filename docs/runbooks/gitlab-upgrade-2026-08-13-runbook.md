# GitLab Upgrade Runbook — 13.08.2026, 14:00

**Path:** 17.11.7 → 18.2.8 → 18.5.7 → 18.8.11 → 18.11.9
**Deployment:** Omnibus `gitlab-ce` image, single pod on Kubernetes, all services in-pod
**Expected return to service:** 19:00
**Companion documents:** [Pre-flight](gitlab-upgrade-2026-08-13-preflight.md) · [Rollback](gitlab-upgrade-2026-08-13-rollback.md)

> **Do not start this document until the pre-flight go/no-go is signed off.**
> In particular: PostgreSQL must already be ≥ 16.5, and the restore must have been rehearsed.

---

## Deployment + Argo CD + Kustomize — read this first

This instance runs as a **`Deployment`** (not a StatefulSet), managed by **Argo CD** from a
**Kustomize** overlay. That changes four things. Nothing else in this runbook changes.

### 1. Argo CD will undo your work — disable auto-sync before you touch anything

Every `kubectl set image`, `kubectl patch`, and `kubectl scale` in this runbook is an
imperative change that diverges from Git. **If the Argo Application has `selfHeal: true`,
Argo will revert it — potentially while migrations are running.** Argo restoring
`replicas: 1` during a snapshot, or reverting the image mid-migration, is the worst
failure mode available in this window.

This is a **blocking prerequisite**, handled in Phase A0.

### 2. Pod names change on every restart

A Deployment names pods `<name>-<replicaset-hash>-<random>`. After every scale-up you must
re-resolve `$POD` before using `gl`. Every hop below includes this step.

### 3. Rolling updates — already safe, but keep the ordering

Your strategy is `RollingUpdate` with **`maxSurge: 0`**, which means Kubernetes will *not*
start a second pod before terminating the first. The double-pod hazard that normally makes
`RollingUpdate` dangerous for a single-instance GitLab on RWO **does not apply here** —
whoever wrote this manifest handled it.

Keep the scale-to-0-before-image-change ordering anyway: it is what makes the snapshots
consistent, not just what avoids double pods. Phase A0 sets `Recreate` as belt-and-braces.

### 4. `/etc/gitlab` lives on the PVC — which is good news for rollback

The single `gitlab-pvc` is mounted three times by `subPath`:

| Mount | subPath | Contains |
|---|---|---|
| `/etc/gitlab` | `config` | `gitlab.rb`, **`gitlab-secrets.json`** |
| `/var/opt/gitlab` | `data` | Postgres, repositories, uploads, registry |
| `/var/log/gitlab` | `logs` | logs |

**A PVC snapshot therefore captures config, secrets and data together, consistently.**
That is a materially stronger rollback position than the usual split. It does not remove
the need for the off-pod backup — a snapshot is useless if the storage backend itself is
the problem — but the snapshot path is now a genuinely complete restore.

### 5. This is GitLab **CE**, not EE

Image is `gitlab/gitlab-ce`. Two consequences:

- **Maintenance Mode is not available** — it is a Premium feature. Phase B2 uses the
  `gitlab-ctl stop puma` path instead. Do not go looking for the admin toggle.
- Tags are `-ce.0`, not `-ee.0`. **Never substitute a `gitlab-ee` image.** Switching
  distribution is a separate migration and doing it inside a four-hop version upgrade
  turns one problem into two.

### 6. There is a second hostname — the container registry

The Ingress serves **two** hosts into the same pod:

- `git.itd.justiz.nrw.de` — GitLab
- `contreg.itd.justiz.nrw.de` — container registry

This matters more than it looks. **The 18.5 NGINX routing regression produced 404s
precisely on non-primary hostnames.** You are going to 18.5.7, which is past the 18.5.2
fix, but the registry host must be explicitly tested after hop 2 — it is invisible from
inside the pod and no `gitlab-ctl status` check will catch it.

Registry data sits under `/var/opt/gitlab` and is covered by both the snapshot and the
backup. SSH is exposed separately on **NodePort 30044**.

### 7. There is a maintenance pod — use it

A second Deployment, `gitlab-maintenance`, runs `ubuntu:noble` at `replicas: 0` and mounts
the **same** `gitlab-pvc` at `/mnt/vol`. This is the right tool for inspecting or repairing
the volume when GitLab will not boot.

> **RWO — never run both at once.** `gitlab-pvc` is `ReadWriteOnce`. Scale `gitlab-ce`
> to 0 *before* scaling `gitlab-maintenance` to 1, and back to 0 before restarting GitLab.
> Two pods writing to one volume is how you corrupt Postgres.

```bash
# Only ever with gitlab-ce at replicas=0
kubectl scale deployment gitlab-maintenance -n "$NS" --replicas=1
MPOD=$(kubectl get pods -n "$NS" -l app=gitlab-maintenance -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n "$NS" "$MPOD" -- ls -lh /mnt/vol/config /mnt/vol/data

# ALWAYS scale back to 0 before starting gitlab-ce
kubectl scale deployment gitlab-maintenance -n "$NS" --replicas=0
```

### Every command below is already written for a Deployment

No mental substitution required — `deployment "$DEPLOY"` is used throughout, waits on pod
deletion use the label selector rather than a pod name, and each scale-up is followed by
`repod`. Copy and paste as written.

The two habits to keep in your head:

1. **`repod` after every scale-up**, before anything that uses `gl` or `$POD`.
2. **Never let two GitLab pods exist at once** — always scale to 0 before changing the image.

> **`kubectl rollout undo` is NOT a rollback.** It reverts the pod template only. The
> database schema has already migrated forward and an older GitLab against a newer schema
> is broken. See the rollback card.

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
export NS=gitlab                          # namespace
export DEPLOY=gitlab-ce                    # Deployment name
export CTR=gitlab-ce                         # container name
export SEL="app=gitlab,component=gitlab"                   # label selector that matches the pod
export PVC=gitlab-pvc                    # PVC name (standalone resource)
export ARGOAPP=gitlab                     # Argo CD Application name
export GLHOST=git.itd.justiz.nrw.de       # primary hostname
export REGHOST=contreg.itd.justiz.nrw.de  # container registry hostname
export SSHPORT=30044                      # NodePort for git over SSH

# Re-resolve the pod name. RUN THIS AFTER EVERY SCALE-UP.
# Blocks until a Running pod exists. "Running" is not "Ready" -- during migrations the
# pod is Running and deliberately not Ready, which is exactly when you need to reach it.
repod() {
  for i in $(seq 1 60); do
    POD=$(kubectl get pods -n "$NS" -l "$SEL" \
      --field-selector=status.phase=Running \
      -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    [ -n "$POD" ] && { export POD; echo "POD=$POD"; return 0; }
    echo "waiting for pod... ($i)"; sleep 5
  done
  echo "TIMEOUT: no Running pod after 5 minutes"; return 1
}

# Run a command inside the GitLab container
gl() { kubectl exec -n "$NS" "$POD" -c "$CTR" -- "$@"; }
```

Sanity check:

```bash
repod
gl gitlab-ctl status && kubectl get pods -n "$NS"
```

> Commands run as root inside the `gitlab-ce` image. Do not prefix with `sudo`.
>
> **`repod` before `gl`, every time the pod has restarted.** A stale `$POD` gives you
> `Error from server (NotFound)`, which is harmless — but a `$POD` pointing at a
> *terminating* pod gives you confusing output from a container that is going away.

---

## Phase A0 — 13:20 Take Argo CD out of the loop — **BLOCKING**

Nothing else in this runbook is safe until this is done.

### A0.1 Find out what Argo is currently allowed to do

```bash
kubectl get application "$ARGOAPP" -n argocd -o jsonpath='{.spec.syncPolicy}{"\n"}'
```

| Output contains | Meaning | Risk |
|---|---|---|
| `"selfHeal":true` | Argo actively reverts drift | **Critical — will fight you mid-migration** |
| `"automated":{...}` without selfHeal | Argo syncs on Git changes only | Moderate — a teammate's commit triggers a sync |
| `{}` or absent | Manual sync only | Low, but suspend anyway |

### A0.2 Suspend it

```bash
# Record the current policy so you can restore it exactly
kubectl get application "$ARGOAPP" -n argocd -o jsonpath='{.spec.syncPolicy}' \
  > ~/gitlab-upgrade-2026-08-13/argocd-syncpolicy.json
cat ~/gitlab-upgrade-2026-08-13/argocd-syncpolicy.json; echo

# Disable automated sync entirely for the window
kubectl patch application "$ARGOAPP" -n argocd --type=merge \
  -p '{"spec":{"syncPolicy":{"automated":null}}}'

# Verify — must NOT contain "automated"
kubectl get application "$ARGOAPP" -n argocd -o jsonpath='{.spec.syncPolicy}{"\n"}'
```

If you have the Argo CLI, this is equivalent and easier to confirm:

```bash
argocd app set "$ARGOAPP" --sync-policy none
argocd app get "$ARGOAPP" | grep -i "sync policy"
```

- [ ] `spec.syncPolicy.automated` is gone
- [ ] Original policy saved to `~/gitlab-upgrade-2026-08-13/argocd-syncpolicy.json`
- [ ] **Team told not to merge anything touching this Application today**

### A0.3 Set the Deployment strategy to Recreate

Belt-and-braces against two GitLab pods ever existing at once:

```bash
kubectl patch deployment "$DEPLOY" -n "$NS" --type=merge \
  -p '{"spec":{"strategy":{"type":"Recreate","rollingUpdate":null}}}'

kubectl get deployment "$DEPLOY" -n "$NS" -o jsonpath='{.spec.strategy.type}{"\n"}'
```

Expect `Recreate`.

- [ ] Strategy reads `Recreate`

---

## Phase A — 13:30 Pre-window checks

```bash
repod

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

> **Maintenance Mode is not available on CE** — it is a Premium feature. Do not spend
> window time looking for the toggle. Stop the services instead.

Stop the web and job services so the backup is consistent:

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

Your probes are already unusually tolerant — someone thought about this. Do the arithmetic
anyway, because hop 4 breaks it:

| Probe | Config | Total tolerance from container start |
|---|---|---|
| liveness | `initialDelay 1200` + `failureThreshold 100` × `period 30` | **~70 min** |
| readiness | `initialDelay 180` + `failureThreshold 300` × `period 10` | ~53 min |

Hops 1–3 finish well inside 70 minutes. **Hop 4 is budgeted at 90 minutes** because of the
automatic PostgreSQL 17.7 upgrade — that exceeds the liveness tolerance, and the probe
would kill the pod *mid-`pg_upgrade`*, leaving a corrupt cluster. Remove the probes for
the window rather than trying to tune them per hop.

`terminationGracePeriodSeconds` is **30**, which is far too short: Kubernetes will `SIGKILL`
Postgres 30 seconds into a shutdown that legitimately takes longer. Raise it to 300.

Fix both, once, for the whole window.

```bash
kubectl patch deployment "$DEPLOY" -n "$NS" --type=json -p='[
  {"op":"remove","path":"/spec/template/spec/containers/0/livenessProbe"},
  {"op":"remove","path":"/spec/template/spec/containers/0/readinessProbe"},
  {"op":"replace","path":"/spec/template/spec/terminationGracePeriodSeconds","value":300}
]'
```

If a path does not exist the patch errors — drop that line and re-run. If a `startupProbe`
exists, remove it too.

Verify:

```bash
kubectl get deployment "$DEPLOY" -n "$NS" -o jsonpath='{.spec.template.spec.containers[0].livenessProbe}{"\n"}'
kubectl get deployment "$DEPLOY" -n "$NS" -o jsonpath='{.spec.template.spec.terminationGracePeriodSeconds}{"\n"}'
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
kubectl scale deployment "$DEPLOY" -n "$NS" --replicas=0
kubectl wait --for=delete pod -l "$SEL" -n "$NS" --timeout=360s

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
kubectl set image deployment/"$DEPLOY" -n "$NS" "$CTR"=gitlab/gitlab-ce:18.2.8-ce.0

# 5. Scale up
kubectl scale deployment "$DEPLOY" -n "$NS" --replicas=1
repod                 # REQUIRED: new pod, new name

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
kubectl scale deployment "$DEPLOY" -n "$NS" --replicas=0
kubectl wait --for=delete pod -l "$SEL" -n "$NS" --timeout=360s
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
kubectl set image deployment/"$DEPLOY" -n "$NS" "$CTR"=gitlab/gitlab-ce:18.5.7-ce.0
kubectl scale deployment "$DEPLOY" -n "$NS" --replicas=1
repod                 # REQUIRED: new pod, new name

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
curl -sS -o /dev/null -w "git root:    %{http_code}\n"  "https://${GLHOST}/"
curl -sS -o /dev/null -w "git signin:  %{http_code}\n"  "https://${GLHOST}/users/sign_in"

# THE REGRESSION CASE — the non-primary host is what 18.5.0/18.5.1 broke
curl -sS -o /dev/null -w "registry v2: %{http_code}\n"  "https://${REGHOST}/v2/"
```

`/users/sign_in` must return 200. `/` returns 200 or 302. **`/v2/` must return 401**, not
404 — a 401 is the registry correctly demanding auth, which proves routing works. A 404
means the NGINX routing regression has hit the registry host.

Then prove the registry actually works end to end:

```bash
docker login "${REGHOST}"
docker pull "${REGHOST}/<some/known/image>:<tag>"
```

- [ ] `/v2/` returns **401**
- [ ] `docker login` succeeds
- [ ] `docker pull` of an existing image succeeds

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
kubectl scale deployment "$DEPLOY" -n "$NS" --replicas=0
kubectl wait --for=delete pod -l "$SEL" -n "$NS" --timeout=360s
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
kubectl set image deployment/"$DEPLOY" -n "$NS" "$CTR"=gitlab/gitlab-ce:18.8.11-ce.0
kubectl scale deployment "$DEPLOY" -n "$NS" --replicas=1
repod                 # REQUIRED: new pod, new name

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

# Free space in the volume MUST exceed 2x the Postgres data directory
gl du -sh /var/opt/gitlab/postgresql/data
gl df -h /var/opt/gitlab

# Ceph pool headroom — this hop rewrites the whole database, which inflates
# every snapshot taken earlier today via copy-on-write
kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph df
kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph status
```

- [ ] Background migrations zero
- [ ] **Free space in the volume ≥ 2× Postgres data dir** — if not, **stop here and stay on 18.8.11**
- [ ] **Ceph pool has headroom for a full DB rewrite** and status is `HEALTH_OK`

> If the Ceph pool is tight, delete nothing to make room — deleting a snapshot here is
> irreversible under `deletionPolicy: Delete` and costs you the rollback for hops you have
> already completed. Stop on 18.8.11 instead and do hop 4 in its own window.

### Execute

```bash
# 2-3. Scale down and snapshot (leaving 18.8.11) — this is your only rollback for the PG upgrade
kubectl scale deployment "$DEPLOY" -n "$NS" --replicas=0
kubectl wait --for=delete pod -l "$SEL" -n "$NS" --timeout=360s
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
kubectl set image deployment/"$DEPLOY" -n "$NS" "$CTR"=gitlab/gitlab-ce:18.11.9-ce.0
kubectl scale deployment "$DEPLOY" -n "$NS" --replicas=1
repod                 # REQUIRED: new pod, new name

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

```bash
# Both Ingress hosts
curl -sS -o /dev/null -w "git signin:  %{http_code}\n"  "https://${GLHOST}/users/sign_in"   # 200
curl -sS -o /dev/null -w "registry v2: %{http_code}\n"  "https://${REGHOST}/v2/"            # 401

# Registry service is actually running in the pod
gl gitlab-ctl status | grep -E "registry|nginx|puma|sidekiq|postgresql|gitaly"
```

- [ ] Log in as a **non-admin external-auth (LDAP/SAML/OIDC) user**
- [ ] Log in as a second external-auth user from a different group, if applicable
- [ ] Browse a project, view a file, view history
- [ ] `git clone` over **SSH via NodePort 30044** with an existing key
- [ ] `git clone` over **HTTPS**
- [ ] `git push` a trivial commit to a scratch branch
- [ ] Open a merge request, view its diff
- [ ] **`docker login contreg.itd.justiz.nrw.de` succeeds**
- [ ] **`docker pull` of an existing image succeeds**
- [ ] **`docker push` a scratch tag succeeds**
- [ ] Admin → Overview → Users loads
- [ ] Admin → Monitoring → Background migrations shows nothing outstanding

Any failure here: decide whether it is service-affecting. A cosmetic issue is a ticket.
A broken clone or a broken login is a rollback decision — see the
[rollback card](gitlab-upgrade-2026-08-13-rollback.md).

---

## Phase H — 18:45 Restore probes and close out

### H1. Confirm services are running

You stopped `puma` and `sidekiq` in B2; the upgrades restarted them. Confirm:

```bash
gl gitlab-ctl status              # puma and sidekiq must show "run"
```

### H2. Restore the probes

```bash
kubectl patch deployment "$DEPLOY" -n "$NS" --type=json -p="[
  {\"op\":\"add\",\"path\":\"/spec/template/spec/containers/0/livenessProbe\",\"value\":$(cat ~/gitlab-upgrade-2026-08-13/probe-liveness.json)},
  {\"op\":\"add\",\"path\":\"/spec/template/spec/containers/0/readinessProbe\",\"value\":$(cat ~/gitlab-upgrade-2026-08-13/probe-readiness.json)}
]"
```

If either file is empty, the workload had no such probe originally — drop that line from
the patch. The saved `workload-before.yaml` from pre-flight is the reference if you need
to reconstruct anything by hand.

This triggers one final pod restart. Wait it out and confirm the pod goes `Ready` on its own:

```bash
kubectl rollout status deployment/"$DEPLOY" -n "$NS" --timeout=900s
kubectl get pods -n "$NS"
```

Also restore `terminationGracePeriodSeconds` to its original value if you want it back —
though leaving it at 300 is the safer setting for GitLab and is worth keeping.

- [ ] Probes restored and pod reaches `Ready` **without intervention**
- [ ] `kubectl get pods -n $NS` shows `1/1 Running`

### H3. Reconcile Git, then re-enable Argo CD — **ORDER IS CRITICAL**

Everything you did this afternoon was imperative. Git still describes a 17.11.7 instance.

> **Re-enabling Argo auto-sync before updating Git will downgrade the image to 17.11.7
> against an 18.11.9 database schema.** That is an instant outage and a restore-from-snapshot
> job. Commit Git first. Verify the diff is empty. Only then re-enable Argo.

#### H3.1 Update the Kustomize overlay

In the overlay that Argo tracks, set the image tag. If you use the Kustomize image
transformer:

```yaml
# kustomization.yaml
images:
  - name: gitlab/gitlab-ce
    newTag: 18.11.9-ce.0
```

Also reflect anything else you changed and want to keep:

- `spec.strategy.type: Recreate` — **keep this**, it is correct for a single-pod GitLab on RWO
- `spec.template.spec.terminationGracePeriodSeconds: 300` — **keep this**, it prevents
  `SIGKILL` on Postgres during shutdown
- Probes — only if you intentionally changed them; the Phase H2 restore put them back to
  their original values, which already match Git

Commit and push.

#### H3.2 Confirm Git and the cluster now agree

```bash
# Render the overlay locally and check the tag
kustomize build <path/to/overlay> | grep "image: gitlab/gitlab-ce"

# What is actually running
kubectl get deployment "$DEPLOY" -n "$NS" -o jsonpath='{..image}{"\n"}'
```

Both must read `gitlab/gitlab-ce:18.11.9-ce.0`.

#### H3.3 Diff before letting Argo act

```bash
argocd app diff "$ARGOAPP"
```

**An empty diff is the gate.** If the diff shows Argo wanting to change the image,
`replicas`, `strategy`, or the probes, fix Git until it does not. Do not proceed on a
non-empty diff — read every line and understand it.

#### H3.4 Restore the sync policy

```bash
cat ~/gitlab-upgrade-2026-08-13/argocd-syncpolicy.json; echo

kubectl patch application "$ARGOAPP" -n argocd --type=merge \
  -p "{\"spec\":{\"syncPolicy\":$(cat ~/gitlab-upgrade-2026-08-13/argocd-syncpolicy.json)}}"

kubectl get application "$ARGOAPP" -n argocd -o jsonpath='{.spec.syncPolicy}{"\n"}'
```

Then watch the first reconcile closely:

```bash
argocd app get "$ARGOAPP"
kubectl get pods -n "$NS" -w
```

- [ ] Kustomize overlay committed and pushed with tag `18.11.9-ce.0`
- [ ] `kustomize build` and the live Deployment show the same image
- [ ] **`argocd app diff` is empty**
- [ ] Sync policy restored to its saved value
- [ ] Argo reports `Synced` and `Healthy`
- [ ] **The pod did NOT restart when Argo resumed**

If Argo restarts the pod on resume, something in Git still differs from the cluster.
Let the pod come up, then find the difference — do not start patching under time pressure.

### H4. Communicate

- [ ] Broadcast message removed
- [ ] Users notified that service is restored
- [ ] Known issues, if any, communicated with a ticket reference

### H5. Clean up — **not before tomorrow**

Keep every snapshot until the instance has run a full business day on 18.11.9. Background
migrations may still be finishing and problems often surface under real load.

> **`deletionPolicy` is `Delete`.** Removing a `VolumeSnapshot` object destroys the Ceph
> snapshot behind it immediately and irreversibly. There is no undo. Treat every
> `kubectl delete volumesnapshot` as a one-way door.

```bash
# Run on 14.08.2026 or later, NOT during the window
kubectl get volumesnapshot -n "$NS"
# kubectl delete volumesnapshot gitlab-pre-18-2-8 gitlab-pre-18-5-7 gitlab-pre-18-8-11 -n "$NS"
```

Retain `gitlab-pre-18-11-9` and the off-pod backup for at least a week. Snapshots do
consume pool space that grows as the volume diverges — check `ceph df` when you clean up,
but let correctness win over capacity while the upgrade is still fresh.

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
