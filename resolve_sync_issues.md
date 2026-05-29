# Git Sync and Fork Resolution Guide

This document explains why you were facing daily Git synchronization issues and provides the exact commands you need to resolve them whenever they occur.

---

## 🔍 The Root Causes of Your Issue

### 1. Divergent Histories (Local vs. Upstream)
- **Local Branch (`main`)**: You are committing your daily training work (Day 6, Day 7, Day 8, Day 9) directly to your `main` branch.
- **Upstream Branch (`upstream/main`)**: The course instructor (Anilmidna) is releasing new labs, directories, and updates to the `upstream/main` branch.
- **Result**: Because both branches are adding new commits independently, their histories have diverged. Git cannot simply fast-forward your branch.

### 2. Missing Pull Default Strategy
When you tried `git pull upstream main`, Git failed with:
`fatal: Need to specify how to reconcile divergent branches.`
This is because Git needs you to explicitly specify whether to **merge** or **rebase** when branches have diverged.

### 3. "Discard Commits" in GitHub UI
When you tried to sync your fork via the GitHub UI, it warned you:
`Discard 17 commits to make this branch match the upstream repository.`
- **WARNING**: Clicking "Discard commits" in the UI will **permanently delete** your local work from the `main` branch. This is because GitHub UI's sync feature is designed for simple mirrors that don't have local work on `main`. **Never use "Discard commits" if you have written code on that branch.**

### 4. Active Database Files committed by accident
You had active MySQL database files tracked in Git inside `day9/labs/openmetadata_sandbox/docker-volume/db-data/`.
- Every time Docker ran, it modified these binary database files.
- This caused huge merge conflict noise and slowed down your repository.
- *(Note: We have successfully untracked these files and added them to `.gitignore` so they won't bother you again!)*

---

## 🛠️ Step-by-Step Commands to Sync Your Fork (Keeping Your Work)

Whenever the instructor pushes new updates and you need to pull them without losing your lab work, follow these steps in your terminal:

### Step 1: Clean/Stash your local working directory
Before doing any merge, ensure you have committed your current day's work or stashed it so your workspace is clean.
```bash
git stash
```

### Step 2: Configure Git's default pull strategy
Tell Git to use the **merge** strategy by default when pulling:
```bash
git config pull.rebase false
```

### Step 3: Fetch the latest updates from the instructor
```bash
git fetch upstream
```

### Step 4: Merge upstream changes, favoring your completed work on conflict
Because you and the instructor both add the same lab files, merging normally creates dozens of `add/add` conflicts. To automatically resolve all file conflicts in favor of your completed work, use the `-X ours` strategy option:
```bash
git merge -X ours upstream/main
```
*Note: If Git detects a directory rename (like when Day 9 was moved to `case_study/`), it might ask you to add a relocated file. Simply add it using `git add <filepath>` and then run `git commit` to complete the merge.*

### Step 5: Restore your stashed active files
```bash
git stash pop
```

### Step 6: Push the synchronized branch to your GitHub fork
```bash
git push origin main
```

---

## 💡 Best Practices for the Future

1. **Keep database folders out of Git**: Always add any local runtime folders, log files, or database caches to `.gitignore` immediately. (We have already added `docker-volume/db-data/` to your `.gitignore`).
2. **If you must work on `main`**: Since the course dashboard checks your submissions on your fork's `main` branch, you *must* have your work there. Therefore, using `git merge -X ours upstream/main` is the safest, conflict-free way to merge upstream changes into your `main` branch.
