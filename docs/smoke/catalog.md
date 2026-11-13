# Smoke: repo catalog

Status: **not run** by the agent. The local guardrails blocked running a script from this clone (its origin is not a trusted org), so the run is left to the user.

## Script run (not run)

[`catalog_smoke.py`](catalog_smoke.py) uses a temp settings file and folder (it never touches `~/.config/kinetic/`) and runs:

1. `show`: expect rc 1, `null`.
2. `set --dir <tmp>/catalog --create`: expect the five layout entries created.
3. `apply` three hand-written change files modelled on INV-24468 and INV-24150 (all three repos) and INV-24153 (pledge-srvc and mgt-srvc only). The repo lists and what-for lines are illustrative, not read from real PRs.
4. `apply` INV-24468 again: expect rc 1, "already cataloged".
5. `ledger --keys INV-24468 INV-99999`: expect cataloged, then not cataloged.
6. `lint`: expect `{"problems": []}`.
7. Print `index.md` and the recipe. Expect one recipe, with `investor-warehouse-pledge-srvc (always, 3 of 3)`, `investor-mgt-srvc (always, 3 of 3)` and `k8s-template (usually, 2 of 3)`.

Run it from a terminal:

```bash
python3 -I docs/smoke/catalog_smoke.py
```

## Skill session (not run)

`/kinetic:catalog-setup`, then `/kinetic:catalog-refresh INV-24468 INV-24150 INV-24153`, then `/kinetic:run` on a fourth asset-class ticket, checking that `discover` lists the recipe's repos with reasons. Needs the Atlassian MCP and `gh` logged in.

The same code paths are covered by `tests/test_catalog.py` (29 tests, passing).
