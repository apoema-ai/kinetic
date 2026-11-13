# Kinetic bare repos Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let kinetic keep one saved folder of bare clones, use it as a `discover` source, refresh matching clones before relying on them, clone missing repos bare into it, and cut run worktrees from `origin/<base>`. Unset means no behavior change.

**Architecture:** A new stdlib script `scripts/kinetic/bare.py` (`detect`, `set`, `show`, `list`, `clone`, `refresh`) holds all deterministic work. `gitops.create_worktree` bases a bare repo's worktree on `origin/<base>`. `discover.scan` and `detect_repos.propose` learn to read bare clones. Three thin user-only skills wrap the script, and `skills/discover/SKILL.md` gains the bare-folder steps.

**Tech Stack:** Python 3.9 stdlib only, `unittest`, markdown skills.

**Spec:** [docs/specs/kinetic-bare-repos-design.md](../specs/kinetic-bare-repos-design.md). Read it before any task; section numbers below refer to its Design sections.

## Global Constraints

- Python 3.9 stdlib only. Every subcommand prints JSON on stdout; errors go to stderr with exit 1, as in `discover.py`.
- `kinetic <module>` finds modules by file stem, so `scripts/kinetic/bare.py` is `kinetic bare` with no registration.
- Settings file: `~/.config/kinetic/settings.json` (`discover.SETTINGS`). New key `bare_dir`: a string, absolute real path. Every function that reads or writes it takes `path=None` defaulting to `discover.SETTINGS`, so tests pass temp paths. Writes keep every other key, go through `discover._write` (atomic), and read through `config._load` first so bad JSON raises `config.ConfigError` and nothing is written.
- A bare repo is recognized exactly as `setup-bare-repos/scripts/bare_repos_config.py` does: `HEAD` file, `objects/` and `refs/` dirs, no `.git` entry, and `bare = true` in `config` (tabs stripped).
- Refresh is `git -C <clone> fetch origin --prune` and nothing else; no local branch is ever moved.
- Clone follows `checkout-ticket-repos` step 4A: clone bare, `git config remote.origin.fetch "+refs/heads/*:refs/remotes/origin/*"`, `git fetch origin`, `git branch --set-upstream-to=origin/<default> <default>`.
- Skill text: no `AskUserQuestion`, `SendMessage`, `run_in_background`, no concrete model names in bodies, no `${CLAUDE_PLUGIN_ROOT}`, `PYTHONPATH` or `python3 -m kinetic`. Frontmatter parses with `yaml.safe_load`. The three new skills are user-only: `disable-model-invocation: true` and `triggers: [user]`. `tests/test_skill_text.py` enforces this.
- Version: bump `.claude-plugin/plugin.json` from `0.4.0` to `0.5.0` in Task 1.
- Git:
  - Work on branch `kinetic-bare-repos`, created from `main`. Task 1 commits the spec and this plan with its code.
  - Stage by explicit path only.
  - Commit messages: `kinetic-bare-repos: <summary>`. No co-author trailer, no mention of Claude.
- Tests: full suite `PYTHONPATH=scripts python3 -m unittest discover -s tests` (baseline 2026-11-13: 526 tests, OK, 13 skipped). One module: `PYTHONPATH=scripts python3 -m unittest tests.test_<name> -k <pattern>`.
- Test fixtures build local repos only: a normal repo as the "remote", then `git clone --bare <path>`. No test touches the network or `gh`.

## Review Focus

1. **`bare_dir` saved but the folder was deleted or moved:** `show` still prints it, `list` returns `[]`, `clone` raises `ValueError` naming the folder; nothing crashes. Test `test_missing_bare_dir_lists_nothing_and_clone_refuses` in Task 1 and Task 2.
2. **One clone in a refresh fails (no `origin`, unreachable URL):** the others still refresh; the failed one reports `ok: false` with git's stderr. Test `test_refresh_reports_failure_and_continues` in Task 2.
3. **A bare clone whose `HEAD` names a branch that has no `origin/<branch>` yet (empty remote, or fetch never ran):** `create_worktree` raises `RuntimeError` with git's message instead of silently basing on the stale local branch. Test `test_bare_repo_missing_origin_base_raises` in Task 3.
4. **`--base origin/main` passed for a bare repo:** not doubled to `origin/origin/main`. Test `test_bare_repo_keeps_explicit_origin_prefix` in Task 3.
5. **A folder in the scanned root that only looks bare (has `HEAD`, `objects`, `refs` but `bare = false`, or is a normal `.git` dir):** not listed as a bare clone. Test `test_is_bare_rejects_lookalikes` in Task 1.

---

### Task 1: `bare.py`: setting, recognition, `detect`, `set`, `show`, `list`

**Files:**
- Create: `scripts/kinetic/bare.py`
- Modify: `.claude-plugin/plugin.json` (version `0.5.0`)
- Add: `docs/specs/kinetic-bare-repos-design.md`, `docs/plan/kinetic-bare-repos-plan.md` (already written; commit them here)
- Test: `tests/test_bare.py` (new)

**Interfaces:**
- Produces: `bare.is_bare(path) -> bool`.
- Produces: `bare.show(path=None) -> str | None` (the saved `bare_dir`, or `None`). Raises `config.ConfigError` if `bare_dir` exists and is not a string.
- Produces: `bare.set_dir(d: str, create: bool = False, path=None) -> str`. Saves `os.path.realpath(os.path.expanduser(d))` as `bare_dir` and returns it. Raises `ValueError("not a directory: <d>")` when missing and `create` is false; with `create`, makes it (`parents=True`).
- Produces: `bare.default_branch(clone) -> str | None` (`git -C <clone> symbolic-ref --short HEAD`).
- Produces: `bare.list_clones(bare_dir) -> list[dict]`, each `{"name", "path", "remote", "default_branch"}`, sorted by name, bare children only. A missing `bare_dir` returns `[]`.
- Produces: `bare.detect(cwd, path=None, home=None) -> dict` with keys `saved` (str or null), `candidates` (up to 5 `{"path", "source", "bare_repo_count"}`), `recommendation` (`{"path", "reason"}` or null). `home` defaults to `Path.home()`. Recommendation order: saved `bare_dir` (reason `"already saved"`); else the container of the bare repo that `cwd` belongs to (`git rev-parse --path-format=absolute --git-common-dir`, then its parent when that is bare); else the scanned folder with the most bare repos (`SCAN_ROOTS = workspace, code, src, dev, projects, repos, git` under `home`, depth 3, `SKIP_DIRS = node_modules, Library, target, build, dist, .git`, dot dirs skipped except `.bare`); else `bare_repos_dir` from `<home>/.claude/bare-repos.local.md` front matter, which is also always added as a candidate with source `"~/.claude/bare-repos.local.md"` when present. Paths in output are absolute (no `~`).
- Produces: CLI `kinetic bare detect [--cwd P]`, `kinetic bare set --dir P [--create]`, `kinetic bare show` (prints `{"bare_dir": ...}`; exit 1 when unset), `kinetic bare list` (exit 1 with a stderr message when unset).
- Note: `bare.py` imports `discover` for `SETTINGS`, `_write` and `_real`. `discover` must never import `bare` at module level (Task 4 imports it inside a function).

- [ ] **Step 1: Create the branch**

```bash
git -C ~/workspace/lab/kinetic switch -c kinetic-bare-repos main
```

The untracked spec and plan come along.

- [ ] **Step 2: Write the failing tests** in `tests/test_bare.py`. Module helpers: `make_remote(path)` (a normal repo on `main` with one commit, gpgsign off, as in `test_gitops.make_repo`) and `make_bare(remote, dest)` (`git clone --bare <remote> <dest>`). `setUp` makes a realpath temp dir, a settings path inside it, and a `home` dir.

```python
def test_is_bare_rejects_lookalikes(self):
    make_remote(self.tmp / "remote")
    make_bare(self.tmp / "remote", self.tmp / "b" / "api")
    fake = self.tmp / "b" / "fake"
    for d in ("objects", "refs"):
        (fake / d).mkdir(parents=True)
    (fake / "HEAD").write_text("ref: refs/heads/main\n")
    (fake / "config").write_text("[core]\n\tbare = false\n")
    self.assertTrue(bare.is_bare(self.tmp / "b" / "api"))
    self.assertFalse(bare.is_bare(fake))
    self.assertFalse(bare.is_bare(self.tmp / "remote"))       # normal checkout
    self.assertFalse(bare.is_bare(self.tmp / "remote" / ".git"))  # inside a checkout

def test_set_and_show_keep_other_keys(self):
    self.settings.write_text(json.dumps({"repo_roots": ["/x"], "tracker": "jira"}))
    d = self.tmp / "bares"; d.mkdir()
    self.assertIsNone(bare.show(path=self.settings))
    self.assertEqual(bare.set_dir(str(d), path=self.settings), str(d))
    self.assertEqual(bare.show(path=self.settings), str(d))
    data = json.loads(self.settings.read_text())
    self.assertEqual((data["repo_roots"], data["tracker"]), (["/x"], "jira"))

def test_set_refuses_missing_dir_unless_create(self):
    with self.assertRaises(ValueError):
        bare.set_dir(str(self.tmp / "nope"), path=self.settings)
    self.assertFalse(self.settings.exists())
    out = bare.set_dir(str(self.tmp / "nope"), create=True, path=self.settings)
    self.assertTrue(Path(out).is_dir())

def test_set_never_overwrites_malformed_settings(self):
    self.settings.write_text("{not json")
    with self.assertRaises(config.ConfigError):
        bare.set_dir(str(self.tmp), path=self.settings)
    self.assertEqual(self.settings.read_text(), "{not json")

def test_list_returns_bare_children_with_remote_and_default_branch(self):
    make_remote(self.tmp / "remote")
    make_bare(self.tmp / "remote", self.tmp / "b" / "api")
    (self.tmp / "b" / "notes").mkdir()
    out = bare.list_clones(str(self.tmp / "b"))
    self.assertEqual([c["name"] for c in out], ["api"])
    self.assertEqual(out[0]["remote"], str(self.tmp / "remote"))
    self.assertEqual(out[0]["default_branch"], "main")

def test_missing_bare_dir_lists_nothing_and_clone_refuses(self):
    self.assertEqual(bare.list_clones(str(self.tmp / "gone")), [])

def test_detect_precedence(self):
    # scan finds <home>/workspace/master/.bare with 2 clones, local.md names another folder
    ...
    out = bare.detect(str(self.tmp), path=self.settings, home=self.home)
    self.assertEqual(out["recommendation"]["path"], str(scanned))
    self.assertIn(str(hinted), [c["path"] for c in out["candidates"]])
    # cwd inside a worktree of a bare clone wins over scan
    out = bare.detect(str(worktree), path=self.settings, home=self.home)
    self.assertEqual(out["recommendation"]["path"], str(worktree_container))
    # saved wins over everything
    bare.set_dir(str(hinted), path=self.settings)
    out = bare.detect(str(worktree), path=self.settings, home=self.home)
    self.assertEqual(out["recommendation"], {"path": str(hinted), "reason": "already saved"})

def test_cli_show_exits_1_when_unset(self):
    with mock.patch.object(bare, "SETTINGS", self.settings):
        self.assertEqual(bare.main(["show"]), 1)
```

Fill the `...` in `test_detect_precedence` with the fixture: two `make_bare` clones under `<home>/workspace/master/.bare`, a `<home>/.claude/bare-repos.local.md` whose front matter has `bare_repos_dir: <hinted>`, and a third bare clone in a separate container `<tmp>/other/x` with `worktree = git -C <tmp>/other/x worktree add <tmp>/wt main`, so `worktree_container` is `<tmp>/other` and differs from the scanned folder. `bare.main` reads `bare.SETTINGS` (a module alias of `discover.SETTINGS`) so the CLI test can patch it.

- [ ] **Step 3: Run them to see them fail**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_bare`
Expected: FAIL (`ModuleNotFoundError: kinetic.bare` or `ImportError`).

- [ ] **Step 4: Implement** the functions and the four CLI subcommands in `scripts/kinetic/bare.py`, porting `is_bare_repo`, `scan_for_bare_containers`, `cwd_container` and `parse_config` from the original script (dropping `tilde`, `derive_layout`, `write`, `link`). Bump `plugin.json` to `0.5.0`.

- [ ] **Step 5: Run the module, then the full suite**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_bare`, then `PYTHONPATH=scripts python3 -m unittest discover -s tests`
Expected: OK both times.

- [ ] **Step 6: Commit**

```bash
git -C ~/workspace/lab/kinetic add scripts/kinetic/bare.py tests/test_bare.py .claude-plugin/plugin.json docs/specs/kinetic-bare-repos-design.md docs/plan/kinetic-bare-repos-plan.md
git -C ~/workspace/lab/kinetic commit -m "kinetic-bare-repos: bare.py setting, detect, set, show and list"
```

---

### Task 2: `bare clone` and `bare refresh`

**Files:**
- Modify: `scripts/kinetic/bare.py`
- Test: `tests/test_bare.py`

**Interfaces:**
- Consumes: `bare.show`, `bare.is_bare`, `bare.default_branch` (Task 1).
- Produces: `bare.clone(bare_dir: str, repo: str | None = None, url: str | None = None, name: str | None = None) -> dict` returning `{"name", "path", "default_branch"}`. Exactly one of `repo` (`<org>/<name>`, cloned with `gh repo clone <org>/<name> <dest> -- --bare`, name taken from after the `/`) or `url` plus `name` (cloned with `git clone --bare <url> <dest>`). Raises `ValueError` when `bare_dir` is not a directory, when `<bare_dir>/<name>` exists, or when the arguments are not one of those two forms; raises `RuntimeError(stderr)` when any git or gh step fails. After cloning: set the fetch refspec, `fetch origin`, set the default branch's upstream to `origin/<default>`.
- Produces: `bare.refresh(bare_dir: str, names: list[str] | None = None) -> list[dict]`, one `{"name", "ok", "advanced", "error"}` per clone in input order (all bare clones by name when `names` is `None`). `advanced` is a list of `{"ref", "from", "to"}` for each `refs/remotes/origin/*` whose sha changed (`from` null for a new ref; a pruned ref appears with `to` null). A name with no bare clone gives `ok: false, error: "no bare clone named <n> in <bare_dir>"`. Runs at most 4 fetches at once (`concurrent.futures.ThreadPoolExecutor(max_workers=4)`).
- Produces: CLI `kinetic bare clone (--repo ORG/NAME | --url U --name N)` and `kinetic bare refresh [--name N ...]`. Both read `bare_dir` from settings and exit 1 with a stderr message when it is unset. `refresh` prints `{"results": [...]}` and exits 1 when any result has `ok: false`, 0 otherwise.

- [ ] **Step 1: Write the failing tests** in `tests/test_bare.py`:

```python
def test_clone_by_url_configures_refspec_fetch_and_upstream(self):
    make_remote(self.tmp / "remote")
    (self.tmp / "b").mkdir()
    out = bare.clone(str(self.tmp / "b"), url=str(self.tmp / "remote"), name="api")
    dest = self.tmp / "b" / "api"
    self.assertEqual(out, {"name": "api", "path": str(dest), "default_branch": "main"})
    self.assertTrue(bare.is_bare(dest))
    self.assertEqual(git(dest, "config", "--get", "remote.origin.fetch"),
                     "+refs/heads/*:refs/remotes/origin/*")
    self.assertEqual(git(dest, "rev-parse", "origin/main"), git(self.tmp / "remote", "rev-parse", "main"))
    self.assertEqual(git(dest, "rev-parse", "--abbrev-ref", "main@{upstream}"), "origin/main")

def test_clone_refuses_existing_target_and_bad_args(self):
    make_remote(self.tmp / "remote")
    (self.tmp / "b" / "api").mkdir(parents=True)
    with self.assertRaises(ValueError):
        bare.clone(str(self.tmp / "b"), url=str(self.tmp / "remote"), name="api")
    with self.assertRaises(ValueError):
        bare.clone(str(self.tmp / "b"), url=str(self.tmp / "remote"))   # no name
    with self.assertRaises(ValueError):
        bare.clone(str(self.tmp / "b"), repo="acme/api", url="x", name="api")

def test_missing_bare_dir_lists_nothing_and_clone_refuses(self):
    # extend the Task 1 test
    with self.assertRaises(ValueError):
        bare.clone(str(self.tmp / "gone"), url=str(self.tmp / "remote"), name="api")

def test_clone_by_repo_calls_gh_with_bare(self):
    with mock.patch.object(bare.subprocess, "run") as run:
        run.side_effect = fake_gh_then_git  # gh creates a bare clone from a local remote
        bare.clone(str(self.tmp / "b"), repo="acme/api")
    self.assertEqual(run.call_args_list[0].args[0][:4], ["gh", "repo", "clone", "acme/api"])
    self.assertEqual(run.call_args_list[0].args[0][-2:], ["--", "--bare"])

def test_refresh_reports_advanced_refs_and_leaves_local_branch(self):
    make_remote(self.tmp / "remote")
    (self.tmp / "b").mkdir()
    bare.clone(str(self.tmp / "b"), url=str(self.tmp / "remote"), name="api")
    dest = self.tmp / "b" / "api"
    old = git(dest, "rev-parse", "main")
    commit_file(self.tmp / "remote", "b.txt", "b\n", "second")
    new = git(self.tmp / "remote", "rev-parse", "main")
    [r] = bare.refresh(str(self.tmp / "b"), ["api"])
    self.assertEqual((r["ok"], r["error"]), (True, None))
    self.assertEqual(r["advanced"], [{"ref": "refs/remotes/origin/main", "from": old, "to": new}])
    self.assertEqual(git(dest, "rev-parse", "main"), old)   # local branch untouched

def test_refresh_reports_failure_and_continues(self):
    # two clones; point one's origin at a path that does not exist
    ...
    out = bare.refresh(str(self.tmp / "b"), ["api", "web", "nope"])
    self.assertEqual([r["ok"] for r in out], [True, False, False])
    self.assertTrue(out[1]["error"])
    self.assertIn("no bare clone named nope", out[2]["error"])

def test_cli_refresh_exits_1_on_any_failure(self):
    ...
```

`fake_gh_then_git` is a small helper in the test module: for a `gh` argv it runs `git clone --bare <local remote> <dest>` itself and returns a completed process; for anything else it calls the real `subprocess.run`. Import `git` and `commit_file` from `tests.test_gitops` or copy them.

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_bare -k clone -k refresh`
Expected: FAIL (`AttributeError: module 'kinetic.bare' has no attribute 'clone'`).

- [ ] **Step 3: Implement** `clone`, `refresh` and their CLI subcommands. `advanced` comes from `git for-each-ref --format='%(refname) %(objectname)' refs/remotes/origin` before and after the fetch.

- [ ] **Step 4: Run the module, then the full suite**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_bare`, then the full suite.
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git -C ~/workspace/lab/kinetic add scripts/kinetic/bare.py tests/test_bare.py
git -C ~/workspace/lab/kinetic commit -m "kinetic-bare-repos: bare clone and refresh"
```

---

### Task 3: Worktrees from `origin/<base>` on a bare clone

**Files:**
- Modify: `scripts/kinetic/gitops.py:22-28` (`create_worktree`)
- Test: `tests/test_gitops.py`

**Interfaces:**
- Produces: `gitops.create_worktree(bare_or_repo, dest, branch, base)` unchanged in signature. When `git -C <repo> rev-parse --is-bare-repository` prints `true` and `base` does not start with `origin/`, the base used is `origin/<base>`. Non-bare repos and an existing branch behave exactly as today.

- [ ] **Step 1: Write the failing tests** in a new `BareWorktreeTests` class in `tests/test_gitops.py`. `setUp`: `make_repo(remote)`, `git clone --bare remote bare`, set the fetch refspec and fetch (as `bare.clone` does), then `commit_file(remote, ...)` and `git -C bare fetch origin --prune` so `origin/main` is ahead of the stale local `main`.

```python
def test_bare_repo_worktree_starts_from_origin_base(self):
    gitops.create_worktree(self.bare, self.tmp / "wt", "kinetic/R/integration", "main")
    self.assertEqual(git(self.tmp / "wt", "rev-parse", "HEAD"), git(self.remote, "rev-parse", "main"))
    self.assertNotEqual(git(self.bare, "rev-parse", "main"), git(self.remote, "rev-parse", "main"))

def test_bare_repo_keeps_explicit_origin_prefix(self):
    gitops.create_worktree(self.bare, self.tmp / "wt", "kinetic/R/integration", "origin/main")
    self.assertEqual(git(self.tmp / "wt", "rev-parse", "HEAD"), git(self.remote, "rev-parse", "main"))

def test_bare_repo_reuses_existing_branch(self):
    git(self.bare, "branch", "kinetic/R/integration", "main")   # at the stale local main
    gitops.create_worktree(self.bare, self.tmp / "wt", "kinetic/R/integration", "main")
    self.assertEqual(git(self.tmp / "wt", "rev-parse", "HEAD"), git(self.bare, "rev-parse", "main"))

def test_bare_repo_missing_origin_base_raises(self):
    with self.assertRaises(RuntimeError):
        gitops.create_worktree(self.bare, self.tmp / "wt", "kinetic/R/integration", "develop")

def test_cleanup_branch_d_on_bare_clone_after_squash_merge(self):
    # pins cleanup's fallback (skills/cleanup/SKILL.md step 4) on a bare clone:
    # branch -d refuses against the stale local main; the tip still equals the
    # recorded PR head, so the headRefOid rule applies
    gitops.create_worktree(self.bare, self.tmp / "wt", "kinetic/R/integration", "main")
    commit_file(self.tmp / "wt", "c.txt", "c\n", "work")
    head = git(self.tmp / "wt", "rev-parse", "HEAD")
    git(self.bare, "worktree", "remove", str(self.tmp / "wt"))
    r = subprocess.run(["git", "-C", str(self.bare), "branch", "-d", "kinetic/R/integration"],
                       capture_output=True, text=True)
    self.assertNotEqual(r.returncode, 0)
    self.assertEqual(git(self.bare, "rev-parse", "kinetic/R/integration"), head)
```

The existing non-bare worktree tests in `test_gitops.py` stay as they are and prove the normal path is unchanged.

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_gitops -k Bare`
Expected: `test_bare_repo_worktree_starts_from_origin_base` and `test_bare_repo_missing_origin_base_raises` FAIL (the worktree starts at the stale local `main`; `develop` raises for the wrong reason or not at all). The cleanup test may already pass; it pins behavior.

- [ ] **Step 3: Implement** the bare check in `create_worktree`.

- [ ] **Step 4: Run the module, then the full suite**

Expected: OK.

- [ ] **Step 5: Commit**

```bash
git -C ~/workspace/lab/kinetic add scripts/kinetic/gitops.py tests/test_gitops.py
git -C ~/workspace/lab/kinetic commit -m "kinetic-bare-repos: cut worktrees of a bare clone from origin/<base>"
```

---

### Task 4: `discover scan` and `detect_repos` read bare clones

**Files:**
- Modify: `scripts/kinetic/discover.py` (`_item`, `scan`)
- Modify: `scripts/kinetic/detect_repos.py` (`propose`, `_has_test_target`)
- Test: `tests/test_discover.py`, `tests/test_detect.py`

**Interfaces:**
- Consumes: `bare.is_bare`, `bare.default_branch` (Task 1), imported inside the functions that need them (`from kinetic import bare`), never at module level of `discover.py`.
- Produces: every `scan` item gains `"bare": bool`. A direct child of a root that is a bare repo is listed with `bare: true`; its `remote` comes from `git -C <clone> config --get remote.origin.url` as today. A root that is itself a bare repo is listed as that one repo.
- Produces: `detect_repos.propose(repo_path)` unchanged in signature. For a bare clone it reads the file list with `git -C <clone> ls-tree --name-only <ref>` and the Makefile with `git -C <clone> show <ref>:Makefile`, where `<ref>` is `origin/<default_branch>` when that ref exists, else `HEAD`. Same `MARKERS` order and same output.

- [ ] **Step 1: Write the failing tests.**

In `tests/test_discover.py` (add a bare clone of `api` under `self.root` in the test itself):

```python
def test_scan_lists_bare_child_with_bare_flag(self):
    subprocess.run(["git", "clone", "-q", "--bare", str(self.root / "api"), str(self.root / "svc.git")], check=True)
    items = {i["name"]: i for i in discover.scan([str(self.root)], central=self.repos_json)}
    self.assertTrue(items["svc.git"]["bare"])
    self.assertFalse(items["web"]["bare"])
    self.assertEqual(items["svc.git"]["remote"], str(self.root / "api"))

def test_scan_root_that_is_a_bare_repo(self):
    ...
    self.assertEqual([i["path"] for i in discover.scan([str(bare_root)], central=self.repos_json)], [str(bare_root)])
```

`_git_init` makes repos with no commits, so give the source a commit before cloning (or build the source with `test_gitops.make_repo`).

In `tests/test_detect.py`:

```python
def test_propose_reads_markers_from_bare_clone(self):
    src = self.d / "src"; make_repo(src)            # from test_gitops
    commit_file(src, "pom.xml", "<project/>", "pom")
    subprocess.run(["git", "clone", "-q", "--bare", str(src), str(self.d / "b")], check=True)
    self.assertEqual(propose(self.d / "b"), {"verify": "mvn -q verify", "marker": "pom.xml"})

def test_propose_reads_makefile_test_target_from_bare_clone(self):
    ...
    self.assertEqual(propose(self.d / "b"), {"verify": "make test", "marker": "Makefile"})
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_discover tests.test_detect -k bare`
Expected: FAIL (`KeyError: 'svc.git'` or `'bare'`; `propose` returns `{"verify": None, ...}`).

- [ ] **Step 3: Implement** the scan branch for bare children and roots, the `bare` key on every item, and the bare path in `propose`. Existing tests that compare whole `scan` items need `"bare": False` added to their expected dicts.

- [ ] **Step 4: Run the full suite**

Expected: OK.

- [ ] **Step 5: Commit**

```bash
git -C ~/workspace/lab/kinetic add scripts/kinetic/discover.py scripts/kinetic/detect_repos.py tests/test_discover.py tests/test_detect.py
git -C ~/workspace/lab/kinetic commit -m "kinetic-bare-repos: scan and detect_repos read bare clones"
```

---

### Task 5: Skills `bare-setup`, `bare-clone`, `bare-refresh` and README

**Files:**
- Create: `skills/bare-setup/SKILL.md`, `skills/bare-clone/SKILL.md`, `skills/bare-refresh/SKILL.md`
- Modify: `tests/test_skill_text.py:21` (`USER_ONLY_SKILLS`; its comment says "five", update it to match)
- Modify: `README.md` (`## Commands`, `## Skills and agents`, `## Configuration`)

**Interfaces:**
- Consumes: CLI from Tasks 1 and 2.
- Produces: `USER_ONLY_SKILLS = ("ask", "bare-clone", "bare-refresh", "bare-setup", "cleanup", "implement", "init", "run", "status")`.

Frontmatter of each, following `skills/cleanup/SKILL.md`: `name`, a `description` (quoted if it contains `: `), `model: sonnet`, `disable-model-invocation: true`, `triggers: [user]`, and `argument-hint` (`"[folder]"`, `"<org>/<name> ... | <url> <name>"`, `"[repo ...]"`).

Bodies (spec section 5), each a few lines over the script:
- `bare-setup`: run `kinetic bare detect --cwd <cwd>`; ask once with the harness's question tool (as `discover` does): recommended path first with its reason, then "Current folder", then "Other"; with a folder in the arguments, skip the question; say if a folder is already saved and ask keep or change. Create a missing folder only after the user agrees (`--create`). Run `kinetic bare set --dir <folder>`. Report the saved path and that `discover` now uses it as a source and refreshes matching clones (saving it is consent for those fetches). Never writes `~/.claude` files.
- `bare-clone`: for each argument, `kinetic bare clone --repo <org>/<name>` or `--url <url> --name <name>`. If `kinetic bare show` exits 1, tell the user to run `/kinetic:bare-setup` and stop. Report each path and default branch, or the error.
- `bare-refresh`: `kinetic bare refresh` with `--name` for each argument (all clones when none). Print a table: repo, fetched or failed, what advanced (`ref from..to`, short shas) or the error. Say once that local branches are never moved.

- [ ] **Step 1: Update `USER_ONLY_SKILLS`** and run `PYTHONPATH=scripts python3 -m unittest tests.test_skill_text`
Expected: OK still (the list names folders that do not exist yet; the test iterates over existing skills).

- [ ] **Step 2: Write the three skills.**

- [ ] **Step 3: Run the skill-text tests**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_skill_text`
Expected: OK. A failure names the file and the forbidden text.

- [ ] **Step 4: Update the README.** One line per skill under `## Commands` and `## Skills and agents`; under `## Configuration`, the `bare_dir` key in `settings.json`: what it holds, that unset means no change, that saving it lets `discover` fetch matching clones, and that run worktrees are cut from `origin/<base>`.

- [ ] **Step 5: Run the full suite.** Expected: OK.

- [ ] **Step 6: Commit**

```bash
git -C ~/workspace/lab/kinetic add skills/bare-setup/SKILL.md skills/bare-clone/SKILL.md skills/bare-refresh/SKILL.md tests/test_skill_text.py README.md
git -C ~/workspace/lab/kinetic commit -m "kinetic-bare-repos: bare-setup, bare-clone and bare-refresh skills"
```

---

### Task 6: `discover` skill uses the bare folder

**Files:**
- Modify: `skills/discover/SKILL.md`
- Test: `tests/test_skill_text.py` (new test in `SkillTextTest`)

**Interfaces:**
- Consumes: `kinetic bare show`, `list`, `refresh`, `clone` (Tasks 1, 2); `bare: true` in `discover scan` (Task 4); `origin/<base>` in `gitops worktree` (Task 3).

Edits, all conditional on `kinetic bare show` exiting 0 (spec section 2):
- **Intro network sentence (line 22):** replace with: the only network calls are the step 4 GitHub calls, made with the user's permission, and fetching bare clones that match a candidate, which the saved bare folder already covers. Reading any other source sends nothing off the machine.
- **Mode: confirm-only:** after the scan match, also match against `kinetic bare list`. Before step 7's worktrees, refresh every confirmed repo that has a bare clone.
- **Step 2:** also run `kinetic bare show`; the bare folder is never asked about in step 3.
- **Step 4:** a new first bullet **Bare clones**: `kinetic bare list`, matched like base folders, with the README read through `git -C <clone> show origin/<default_branch>:README.md`. For every candidate that matches a bare clone, run `kinetic bare refresh --name <n> ...` before reading its contents, asking nothing; a failure does not stop the step and is kept for step 6. A repo registered in `repos.json` at a normal checkout keeps that path even when a bare clone also exists; an unregistered repo found both in a base folder and in the bare folder uses the bare clone.
- **Step 6:** add location `bare clone`, and `bare clone, not refreshed: <error>` for a failed refresh.
- **Step 7.1:** with a bare folder, the question is "Clone them into <bare_dir>?" and the action `kinetic bare clone --repo <org>/<name>`; without it, unchanged.
- **Step 7.2:** a bare clone is registered under its bare path.
- **Step 7.4:** before the worktrees, refresh every confirmed bare-clone repo not refreshed earlier in this run of the skill. For a repo registered at a bare clone, the base branch is `base_branch` from its `repos.json` entry, else the clone's `default_branch` from `kinetic bare list`, never the literal `main` (spec section 4). The `kinetic gitops worktree ... --base <base>` line stays as it is.
- **Rules:** "Never clone, search GitHub, or read a source the user did not approve" gains: fetching a bare clone that matches a candidate is approved by the saved bare folder.

- [ ] **Step 1: Write the failing test** in `tests/test_skill_text.py`:

```python
def test_discover_uses_bare_folder(self):
    text = (ROOT / "skills" / "discover" / "SKILL.md").read_text()
    for needle in ("kinetic bare show", "kinetic bare list", "kinetic bare refresh",
                   "kinetic bare clone --repo", "not refreshed:", "default_branch"):
        self.assertIn(needle, text)
    self.assertNotIn("only the GitHub calls in step 4 reach the network", text)
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTHONPATH=scripts python3 -m unittest tests.test_skill_text -k bare`
Expected: FAIL (`'kinetic bare show' not found`).

- [ ] **Step 3: Edit `skills/discover/SKILL.md`** as listed above.

- [ ] **Step 4: Run the full suite.** Expected: OK, with the final count reported.

- [ ] **Step 5: Commit**

```bash
git -C ~/workspace/lab/kinetic add skills/discover/SKILL.md tests/test_skill_text.py
git -C ~/workspace/lab/kinetic commit -m "kinetic-bare-repos: discover reads, refreshes and clones into the bare folder"
```
