---
name: catalog-setup
description: Choose and save the folder that holds the repo catalog (repo labels and recipes learned from merged work), so /kinetic:catalog-refresh can fill it and discovery can read it. Detects a likely folder and asks once; with a folder argument it skips the question.
model: sonnet
disable-model-invocation: true
triggers: [user]
argument-hint: "[folder]"
---

# Kinetic catalog-setup

Save the folder that holds the repo catalog as `catalog_dir` in kinetic's settings. Run scripts as `kinetic <module> ...`.

## 1. Detect

Run `kinetic catalog detect --cwd <cwd>`, with `<cwd>` the current working directory. It prints `existing_config` (the folder already saved, or null), `candidates` (each with `path` and `reason`) and `recommendation` (a path, or null).

If `existing_config` is set, say which folder it is and ask whether to keep it or change it. On keep, stop.

## 2. Choose the folder

If the arguments name a folder, use it and skip the question.

Otherwise ask once, with the harness's question tool when the profile names one (`kinetic harness` prints it under `Question tool:`; `none` means chat). Options, in this order:

1. The recommended path, with its reason. Leave it out when `recommendation` is null.
2. "Current folder": the current working directory.
3. "Other": the user types a path.

## 3. Confirm and save

Show what will be created inside the folder when it is missing: `index.md`, `terms.md`, `repos/`, `recipes/`, `ledger.json`. Existing files are never overwritten. On yes, run `kinetic catalog set --dir <folder> --create`. On no, stop.

## 4. Report

Report the saved path and what was created. Say that:

- a folder inside a git checkout is shared with whoever uses that checkout; kinetic never commits or pushes it;
- `/kinetic:catalog-refresh <keys>` fills it from merged tickets, and `discover` reads it.

Never write `~/.config/kinetic/` files with edit tools: the folder is saved only through `kinetic catalog set`.
