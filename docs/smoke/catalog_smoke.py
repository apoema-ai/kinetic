"""Smoke run of the kinetic catalog CLI against a temp settings file and folder."""
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/Users/rmendes/workspace/lab/kinetic/scripts")
from kinetic import catalog  # noqa: E402

tmp = Path(tempfile.mkdtemp())
catalog.SETTINGS = tmp / "settings.json"
cat = tmp / "catalog"


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = catalog.main(list(argv))
    print(f"$ kinetic catalog {' '.join(argv)}\n  rc={rc} {out.getvalue().strip()[:300]}")
    return rc


TERMS = [{"term": t, "meaning": m, "synonyms": s, "avoid": a} for t, m, s, a in [
    ("warehouse", "warehouse facility and its pledge flow", [], []),
    ("pledge", "pledging loans to a warehouse line", [], []),
    ("asset-class", "an InvestorAssetClassName value", ["iac"], ["asset type"]),
    ("onboarding", "enabling something new end to end", [], ["onboard"]),
]]
WHAT_FOR = {
    "investor-warehouse-pledge-srvc": ["add <ASSET_CLASS> to the nightly warehouse workflow trigger",
                                       "ingest tier and origination tier for <ASSET_CLASS>"],
    "investor-mgt-srvc": ["preset investment account for <ASSET_CLASS> (data-generation context)",
                          "extend the warehouse tests to <ASSET_CLASS>",
                          "link the investment accounts to <ASSET_CLASS>"],
    "k8s-template": ["enable <ASSET_CLASS> for the asset position load processes",
                     "enable <ASSET_CLASS> for the nightly workflow processes"],
}


def change(key, repos, first):
    return {
        "deliverables": [{"key": key, "repos": repos, "prs": [], "recipe": "onboard-asset-class-warehouse-pledge"}],
        "recipes": [{"slug": "onboard-asset-class-warehouse-pledge",
                     "title": "Onboard an asset class in the investor warehouse pledge service",
                     "when": "adding a new <ASSET_CLASS> to the warehouse pledge flow",
                     "parameters": [{"name": "ASSET_CLASS", "meaning": "InvestorAssetClassName",
                                     "examples": ["HOME_SECURED", "HELOC"]}],
                     "terms": ["warehouse", "pledge", "asset-class", "onboarding"],
                     "what_for": {r: WHAT_FOR[r] for r in repos}}],
        "repos": [{"repo": r, "org": "Credify", "terms": {"warehouse": [key], "asset-class": [key]}} for r in repos],
        "terms": TERMS if first else [],
    }


run("show")
run("set", "--dir", str(cat), "--create")
batch = [("INV-24468", list(WHAT_FOR)), ("INV-24150", list(WHAT_FOR)),
         ("INV-24153", ["investor-warehouse-pledge-srvc", "investor-mgt-srvc"])]
for i, (key, repos) in enumerate(batch):
    f = tmp / f"changes-{key}.json"
    f.write_text(json.dumps(change(key, repos, i == 0)))
    run("apply", "--changes", str(f))
run("apply", "--changes", str(tmp / "changes-INV-24468.json"))
run("ledger", "--keys", "INV-24468", "INV-99999")
run("lint")
print("\n--- index.md ---\n" + (cat / "index.md").read_text())
print("--- recipe ---\n" + (cat / "recipes" / "onboard-asset-class-warehouse-pledge.md").read_text().split("---\n", 2)[2])
