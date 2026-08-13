# ROLLBACK CARD — GitLab Upgrade 13.08.2026

**Open this only when something has gone wrong.**
Companions: [Pre-flight](gitlab-upgrade-2026-08-13-preflight.md) · [Runbook](gitlab-upgrade-2026-08-13-runbook.md)

---

## THE ONE RULE

> **Once a hop's database migrations have run, reverting the image tag does NOT roll back.**
> GitLab schema migrations are forward-only. An older GitLab against a newer schema is a
> broken instance, not a rolled-back one.
>
> **After migrations have started, restoring from snapshot or backup is the ONLY path back.**

---

## STEP ZERO — IS ARGO CD SUSPENDED?

**Before any recovery command.** If Argo auto-sync is live it will fight every step below —
recreating the PVC you just deleted, resetting `replicas`, reverting the image.

```bash
kubectl get application "$ARGOAPP" -n argocd -o jsonpath='{.spec.syncPolicy}{"\n"}'
```

If the output contains `automated`, suspend it **now**:

```bash
kubectl patch application "$ARGOAPP" -n argocd --type=merge \
  -p '{"spec":{"syncPolicy":{"automated":null}}}'
```

- [ ] Output no longer contains `automated` → continue

> **`kubectl rollout undo` is NOT a rollback.** It reverts the pod template and nothing else.
> The database has already migrated forward. Running an older GitLab against a newer schema
> gives you a broken instance that *looks* recovered. Do not use it. Use § A, § B or § C.

---

## DECISION TREE

```
Something is wrong.
│
├─ Has the new pod started and begun migrations?  (logs show db:migrate / reconfigure)
│  │
│  ├─ NO  → Image not yet applied, or pod still pulling.
│  │        → Set the image tag back. Scale up. No restore needed.        [ § A ]
│  │
│  └─ YES ─┬─ Did migrations COMPLETE and is the instance broken?
│          │  → Restore the snapshot for the version you left.            [ § B ]
│          │
│          ├─ Are migrations STILL RUNNING and it just looks slow?
│          │  → WAIT. Do not intervene. Confirm progress first.           [ § D ]
│          │
│          └─ Did migrations FAIL / pod crash-looping / PG corrupt?
│             → Restore the snapshot for the version you left.            [ § B ]
│                If snapshot restore fails → restore from backup.         [ § C ]
```

**Not sure which branch you are on?** Take § D first. It is read-only.

---

## LAST KNOWN GOOD

| If you were leaving | Revert image to | Restore snapshot |
|---|---|---|
| 17.11.7 (hop 1 failed) | `gitlab/gitlab-ce:17.11.7-ce.0` | `gitlab-pre-18-2-8` |
| 18.2.8 (hop 2 failed) | `gitlab/gitlab-ce:18.2.8-ce.0` | `gitlab-pre-18-5-7` |
| 18.5.7 (hop 3 failed) | `gitlab/gitlab-ce:18.5.7-ce.0` | `gitlab-pre-18-8-11` |
| 18.8.11 (hop 4 failed) | `gitlab/gitlab-ce:18.8.11-ce.0` | `gitlab-pre-18-11-9` |

Off-pod backup: `~/gitlab-upgrade-2026-08-13/window/`
Secrets: `~/gitlab-upgrade-2026-08-13/window/gitlab-secrets.json`

```bash
export NS=gitlab DEPLOY=gitlab-ce CTR=gitlab-ce SEL="app=gitlab,component=gitlab" PVC=gitlab-pvc ARGOAPP=gitlab

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
gl() { kubectl exec -n "$NS" "$POD" -c "$CTR" -- "$@"; }
```

Commands below are written for a **Deployment** and are copy-paste ready. `repod` blocks
until a Running pod exists — run it after every scale-up, before any `gl` command.

---

## § A — Revert image only (migrations have NOT run)

```bash
kubectl scale deployment "$DEPLOY" -n "$NS" --replicas=0
kubectl wait --for=delete pod -l "$SEL" -n "$NS" --timeout=360s
kubectl set image deployment/"$DEPLOY" -n "$NS" "$CTR"=gitlab/gitlab-ce:<LAST-GOOD>-ce.0
kubectl scale deployment "$DEPLOY" -n "$NS" --replicas=1
repod                 # REQUIRED: new pod, new name
kubectl logs -n "$NS" "$POD" -c "$CTR" -f
```

Verify: `gl gitlab-ctl status` and `gl gitlab-rake gitlab:env:info | grep -A2 "GitLab information"`

---

## § B — Restore from snapshot (PRIMARY PATH)

Restores the PVC to its exact state before the failed hop. Fastest and most complete.

### B1. Stop everything

```bash
kubectl scale deployment "$DEPLOY" -n "$NS" --replicas=0
kubectl wait --for=delete pod -l "$SEL" -n "$NS" --timeout=360s
```

### B2. Identify the PVC and PROTECT THE VOLUME

```bash
kubectl get pvc -n "$NS"
export PVC=<PVC-NAME>
export PV=$(kubectl get pvc "$PVC" -n "$NS" -o jsonpath='{.spec.volumeName}')

# CRITICAL: set Retain so deleting the PVC does not destroy the volume
kubectl patch pv "$PV" -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'
kubectl get pv "$PV" -o jsonpath='{.spec.persistentVolumeReclaimPolicy}{"\n"}'   # must read: Retain
```

**Do not proceed until that prints `Retain`.**

### B3. Confirm the snapshot is usable

```bash
kubectl get volumesnapshot -n "$NS"
kubectl get volumesnapshot <SNAPSHOT-NAME> -n "$NS" -o jsonpath='{.status.readyToUse}{"\n"}'   # must read: true
```

Also note its restore size:

```bash
kubectl get volumesnapshot <SNAPSHOT-NAME> -n "$NS" -o jsonpath='{.status.restoreSize}{"\n"}'
```

### B4. Replace the PVC from the snapshot

> **Argo CD manages this PVC.** Confirm STEP ZERO was done. If auto-sync is live, Argo
> recreates the PVC from Git — empty, with no `dataSource` — the moment you delete it,
> and you lose the restore. Re-verify before deleting:
>
> ```bash
> kubectl get application "$ARGOAPP" -n argocd -o jsonpath='{.spec.syncPolicy}{"\n"}'
> ```
>
> Must not contain `automated`.

```bash
# Capture the current spec first, in case you need to recreate it as-is
kubectl get pvc "$PVC" -n "$NS" -o yaml > ~/pvc-backup-$PVC.yaml

kubectl delete pvc "$PVC" -n "$NS"

cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ${PVC}
  namespace: ${NS}
spec:
  storageClassName: <STORAGECLASS>
  dataSource:
    name: <SNAPSHOT-NAME>
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: <SIZE>          # must be >= the snapshot restoreSize
EOF

kubectl get pvc "$PVC" -n "$NS" -w      # wait for Bound
```

> The PVC name **must match exactly** what the Deployment's `volumes[].persistentVolumeClaim.claimName`
> references — this is `$PVC`, an ordinary standalone manifest in your Kustomize overlay.
> Confirm with:
> ```bash
> kubectl get deployment "$DEPLOY" -n "$NS" -o jsonpath='{.spec.template.spec.volumes[*].persistentVolumeClaim.claimName}{"\n"}'
> ```
>
> **After recovery, reconcile Git.** The restored PVC has a `dataSource` that your overlay
> does not. Either remove the `dataSource` from the live PVC's stored spec expectations, or
> add `ignoreDifferences` for it in the Argo Application, before re-enabling auto-sync.

### B5. Revert the image and start

```bash
kubectl set image deployment/"$DEPLOY" -n "$NS" "$CTR"=gitlab/gitlab-ce:<LAST-GOOD>-ce.0
kubectl scale deployment "$DEPLOY" -n "$NS" --replicas=1
repod                 # REQUIRED: new pod, new name
kubectl logs -n "$NS" "$POD" -c "$CTR" -f
```

### B6. Verify

```bash
gl gitlab-ctl status
gl gitlab-rake gitlab:env:info | grep -A2 "GitLab information"   # expect LAST-GOOD version
gl gitlab-psql -c "SELECT version();"
gl gitlab-rake db:migrate:status | grep "^  down" || echo "OK: none down"
gl gitlab-rake gitlab:check SANITIZE=true
```

- [ ] Version matches LAST-GOOD
- [ ] Non-admin external-auth login works
- [ ] `git clone` works

---

## § C — Restore from backup (FALLBACK, if snapshot restore fails)

Slower, and the restore **must run on the same GitLab version the backup was taken from**
(17.11.7 for the Phase B backup).

### C1. Bring up a clean pod on the ORIGINAL version

```bash
kubectl scale deployment "$DEPLOY" -n "$NS" --replicas=0
kubectl wait --for=delete pod -l "$SEL" -n "$NS" --timeout=360s
kubectl set image deployment/"$DEPLOY" -n "$NS" "$CTR"=gitlab/gitlab-ce:17.11.7-ce.0
kubectl scale deployment "$DEPLOY" -n "$NS" --replicas=1
repod                 # REQUIRED: new pod, new name
kubectl rollout status deployment/"$DEPLOY" -n "$NS" --timeout=900s
```

### C2. Restore the SECRETS FIRST

Without this the restored data is encrypted and unreadable. Do this before the data restore.

```bash
kubectl cp -n "$NS" -c "$CTR" \
  ~/gitlab-upgrade-2026-08-13/window/gitlab-secrets.json \
  "$POD:/etc/gitlab/gitlab-secrets.json"

kubectl cp -n "$NS" -c "$CTR" \
  ~/gitlab-upgrade-2026-08-13/window/config/ \
  "$POD:/etc/gitlab/config_backup/"

gl gitlab-ctl reconfigure
```

### C3. Copy the backup in and restore

```bash
kubectl cp -n "$NS" -c "$CTR" \
  ~/gitlab-upgrade-2026-08-13/window/backups/ \
  "$POD:/var/opt/gitlab/backups/"

gl ls -lh /var/opt/gitlab/backups/          # note the BACKUP timestamp prefix

gl gitlab-ctl stop puma
gl gitlab-ctl stop sidekiq
gl gitlab-backup restore BACKUP=<TIMESTAMP>     # e.g. 1755086400_2026_08_13_17.11.7
gl gitlab-ctl reconfigure
gl gitlab-ctl restart
```

### C4. Verify

```bash
gl gitlab-ctl status
gl gitlab-rake gitlab:check SANITIZE=true
```

- [ ] Non-admin external-auth login works
- [ ] A project's files and history are visible
- [ ] `git clone` works
- [ ] CI/CD variables are readable (proves secrets restored correctly)

---

## § D — "Is it hung, or just slow?" (READ-ONLY — do this before any restore)

Long silences during migrations and during the PG 17.7 upgrade in hop 4 are **normal**.
Confirm before you act.

```bash
# Is a process actually working?
kubectl exec -n "$NS" "$POD" -c "$CTR" -- ps aux | grep -E "pg_upgrade|postgres|initdb|rake|ruby"

# Is disk usage moving?  (run twice, 60s apart)
kubectl exec -n "$NS" "$POD" -c "$CTR" -- df -h /var/opt/gitlab

# Are logs still producing output?
kubectl logs -n "$NS" "$POD" -c "$CTR" --tail=50

# Is Postgres alive and what is it doing?
kubectl exec -n "$NS" "$POD" -c "$CTR" -- gitlab-psql -c \
  "SELECT pid, state, wait_event_type, left(query,80) FROM pg_stat_activity WHERE state <> 'idle';"

# Batched migration progress
kubectl exec -n "$NS" "$POD" -c "$CTR" -- gitlab-psql -c \
  "SELECT job_class_name, status, progress FROM batched_background_migrations WHERE status NOT IN (3,6);"
```

| Observation | Verdict |
|---|---|
| Live `pg_upgrade` / `ruby` process, disk usage changing | **Working. Wait.** |
| Active queries in `pg_stat_activity`, `progress` advancing | **Working. Wait.** |
| No relevant process, no log output for >15 min, disk static | Likely hung → § B |
| Pod in `CrashLoopBackOff` | Failed → § B |

---

## IF IN DOUBT

1. **Stop.** Do not run another command.
2. The instance being down for 30 more minutes is cheaper than a bad restore.
3. Call the escalation contact.
4. Snapshots and the off-pod backup are both intact — you have time.
5. Staying on an older required stop is a legitimate outcome. **Not every window ends at 18.11.9.**
