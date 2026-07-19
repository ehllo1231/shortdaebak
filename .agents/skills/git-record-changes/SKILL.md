---
name: git-record-changes
description: Record every completed repository code change as a scoped, verified Git commit. Use automatically for any task that creates, modifies, or deletes source code, tests, configuration, scripts, or directly related documentation in this repository, including fixes, features, refactors, and maintenance. Finish the task with a commit, but never push it.
---

# Record Code Changes in Git

Treat a local Git commit as part of the definition of done for every completed code-change task in this repository. Keep the commit limited to the current task and leave publishing to the user.

## Core Rules

- Run this workflow for every completed task that changes repository files covered by the description.
- Never run `git push`, change remotes or upstreams, open a pull request, create a tag, or publish a release.
- Never amend, rebase, reset, restore, checkout, clean, or stash existing work unless the user explicitly requests that exact operation.
- Preserve all pre-existing user changes, including staged, unstaged, and untracked files.
- Commit only a coherent, completed change. Do not create empty commits or commit incomplete work by default.
- Treat generated output, local configuration, credentials, tokens, cookies, and environment files as non-committable unless the user explicitly requires a reviewed fixture or template.

## Workflow

### 1. Capture the Baseline

Before editing files, inspect:

```bash
git status --short --branch
git diff --name-status
git diff --cached --name-status
```

Remember which files and index entries existed before the task. Do not assume a dirty worktree belongs to the current request.

If the directory is not a Git repository, stop and report that the commit cannot be created. Do not initialize Git implicitly.

### 2. Implement and Verify

Complete the requested change and run checks proportional to its risk. Prefer the repository's documented formatter, linter, type checker, and focused tests, then broaden testing when shared behavior or user-facing workflows are affected.

Do not commit when required checks fail. Fix the failure first, unless the user explicitly asks for a failing or work-in-progress commit. If a check cannot run because of an environment limitation, inspect the change as far as possible and report the limitation with the commit result.

### 3. Isolate the Task Changes

Inspect the final state and diff:

```bash
git status --short
git diff --stat
git diff
git diff --cached
```

Classify every changed path as either current-task work or pre-existing/unrelated work.

- Stage current-task paths explicitly with `git add -- <path>...`.
- Never use `git add .`, `git add -A`, or another broad staging command.
- Do not stage unrelated files merely because they are present or already modified.
- If a file mixes current-task edits with pre-existing user edits, isolate only the owned hunks when this can be done safely and verified.
- If unrelated staged changes or overlapping edits cannot be separated without modifying the user's index or worktree, stop before committing and explain the conflict.

### 4. Audit the Staged Snapshot

Review exactly what the commit would contain:

```bash
git diff --cached --name-status
git diff --cached --stat
git diff --cached --check
git diff --cached
```

Confirm all of the following:

- Every staged path belongs to the current task.
- No required current-task path is missing.
- The diff contains no secrets, local machine data, runtime output, debug artifacts, or accidental large files.
- Ignored files such as local configuration, `.env` files, logs, caches, and output directories are not force-added.
- `git diff --cached --check` succeeds.

If there is no staged diff after this audit, do not create a commit.

### 5. Create One Focused Commit

Use a concise imperative Conventional Commit-style subject that describes the result, for example:

- `fix: handle empty gallery responses`
- `feat: add collection progress reporting`
- `test: cover candidate ranking failures`
- `docs: document local setup`
- `refactor: isolate gallery request retries`
- `chore: update repository tooling`

Create one commit for the completed user task. Add a body only when the motivation, migration impact, or verification limitation would otherwise be unclear.

### 6. Verify and Report

After committing, run:

```bash
git status --short --branch
git log -1 --oneline
```

Report the commit hash and subject, the checks that ran, and any remaining staged or unstaged changes. State explicitly that no push was performed when that distinction matters.

## Stop Conditions

Leave the changes uncommitted and report the reason when:

- implementation or required verification is incomplete;
- the task diff cannot be separated safely from pre-existing work;
- the staged snapshot contains unexpected or sensitive data;
- Git reports a conflict, hook failure, or identity/configuration error;
- there are no task-related changes to commit.

Resolve issues that are safely within the current task, then repeat the audit. Never bypass hooks or destructive safeguards merely to force a commit.
