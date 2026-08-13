# GitLab Upgrade — Pre-Flight

**Window:** 13.08.2026, 14:00
**Path:** 17.11.7 → 18.2.8 → 18.5.7 → 18.8.11 → 18.11.9
**Deployment:** Omnibus `gitlab-ce` image, single pod on Kubernetes, all services in-pod
**Companion documents:** [Runbook](gitlab-upgrade-2026-08-13-runbook.md) · [Rollback](gitlab-upgrade-2026-08-13-rollback.md)

This document is worked through **before** the window and ends in a go/no-go decision.
Nothing here happens on the 13th. If an item cannot be completed in time, that is a
no-go signal, not something to carry into the window.

---

## 0. Shell setup

Every command in this document set assumes these are exported. Set them once per terminal.

```bash
export NS=gitlab                          # namespace
export DEPLOY=gitlab-ce                    # Deployment name
export CTR=gitlab-ce                         # container name
export SEL="app=gitlab,component=gitlab"                   # label selector that matches the pod
export PVC=gitlab-pvc                    # PVC name (standalone resource)
export ARGOAPP=gitlab                     # Argo CD Application name

# Re-resolve the pod name. Deployment pods are renamed on every restart.
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

# Helper used throughout: run a command inside the GitLab container
gl() { kubectl exec -n "$NS" "$POD" -c "$CTR" -- "$@"; }
```

Verify both work before relying on them:

```bash
repod
gl gitlab-ctl status
```

> Commands inside the official `gitlab-ce` image already run as root — do **not** prefix
> with `sudo`. GitLab's own documentation assumes a VM install and includes `sudo`; drop it.

---

## 1. Instance Facts

Fill this in first. Every later command and both companion documents reference these values.

| Fact | Command | Value |
|---|---|---|
| Namespace | — | `_______` |
| Workload kind + name | `kubectl get sts,deploy -n $NS` | `_______` |
| Pod name | `kubectl get pods -n $NS` | `_______` |
| Container name | `kubectl get pod $POD -n $NS -o jsonpath='{.spec.containers[*].name}'` | `_______` |
| Current GitLab version | `gl gitlab-rake gitlab:env:info \| grep "GitLab information" -A5` | `_______` |
| **Current PostgreSQL version** | `gl gitlab-psql -c "SELECT version();"` | `_______` |
| PVC name(s) | `kubectl get pvc -n $NS` | `_______` |
| StorageClass | `kubectl get pvc -n $NS -o jsonpath='{.items[*].spec.storageClassName}'` | `_______` |
| VolumeSnapshotClass | `kubectl get volumesnapshotclass` | `_______` |
| Image repository | `kubectl get deployment $DEPLOY -n $NS -o jsonpath='{..image}'` | `_______` |
| PVC total / used | `gl df -h /var/opt/gitlab` | `_______` |
| Postgres data dir size | `gl du -sh /var/opt/gitlab/postgresql/data` | `_______` |
| External auth type | Admin → Settings → General | `_______` |
| Pod label selector | `kubectl get deployment $DEPLOY -n $NS -o jsonpath='{.spec.selector.matchLabels}'` | `_______` |
| Deployment strategy | `kubectl get deployment $DEPLOY -n $NS -o jsonpath='{.spec.strategy.type}'` | `_______` |
| Argo CD Application | `kubectl get applications -n argocd` | `_______` |
| **Argo sync policy** | `kubectl get application $ARGOAPP -n argocd -o jsonpath='{.spec.syncPolicy}'` | `_______` |
| Kustomize overlay path | from the Argo Application `spec.source` | `_______` |

Record the current probe configuration too — you restore it at the end of the window.
**Save these to your persistent working directory, not `/tmp`** — the window spans several
hours and possibly a different terminal or machine than the one you are on now.

```bash
mkdir -p ~/gitlab-upgrade-2026-08-13
kubectl get deployment "$DEPLOY" -n "$NS" -o jsonpath='{.spec.template.spec.containers[0].livenessProbe}'  > ~/gitlab-upgrade-2026-08-13/probe-liveness.json
kubectl get deployment "$DEPLOY" -n "$NS" -o jsonpath='{.spec.template.spec.containers[0].readinessProbe}' > ~/gitlab-upgrade-2026-08-13/probe-readiness.json
kubectl get deployment "$DEPLOY" -n "$NS" -o jsonpath='{.spec.template.spec.terminationGracePeriodSeconds}{"\n"}'

cat ~/gitlab-upgrade-2026-08-13/probe-liveness.json; echo
cat ~/gitlab-upgrade-2026-08-13/probe-readiness.json; echo
```

Also take a full copy of the workload spec as a reference:

```bash
kubectl get deployment "$DEPLOY" -n "$NS" -o yaml > ~/gitlab-upgrade-2026-08-13/workload-before.yaml
```

Keep these files. They are the source of truth for Phase H of the runbook.

> **Argo CD manages this workload.** The probe values you capture here are what Git says
> today. Phase H of the runbook restores them from these files, then verifies that
> `argocd app diff` is empty before auto-sync is re-enabled. If you change probes in Git
> between now and the window, re-capture them.

---

## 2. PostgreSQL 16.5 gate — **blocking**

GitLab 18.0 requires **PostgreSQL 16.5 minimum**. GitLab 17.x runs on 14.14+, so an
instance that has been upgraded in place for a while may still be on PG 14 or 15.
If it is, hop 1 will fail.

```bash
gl gitlab-psql -c "SELECT version();"
```

| Result | Action |
|---|---|
| **16.5 or higher** | Nothing to do. Tick this item and move on. |
| **Below 16.5** | Run the upgrade below **before the window**, as its own scheduled work. |

Upgrading the bundled PostgreSQL needs disk space for two copies of the database, so
check first:

```bash
gl du -sh /var/opt/gitlab/postgresql/data   # size of the current cluster
gl df -h /var/opt/gitlab                    # free space must exceed the above
```

Then, **while still on 17.11.7** (which bundles PG 16):

```bash
# Take a snapshot and a backup first — see sections 5 and 6.
gl gitlab-ctl pg-upgrade -V 16
gl gitlab-psql -c "SELECT version();"       # confirm 16.x
```

If free space is insufficient, pass an alternative work directory:

```bash
gl gitlab-ctl pg-upgrade -V 16 --tmp-dir /var/opt/gitlab/tmp-pgupgrade
```

> **Why this is pre-window work:** `pg-upgrade` rewrites the entire cluster and cannot be
> safely interrupted. Bundling it with four GitLab hops in one window means a single
> failure mode consumes the whole afternoon. Do it separately, verify, then upgrade GitLab.

---

## 3. Confirm the four target versions are still current

The chosen patch levels each clear a known regression. Re-confirm they are still the
latest patch of their minor, and that no newer required stop has appeared:

- Upgrade path tool: <https://gitlab-com.gitlab.io/support/toolbox/upgrade-path/>
- Version notes: <https://docs.gitlab.com/update/versions/gitlab_18_changes/>

| Hop | Target | Minimum acceptable | Why |
|---|---|---|---|
| 1 | `18.2.8` | ≥ 18.2.6 | Below 18.2.6 has a code-push error after upgrade |
| 2 | `18.5.7` | ≥ 18.5.2 | Below 18.5.2 has an NGINX routing regression causing 404s |
| 3 | `18.8.11` | ≥ 18.8.2 | See section 4 — blocked-user credential change lands here |
| 4 | `18.11.9` | ≥ 18.11.2 | Below 18.11.2 breaks CI job token image pulls |

If a higher patch exists within the same minor, prefer it. **Do not change the minor
versions** — 18.2 / 18.5 / 18.8 / 18.11 are GitLab's required stops and cannot be skipped.

---

## 4. Version-specific preparation

### 4.1 Migrate `git_data_dirs` → `gitaly['configuration']` — **required before 18.0**

The `git_data_dirs` setting is removed in 18.0.

> **`gitlab.rb` is NOT editable in the pod.** It is supplied by the ConfigMap
> `gitlab-config-file` (key `gitlab.rb`), mounted read-only at `/opt/gitlab-config/`, and
> copied into `/etc/gitlab` by the `init-gitlab` init container running `init.sh`.
> **Any edit you make inside the running pod is discarded on the next restart** — which
> means it would silently vanish partway through the window.
>
> **The change must be made in the ConfigMap in Git, committed, and synced.**

Check both the live file and the ConfigMap — they should agree, and if they do not, that
is itself a finding worth understanding before you upgrade:

```bash
# What GitLab is actually running with
gl grep -n "git_data_dirs" /etc/gitlab/gitlab.rb

# What Git says (the source of truth)
kubectl get configmap gitlab-config-file -n "$NS" -o jsonpath='{.data.gitlab\.rb}' \
  | grep -n "git_data_dirs"

# How init.sh places the file - read it, so you know what the restart will do
kubectl get configmap gitlab-init-script -n "$NS" -o jsonpath='{.data.init\.sh}'
```

If there is no uncommented match, nothing to do. If there is, rewrite it **in the Git
source of the ConfigMap**.

**Before:**
```ruby
git_data_dirs({ "default" => { "path" => "/var/opt/gitlab/git-data" } })
```

**After:**
```ruby
gitaly['configuration'] = {
  storage: [
    {
      name: 'default',
      path: '/var/opt/gitlab/git-data/repositories',
    },
  ],
}
```

> **The `/repositories` suffix is mandatory.** GitLab appended it internally under the old
> setting. Omitting it points Gitaly at the wrong directory and every project appears empty.

Apply and verify while still on 17.11.7 — **via Git, then a controlled restart**:

1. Edit `gitlab.rb` in the Kustomize source, commit, push.
2. Sync Argo (or `kubectl apply` the ConfigMap if Argo is already suspended).
3. Confirm the ConfigMap in the cluster now shows the new syntax.
4. Restart the pod so `init.sh` copies the new file into `/etc/gitlab`:

```bash
kubectl scale deployment "$DEPLOY" -n "$NS" --replicas=0
kubectl wait --for=delete pod -l "$SEL" -n "$NS" --timeout=360s
kubectl scale deployment "$DEPLOY" -n "$NS" --replicas=1
repod
kubectl logs -n "$NS" "$POD" -c "$CTR" -f
```

5. Verify the change actually landed and Gitaly is healthy:

```bash
gl grep -n "gitaly\['configuration'\]" /etc/gitlab/gitlab.rb
gl grep -n "git_data_dirs" /etc/gitlab/gitlab.rb    # expect no uncommented match
gl gitlab-rake gitlab:gitaly:check
```

Then open a project in the UI and confirm the file tree renders. **Do this before the
window, not during it** — it costs a full pod restart.

### 4.2 Enable `ci_only_one_persistent_ref_creation` — **required before 18.0**

Without it, pipelines fail after the upgrade.

```bash
gl gitlab-rails runner -e production 'Feature.enable(:ci_only_one_persistent_ref_creation)'
gl gitlab-rails runner -e production 'puts Feature.enabled?(:ci_only_one_persistent_ref_creation)'
```

Expect `true`.

### 4.3 Audit blocked-user credentials — before 18.8

From 18.8.2, personal access tokens and deploy keys owned by **blocked** users stop working.
Anything automated that runs under a blocked user's token will silently break.

```bash
gl gitlab-rails runner -e production '
  User.blocked.each do |u|
    pats = u.personal_access_tokens.active.count
    keys = DeployKey.where(user_id: u.id).count
    puts "#{u.username}: #{pats} active PATs, #{keys} deploy keys" if pats > 0 || keys > 0
  end
'
```

For each result: reassign the credential to an active user, or confirm the breakage is
acceptable. Record the decision here.

| Blocked user | PATs | Deploy keys | Decision |
|---|---|---|---|
| | | | |

---

## 5. Backup — and prove the restore works

### 5.1 Application backup

```bash
gl gitlab-backup create
gl ls -lh /var/opt/gitlab/backups/
```

### 5.2 Configuration and secrets — **separate, and the one people forget**

`gitlab-backup create` does **not** include `/etc/gitlab`. Without `gitlab-secrets.json`
a restore produces an instance where 2FA, CI/CD variables, and every stored token are
undecryptable. The data is there and unreadable.

```bash
gl gitlab-ctl backup-etc
gl ls -lh /etc/gitlab/config_backup/
```

### 5.3 Copy both off the pod

Artifacts stored only on the PVC do not help if the PVC is the problem.

```bash
mkdir -p ~/gitlab-upgrade-2026-08-13
kubectl cp -n "$NS" -c "$CTR" "$POD:/var/opt/gitlab/backups/"      ~/gitlab-upgrade-2026-08-13/backups/
kubectl cp -n "$NS" -c "$CTR" "$POD:/etc/gitlab/config_backup/"    ~/gitlab-upgrade-2026-08-13/config/
kubectl cp -n "$NS" -c "$CTR" "$POD:/etc/gitlab/gitlab-secrets.json" ~/gitlab-upgrade-2026-08-13/gitlab-secrets.json
ls -lhR ~/gitlab-upgrade-2026-08-13/
```

### 5.4 Rehearse the restore — **do not skip**

An unrehearsed backup is a hypothesis. Restore into a scratch namespace or a throwaway
pod running the **same** version (17.11.7) and confirm you can log in and browse a repo.
See the [rollback card](gitlab-upgrade-2026-08-13-rollback.md) for the restore sequence.

Rehearsed on: `__________`  Result: `__________`

---

## 6. Verify the snapshot path

> **This gate can cancel the window.** Snapshots are the primary rollback path. If the
> storage backend has no CSI snapshot support, you have no fast rollback — only the slow
> backup restore in § C of the rollback card, which on a 300 Gi volume is a very different
> conversation about window length.
>
> Note also that `gitlab-pvc` sets **no `storageClassName`**, so it uses the cluster default.
> Find out what that actually is before you need it:
>
> ```bash
> kubectl get pvc gitlab-pvc -n "$NS" -o jsonpath='{.spec.storageClassName}{"\n"}'
> kubectl get storageclass
> kubectl get volumesnapshotclass
> ```
>
> If `kubectl get volumesnapshotclass` returns nothing, **stop and reconsider the window.**

Take one snapshot now to prove the CSI driver, the VolumeSnapshotClass, and your RBAC
all work. Finding out they do not at 15:00 is expensive.

```bash
cat <<EOF | kubectl apply -f -
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: gitlab-preflight-test
  namespace: ${NS}
spec:
  volumeSnapshotClassName: <VOLUMESNAPSHOTCLASS>
  source:
    persistentVolumeClaimName: <PVC-NAME>
EOF

kubectl get volumesnapshot -n "$NS" -w
```

Wait for `READYTOUSE=true`, note how long it took, then delete it:

```bash
kubectl delete volumesnapshot gitlab-preflight-test -n "$NS"
```

Snapshot duration observed: `______`  (used to budget each hop)

---

## 7. Disk space gate for hop 4

Hop 4 (18.11) **automatically upgrades the bundled PostgreSQL to 17.7** on single-node
Linux-package instances. That needs room for two copies of the database.

```bash
gl du -sh /var/opt/gitlab/postgresql/data
gl df -h /var/opt/gitlab
```

| Check | Requirement | Actual |
|---|---|---|
| Free space on `/var/opt/gitlab` | ≥ 2× Postgres data dir, plus headroom | `______` |

If this does not pass, expand the PVC **before** the window. Hop 4 is not safe otherwise.

---

## 8. Pre-pull the images

Four image pulls during the window is four chances for a registry timeout on the
critical path. Pull them ahead of time onto the node that will run the pod.

```bash
for v in 18.2.8 18.5.7 18.8.11 18.11.9; do
  echo "=== $v ==="
  crictl pull gitlab/gitlab-ce:${v}-ce.0 || docker pull gitlab/gitlab-ce:${v}-ce.0
done
```

If you cannot reach the node directly, run a throwaway DaemonSet or Job that references
each tag with `imagePullPolicy: IfNotPresent` to warm the node cache.

Confirm each tag exists and note its digest:

| Version | Tag | Digest | Pulled |
|---|---|---|---|
| 18.2.8 | `gitlab/gitlab-ce:18.2.8-ce.0` | | ☐ |
| 18.5.7 | `gitlab/gitlab-ce:18.5.7-ce.0` | | ☐ |
| 18.8.11 | `gitlab/gitlab-ce:18.8.11-ce.0` | | ☐ |
| 18.11.9 | `gitlab/gitlab-ce:18.11.9-ce.0` | | ☐ |

---

## 9. Background migrations must be at zero

The instance must be fully drained of batched background migrations before hop 1.
On a healthy 17.11.7 instance this is normally already true, but check now so that a
surprise here becomes pre-window work rather than a 14:15 problem.

```bash
gl gitlab-psql -c "SELECT job_class_name, table_name, status FROM batched_background_migrations WHERE status NOT IN (3, 6);"
```

**Zero rows is the required result.** Statuses `3` and `6` mean finished; anything else
is still outstanding. Also confirm via Admin → Monitoring → Background migrations.

If rows persist, let them run and re-check. For a genuinely stuck migration:

```bash
gl gitlab-rake "gitlab:background_migrations:finalize[JobClassName,table_name,column_name,'[[\"arg1\"],[\"arg2\"]]']"
```

Take the arguments from the query output. Do not mark migrations finished manually —
that loses data.

---

## 10. Communications

| Item | Owner | Done |
|---|---|---|
| Announce window to users (T-48h) | | ☐ |
| Broadcast message scheduled in GitLab (Admin → Messages) | | ☐ |
| Reminder to users (T-2h) | | ☐ |
| Escalation contact reachable during window | | ☐ |
| Someone other than the operator available as second pair of eyes | | ☐ |

Suggested broadcast text:

> GitLab will be unavailable for scheduled maintenance on Thursday 13.08.2026 from 14:00.
> Expected return to service: 19:00. Please push any in-flight work before 13:45.

---

## 11. Go / No-Go

All must be ticked by the evening of 12.08.2026.

- [ ] Instance Facts table complete
- [ ] Probe configuration and workload YAML saved to `~/gitlab-upgrade-2026-08-13/`
- [ ] **Argo CD Application identified and its sync policy recorded**
- [ ] **Team told not to merge anything touching the GitLab Application today**
- [ ] Kustomize overlay path known, and you have write access to push the final tag bump
- [ ] **PostgreSQL ≥ 16.5 confirmed** (or upgraded pre-window and verified)
- [ ] **A `VolumeSnapshotClass` exists and a test snapshot reached `readyToUse=true`**
- [ ] Container registry baseline captured: `docker login` + `pull` work **before** the window
- [ ] `git clone` over SSH on NodePort 30044 works **before** the window
- [ ] Confirmed the image is `gitlab/gitlab-ce` and all four target tags use `-ce.0`
- [ ] Four target versions re-confirmed as current
- [ ] `git_data_dirs` migrated and `gitlab:gitaly:check` passing
- [ ] `ci_only_one_persistent_ref_creation` enabled
- [ ] Blocked-user PATs and deploy keys audited and decided
- [ ] Full backup taken and copied off-pod
- [ ] `gitlab-secrets.json` copied off-pod
- [ ] **Restore rehearsed successfully**
- [ ] Snapshot creation verified end-to-end, duration noted
- [ ] Free space ≥ 2× Postgres data dir
- [ ] All four images pre-pulled
- [ ] Background migrations at zero rows
- [ ] Comms sent, escalation contact confirmed

**Any unticked item is a no-go.** Postponing the window costs one week.
Discovering a missing `gitlab-secrets.json` after a failed hop costs the instance.

Decision: `GO / NO-GO`   Made by: `__________`   At: `__________`
