# Kinetic: a shared folder of bare clones for discover

Status: draft for approval. Builds on [kinetic-repo-discovery-design.md](kinetic-repo-discovery-design.md). Brainstormed 2026-11-13; "Decided by the user" holds only what the user said, "My calls" holds what I chose and the user has not yet seen.

## Why

The user keeps one folder of bare git clones (today `~/workspace/master/.bare`, one `<repo>` per bare clone) and works through worktrees cut from them, set up by their personal `checkout-ticket-repos`, `refresh-bare-repos` and `setup-bare-repos` skills. Kinetic's `discover` knows none of this: it looks for normal checkouts under `repo_roots`, clones missing repos with `gh repo clone` into the first repo root, and never updates a clone, so a run can start from code that is weeks old.

## Goals

1. **One saved folder of bare clones** that kinetic reads. Unset means kinetic behaves exactly as it does today.
2. **`discover` uses that folder as a source of repos**, next to `repo_roots` and the GitHub org.
3. **A matching bare clone is refreshed before `discover` relies on it**, so what it reads, and the worktree it cuts, is current.
4. **A missing repo is cloned bare into that folder** instead of as a normal checkout.
5. **Three small skills** for using the same behavior outside a run: `/kinetic:bare-setup`, `/kinetic:bare-clone`, `/kinetic:bare-refresh`.

## Non-goals

- Managing the user's own master or per-ticket worktrees. Kinetic never touches `~/workspace/master/<repo>` or `~/workspace/<TICKET>/<repo>`.
- Fast-forwarding any local branch of a bare clone (what `/refresh-bare-repos` does to master worktrees). Kinetic has no master worktrees.
- Rebasing a run's integration branch when its base branch moves.
- Writing `~/.claude/CLAUDE.md` or `~/.claude/bare-repos.local.md`. Kinetic reads the latter once, as a hint, and never writes it.
- Converting repos already registered at a normal checkout into bare clones.
- A `doctor` check for the folder.

## Anti-goals

- Refreshing every clone in the folder (it may hold dozens; each fetch is a network call).
- `discover` calling another skill. Its `SKILL.md` forbids it, so the logic lives in a script.
- A failed fetch (VPN down, SSH agent missing) aborting the run, or being hidden from the user.
- Any change for a user who never sets the folder.

## Decided by the user

- The folder stores **bare repos**, not worktrees; worktrees are cut from them.
- `discover` treats the folder as a source of information and, when a repo found there is stale, fetches a fresh version first.
- Cloning follows `checkout-ticket-repos` step 4A: `git clone --bare`, set `remote.origin.fetch` to `+refs/heads/*:refs/remotes/origin/*`, `git fetch origin`, set the default branch's upstream to `origin/<default>`.
- Refreshing follows `refresh-bare-repos` step 3.1: `git fetch origin --prune`.
- Refresh only the clones that match a candidate, not the whole folder.
- Saving the bare folder counts as consent for `discover` to fetch the matching clones. `discover` does not ask again per run.
- Skill names: `bare-setup`, `bare-clone`, `bare-refresh`.
- The design document lives in `docs/specs/`.

## Design

### 1. Setting (`scripts/kinetic/bare.py`, new, auto-listed by `kinetic <module>`)

`~/.config/kinetic/settings.json` gains one key, `bare_dir` (a string). `discover.remember` already preserves unknown keys; `discover settings` is unchanged, `bare` reads and writes the new key itself, with the same atomic write and bad-JSON refusal.

Subcommands, all printing JSON, stdlib only (Python 3.9):

| Command | Does |
|---|---|
| `kinetic bare detect [--cwd P]` | Candidate folders and one recommendation: the saved `bare_dir`; else the folder holding the bare repos around `--cwd`; else the folder holding the most bare repos under `~/workspace`, `~/code`, `~/src`, `~/dev`, `~/projects`, `~/repos`, `~/git` (depth 3, skipping `node_modules`, `Library`, `target`, `build`, `dist`, `.git`); also `bare_repos_dir` from `~/.claude/bare-repos.local.md` when that file exists. Logic ported from `setup-bare-repos/scripts/bare_repos_config.py`. |
| `kinetic bare set --dir P` | Validates `P` is a directory (creates it only with `--create`), saves it as `bare_dir`. |
| `kinetic bare show` | Prints `bare_dir` or `null`; exit 1 when unset. |
| `kinetic bare list` | Bare clones in `bare_dir`: name, path, remote URL, default branch. |
| `kinetic bare clone --repo <org>/<name>` or `--url U --name N` | Clones into `<bare_dir>/<name>` as above. With `--repo` it runs `gh repo clone <org>/<name> <dir> -- --bare` so `gh`'s configured protocol is honoured; with `--url` it runs `git clone --bare`. Refuses when the target exists. |
| `kinetic bare refresh [--name N ...]` | `git -C <clone> fetch origin --prune` per named clone (all clones when no `--name`, used only by the skill), a few at a time. Per repo: `{name, ok, advanced: [{ref, from, to}], error}`. |

A "bare repo" is recognized as the original script does: `HEAD`, `objects/` and `refs/` present, no `.git` entry, `bare = true` in `config`.

### 2. `discover` (`skills/discover/SKILL.md`, `scripts/kinetic/discover.py`, `scripts/kinetic/detect_repos.py`)

All new behavior is conditional on `kinetic bare show` succeeding.

- **Step 2 (look for base folders):** `kinetic bare show` is read next to `kinetic discover settings`; the bare folder is not asked about again.
- **Step 4 (search):** `kinetic bare list` joins the sources. Each bare clone is matched against the run the same way as a base-folder repo (name, README first lines, remote). Reading a README means `git -C <clone> show origin/<default>:README.md`, since a bare clone has no files.
- **Refresh, in step 4, agent only, no question:** for every candidate that matches a bare clone, run `kinetic bare refresh --name <n> ...` before reading its contents. A failure does not stop the step. Saving `bare_dir` is the user's consent to these fetches.
- **Consent rule in `SKILL.md`:** the current text says only the step-4 GitHub calls reach the network, and only with the user's permission. It changes to: the only network calls are the step-4 GitHub calls (with the user's permission) and fetching bare clones that match a candidate (covered by the saved `bare_dir`). Reading any other source still sends nothing off the machine. The skill-text tests are checked against the new wording.
- **Step 6 (confirm):** candidates gain the location `bare clone`; one that failed to refresh shows `bare clone, not refreshed: <reason>`. The user's approval of the list is also the decision to go on with it.
- **Step 7, repo not cloned:** the question becomes "Clone them into `<bare_dir>`?" and the action `kinetic bare clone --repo <org>/<name>`. Without the setting it stays `gh repo clone` into the first repo root.
- **Step 7, before worktrees:** refresh every confirmed repo that has a bare clone and was not refreshed earlier in this run of the skill (a repo the user added at confirmation, or any repo in `Mode: confirm-only`).
- **`discover scan`** also lists a direct child that is a bare repo, with `bare: true`. It is registered under its bare path in `repos.json`.
- **`detect_repos`** accepts a bare clone and finds its marker files with `git ls-tree --name-only origin/<default>` instead of looking at the filesystem.

### 3. Worktrees (`scripts/kinetic/gitops.py`)

`create_worktree` learns whether `--repo` is a bare clone (`git rev-parse --is-bare-repository`). When it is and `--base` has no `origin/` prefix, the base becomes `origin/<base>`. Run worktrees stay at `<run_dir>/worktrees/<repo>` and `<run_dir>/worktrees/<repo>-<id>`; the `discover` and `run` guides keep their `--base <base>` text unchanged, so crash recovery in `build-loop.md` also gets the fresh base.

### 4. Base branch of a bare clone

`config.resolve` merges `<repo path>/.kinetic.json`, which a bare path cannot have. For a repo registered at a bare clone, `discover` takes the base branch from the central `repos.json` entry if it has `base_branch`, else from the bare clone's own default branch (`HEAD`), never the literal `main`. `verify` and `pin` already resolve against worktree paths, so they keep seeing `.kinetic.json`.

### 5. Skills

Three new `skills/<name>/SKILL.md`, each a few lines over the script, none naming a Claude-only tool, concrete model or `${CLAUDE_PLUGIN_ROOT}` (`tests/test_skill_text.py` enforces this):

- `bare-setup`: runs `kinetic bare detect`, asks where the folder goes (recommended path first, current folder, other), confirms, then `kinetic bare set`.
- `bare-clone`: `<org>/<name>` or URL arguments, runs `kinetic bare clone`.
- `bare-refresh`: optional repo names, runs `kinetic bare refresh`, prints a table of repo, fetched or failed, what advanced.

### 6. Cleanup and `ship`

No change. `cleanup` already runs `git -C <clone path> worktree remove / branch -d / worktree prune`; a bare clone's local default branch is stale, so `branch -d` may refuse a merged integration branch and `cleanup` falls to its existing tip-equals-`headRefOid` rule. A test pins this.

## Testing

`tests/test_bare.py` (new, temp `HOME`, local bare repos as remotes): detect precedence, set and show, clone configures refspec and upstream, refresh reports advanced refs and a failure, list skips non-bare folders. Additions to `test_discover.py` (scan sees a bare child), `test_detect.py` (markers through `ls-tree`), `test_gitops.py` (bare repo gets `origin/<base>`, normal repo unchanged, an existing branch is reused), `test_skill_text.py` (new skill names added to its user-only list, no forbidden text), and a cleanup test on a bare clone.

## My calls (unconfirmed by the user)

- `bare_dir` lives in kinetic's own `settings.json`, so it works on every harness; the `~/.claude/CLAUDE.md` link step is dropped.
- All three skills are user-only (`disable-model-invocation: true`, `triggers: [user]`); discover never calls them.
- Refresh is fetch and prune only; no local branch is fast-forwarded.
- A fetch failure is reported at confirmation, not asked about mid-search.
- `origin/<base>` is applied inside `gitops`, only for bare repos, so non-bare behavior is untouched.
- A repo registered at a normal checkout keeps that path even if a bare clone also exists; an unregistered repo found in both places prefers the bare clone.
- The default-branch upstream step from `checkout-ticket-repos` is kept for parity, though kinetic itself does not need it.

## Left to the builder

- Exact JSON field names, exit codes and the parallelism of `refresh`.
- Whether `list` and `detect` share one scanner.
- Wording of the three skills and the README "Commands" and "Configuration" entries.
