# ROLLBACK RUNBOOK

Rollback playbook for `robot` after teleapp integration and conflict-hardening changes.

## Scope

Use this when a newly deployed version causes:

- persistent Telegram polling conflict loops
- unexpected restart storms
- queue/schedule behavior regressions
- runtime failure after dependency/layout changes

## 0) Pre-check

Run in repo root:

```bash
git status --short --branch
```

If the working tree is not clean on the deployment machine, stash or commit first.

## 1) Fast Rollback (single-maintainer, fastest recovery)

Use this when service recovery speed is the top priority.

1. Find a known stable commit:

```bash
git log --oneline -n 30
```

2. Reset `main` to that commit:

```bash
git checkout main
git reset --hard <stable_commit_sha>
git push --force-with-lease origin main
```

3. Re-deploy on runtime host:

```bash
git checkout main
git pull origin main
```

4. Rebuild env and restart process:

Windows:

```powershell
bootstrap_robot.bat
start_robot.bat
```

Linux/macOS:

```bash
./bootstrap_robot.sh
./start_robot.sh
```

## 2) Safe Rollback (preserve git history)

Use this when collaboration/audit trail is preferred over raw speed.

1. Identify merge commit on `main`:

```bash
git log --oneline --merges -n 10
```

2. Revert the merge commit:

```bash
git checkout main
git revert -m 1 <merge_commit_sha>
git push origin main
```

3. Re-deploy and restart (same as above).

## 3) Post-rollback Verification

In Telegram, run:

- `/status`
- `/doctor`
- `/queue`
- `/agentstatus`

Expected:

- no repeated `polling conflict backoff=...` logs
- `restart_count` not rapidly increasing
- queue drains normally
- no persistent `last_error`

## 4) Conflict-Specific Emergency Fix

If rollback is not immediately possible, do this temporary mitigation:

1. Ensure only one process uses the bot token.
2. Stop duplicate processes.
3. Restart single instance.

Optional temporary override:

```bash
TELEAPP_HOT_RELOAD=0
```

Use only as emergency stabilization, then restore normal config.

## 5) Known Good Baseline (before integration branch merge)

- `robot` main baseline commit: `264e13f`

Use this as one candidate recovery point if needed.
