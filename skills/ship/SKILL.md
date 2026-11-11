---
name: ship
description: Write PR bodies, determine cross-repo merge order, and open the set of draft PRs with gh, linking siblings. Use at the ship phase of a kinetic run.
model: sonnet
---

# Ship

Write a PR body per repo integration branch, then open the set as **draft** PRs in merge order, linking the sibling PRs. This skill never invokes another skill.

The orchestrator passes `Run: <dir>` (the run directory, `<workspace>/<run-id>/`). Run scripts as `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts" python3 -m kinetic.<module> ...`. Repo paths and integration branches are in the run state (`python3 -m kinetic.state load --run <dir>`, field `repos`); `base_branch` comes from repo config (default `main`).

## Rules

- Never push to `main`, `master` or `Release*` branches; push only the integration branch.
- Open PRs only as drafts. Do not merge any PR. Do not deploy.
- The push/PR confirmation hook may prompt; that is the expected gate.

## Process

1. Get the order, upstream repos first:

```
python3 -m kinetic.gitops merge-order --run <dir>
```

It prints the ordered repo list (and errors on a dependency cycle).

2. For each repo in that order, from its repo path: write the PR body (template below) to a temp file, push the integration branch, and open the draft:

```
git push -u origin <integration-branch>
gh pr create --draft --base <base_branch> --head <integration-branch> --title "<title>" --body-file <file>
```

Collect each PR URL as it is created.

3. Siblings link each other. Since later PRs are not known when earlier ones are created, after all PRs exist update each body so its "Related PRs" list names every sibling PR with its position in the merge order and the edge type that orders it (`gh pr edit <url> --body-file <file>`). State plainly in each body: "Merge in this order: ...".

4. Report the PR URLs in merge order to the orchestrator, which records the ship approval.

## PR body template

Skip preambles and keep prose brief. Use the user's domain language from `GLOSSARY.md`.

```markdown
## Summary

<diagram, diff-sketch, or tree>

## Evidence

- **Before:** <screenshot/output/failing test run>
  **After:** <screenshot/output/passing test run>

## Merge Danger

**Door:** <one-way or two-way>

<optional: description>

**Blast Radius:** <one-word description>

<optional: potential ramifications of merge>

## Related PRs

- <sibling PR URL> (merge order N, edge: snapshot|merge|release)
```

### Summary

Pick the smallest view that makes the key point clear, placed next to the short text it supports. Keep only the calls, files, props, states and boundaries needed.

- Logic or an algorithm: pseudocode.
- Runtime control flow: a call tree.
- UI structure: a component tree, including state and module boundaries that matter.
- File responsibility or a broad refactor: a shallow file tree.
- Component interaction or data flow: Mermaid (`sequenceDiagram`).
- What changes where the surrounding shape already exists: a `diff` block matching the topic (component tree, file layout, call tree or control flow).
- Most of the block is new, or omitted context would hide ownership or order: show the whole block.

Use one or several; it is unlikely you will use all. Don't overwhelm the reader.

### Evidence

Concrete proof the change works, before and after. Screenshots are best when the change is visual. Execution evidence is next: test results and console output, showing the exact test that now fails then passes, in pseudocode. Use the run's verify logs (`verify` results in state) as the source.

### Merge Danger

Say whether it is a one-way or two-way door: two-way can be walked back, one-way (destructive or hard-to-reverse decisions) cannot, and a cheap-to-roll-back PR is lower risk. Blast radius is the scope of impact: layout shift, breakage for consumers, mobile responsiveness, a downstream repo pinned to a snapshot, and so on. Consider all possibilities.

Adapted from mattpocock/skills (pr), MIT License.
