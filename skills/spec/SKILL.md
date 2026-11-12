---
name: spec
description: Turn the grilled conversation into a spec with threat model, non-functional requirements and acceptance criteria, lint it, and publish it to the tracker or the run directory. Use at the spec phase of a kinetic run.
model: sonnet
---

# Spec

Take the current conversation context and codebase understanding and produce a spec. Do NOT interview the user; synthesize what you already know. This skill never invokes another skill.

The orchestrator passes `Run: <dir>` (the run directory, `<workspace>/<run-id>/`). Run scripts as `kinetic <module> ...`.

Resolve the tracker with `kinetic tracker resolve` (set by `/kinetic:init`; with no tracker configured it resolves to local), read the adapter file it names, and follow its operations.

## Process

1. Explore the repo to understand the current state of the codebase, if you haven't already. Use the vocabulary in `<run_dir>/docs/GLOSSARY.md` (or the repo's own) throughout the spec, and respect any ADRs in the area you're touching.

2. Sketch the seams at which you'll test the feature. Prefer existing seams to new ones, and the highest seam possible. If new seams are needed, propose them at the highest point you can. The fewer seams across the codebase, the better; the ideal number is one. Check with the user that these seams match their expectations.

3. Write the spec using the template below.

4. Lint it. Write the draft to `<run_dir>/spec.md` first, then run:

```
kinetic spec_lint <run_dir>/spec.md
```

It prints a JSON list of problems. Fix the spec and re-run until the list is empty (`[]`).

5. Publish:
   - **Tracker with remote issues**: follow the adapter's "create slice parent" operation with the spec body, and note the ticket reference at the top of `<run_dir>/spec.md`.
   - **Local**: `<run_dir>/spec.md` is the published spec.

The orchestrator then runs the spec approval gate; do not set phases or gates here.

<spec-template>

## Problem Statement

The problem the user is facing, from the user's perspective.

## Solution

The solution to the problem, from the user's perspective.

## User Stories

A LONG, numbered list covering all aspects of the feature, each in the form:

1. As an <actor>, I want a <feature>, so that <benefit>

## Implementation Decisions

- The modules that will be built/modified, and which repo each lives in
- The interfaces of those modules that will be modified
- Technical clarifications from the developer
- Architectural decisions, schema changes, API contracts, specific interactions

Do NOT include specific file paths or code snippets; they go stale quickly. Exception: if a prototype produced a snippet that encodes a decision more precisely than prose can (state machine, reducer, schema, type shape), inline the decision-rich part and note it came from a prototype.

## Testing Decisions

- What makes a good test (external behavior only, not implementation details)
- Which modules will be tested, and at which seams
- Prior art for the tests (similar tests in the codebase)

## Threat model

Assets, actors and trust boundaries, abuse cases, and the mitigation for each, taken from the grill.

## Non-functional requirements

Performance, availability, consistency and idempotency, observability, data retention and privacy, migration and rollback, compatibility.

## Acceptance criteria

A checklist of verifiable criteria (`- [ ] ...`) that together mean the feature is done.

## Out of Scope

Things that are out of scope for this spec.

## Further Notes

Anything else.

</spec-template>

The headings `## Threat model`, `## Non-functional requirements` and `## Acceptance criteria` are required, exactly as written.

Adapted from mattpocock/skills (to-spec), MIT License.
