---
name: bare-refresh
description: Fetch the latest commits into the bare clones in the saved bare-repos folder, all of them or the repos named. Reports what advanced; never moves a local branch.
model: sonnet
disable-model-invocation: true
triggers: [user]
argument-hint: "[repo ...]"
---

# Kinetic bare-refresh

Fetch from origin into bare clones. Run scripts as `kinetic <module> ...`.

## 1. Run

Run `kinetic bare refresh`, adding `--name <repo>` for each argument. With no arguments it refreshes every clone in the saved folder. If it reports that no folder is saved (it exits 1 with a message on stderr), tell the user to run `/kinetic:bare-setup` and stop.

It prints `{"results": [{name, ok, advanced, error}]}` and exits 1 when any clone failed. A non-zero exit with a `results` list is a partial failure, not a crash: still print the table.

## 2. Report

One table, a row per result:

| Repo | Result | Advanced |
|---|---|---|

- Result: `fetched` when `ok`, else `failed`.
- Advanced: each entry of `advanced` as `<ref> <from>..<to>` with 7-character shas. A `from` of null is a new branch, a `to` of null a deleted one. Write `up to date` when the list is empty. For a failed clone, write the `error` instead.

Say once, after the table, that only fetching happens: local branches in the clones are never moved.
