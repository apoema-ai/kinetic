from __future__ import annotations

import json

import _common


def main(inp):
    if inp.get("stop_hook_active"):
        return
    try:
        found = _common.active_run(inp)
    except _common.state.ticket_store.TicketStoreError as e:
        # the gate cannot check verify freshness without tickets: block, never pass silently
        print(json.dumps({"decision": "block", "reason":
            f"kinetic could not read the run's tickets ({e}); fix it, then stop again"}))
        return
    if not found:
        return
    run_dir, st = found
    # the stale-verify rule lives in state.stale_verify — the same rule
    # ship_refusal applies at the CLI layer — so the gate and the ship
    # refusal can never disagree
    bad = _common.state.stale_verify(st)
    if not bad:
        return
    lines = []
    for b in bad:
        name = b["repo"] or "(outside registered repos)"
        if b["path"]:
            lines.append(f"{name}: " + _common.state.verify_command(
                run_dir, name, b["path"], b["ticket"]))
        else:
            lines.append(f"{name}: run verify for the repo you edited")
    print(json.dumps({"decision": "block", "reason":
        "Run verify: no passing verify after the last edit. " + "; ".join(lines)}))


if __name__ == "__main__":
    _common.run(main)
