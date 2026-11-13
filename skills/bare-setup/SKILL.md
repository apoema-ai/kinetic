---
name: bare-setup
description: Choose and save the folder that holds your bare git clones, so kinetic discovery can use it as a source and refresh its clones. Detects likely folders and asks once; with a folder argument it skips the question.
model: sonnet
disable-model-invocation: true
triggers: [user]
argument-hint: "[folder]"
---

# Kinetic bare-setup

Save the folder that holds your bare clones (one bare repo per subfolder) as `bare_dir` in kinetic's settings. Run scripts as `kinetic <module> ...`.

## 1. Detect

Run `kinetic bare detect --cwd <cwd>`, with `<cwd>` the current working directory. It prints `saved` (the folder already saved, or null), `candidates` (each with `path`, `source` and `bare_repo_count`) and `recommendation` (`path` and `reason`, or null).

If `saved` is set, say which folder it is and ask whether to keep it or change it. On keep, stop.

## 2. Choose the folder

If the arguments name a folder, use it and skip the question.

Otherwise ask once, with the harness's question tool when the profile names one (`kinetic harness` prints it under `Question tool:`; `none` means chat). Options, in this order:

1. The recommended path, with its `reason`. Leave it out when `recommendation` is null.
2. "Current folder": the current working directory.
3. "Other": the user types a path.

## 3. Save

If the chosen folder does not exist, say so and create it only after the user agrees: `kinetic bare set --dir <folder> --create`. Otherwise run `kinetic bare set --dir <folder>`. A path that is not a directory without `--create` is an error; report it and ask again.

## 4. Report

Report the saved path. Say that `discover` now uses this folder as a source and refreshes (fetches) the clones that match its repos: saving the folder is the consent for those fetches. Run `kinetic bare list` and mention how many clones the folder holds, if any. Use `/kinetic:bare-clone` to add more.

Never write `~/.claude` files or `~/.config/kinetic/` files with edit tools: the folder is saved only through `kinetic bare set`.
