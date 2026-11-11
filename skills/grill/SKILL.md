---
name: grill
description: Relentless interview that sharpens a plan or design, covering threat model and non-functional requirements, and maintains GLOSSARY.md and ADRs as it goes. Use at the grill phase of a kinetic run.
model: sonnet
---

# Grill

Interview the user relentlessly until you reach a shared understanding, and write the domain language and key decisions down as they crystallise.

The orchestrator passes `Run: <dir>` (the run directory, `<workspace>/<run-id>/`) and the ref being grilled. Run scripts as `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts" python3 -m kinetic.<module> ...`. This skill never invokes another skill.

## Interview rules

Map the plan as a **design tree**: every decision branches into the decisions that hang off it.

Work the tree in **rounds**. The **frontier** is every decision whose prerequisites are already settled: the questions you can ask _now_ without guessing at answers you haven't heard yet. Ask the whole frontier in one round: number each question and give your recommended answer. Then wait for the user's answers before the next round.

Format a round like so:

```
Q1 - <question title>: <question body, might be multiple paragraphs, including multiple choices>

Recommended: <your recommended answer>

---

Q2 - <question title>: <question body>

Recommended: <your recommended answer>
```

Word each question so "yes" accepts your recommended answer.

Each round the user answers reshapes the tree: settled decisions push the frontier outward and unblock questions that depended on them. Recompute the frontier and ask the next round. A question whose answer depends on another question still open in this round belongs to a _later_ round.

Finding _facts_ is your job, never the user's. When a question needs a fact from the environment (code, config, docs, the tracker), look it up yourself with read-only tools; don't ask the user for anything you could look up. The _decisions_ are the user's: put each to them and wait.

The session is done when the frontier is empty: every branch of the design tree visited, nothing left silently assumed. Do not act on it until the user confirms you have reached a shared understanding.

## What the tree must cover

Beyond behavior and scope, every grill covers these branches, each with a recommended answer:

- **Threat model**: assets worth protecting, actors and trust boundaries, how each could be abused (authn/authz, data exposure, injection, money movement, abuse of retries or replays), and the mitigation for each.
- **Non-functional requirements**: performance and load, availability, consistency and idempotency, observability, data retention and privacy, migration and rollback, compatibility with existing consumers.
- **Which repos are touched** and how they depend on each other (this feeds the later ticket breakdown).

## Domain model, written as you go

Build and sharpen the project's domain model while interviewing:

- **Challenge against the glossary**: when the user uses a term that conflicts with `GLOSSARY.md`, call it out immediately.
- **Sharpen fuzzy language**: when a term is vague or overloaded, propose a precise canonical term ("account": Customer or User?).
- **Discuss concrete scenarios**: invent edge-case scenarios that force the user to be precise about boundaries between concepts.
- **Cross-reference with code**: when the user states how something works, check whether the code agrees and surface contradictions.

### GLOSSARY.md

Update `GLOSSARY.md` the moment a term is resolved; do not batch. Create it lazily when the first term is resolved. Format:

```md
# {Context Name}

{One or two sentences on what this context is and why it exists.}

## Language

**Order**:
{One or two sentence description of what it IS.}
_Avoid_: Purchase, transaction
```

Be opinionated: pick one word per concept and list the rest under `_Avoid_`. Only terms specific to this project's context, not general programming concepts. No implementation details: it is a glossary, not a spec or scratch pad. If a `GLOSSARY-MAP.md` exists at the root the repo has several contexts; put each term in the context's own `GLOSSARY.md`, asking if unclear.

### ADRs

Offer an ADR only when all three are true: the decision is **hard to reverse**, **surprising without context**, and **the result of a real trade-off**. Otherwise skip it. ADRs live in `docs/adr/` as `0001-slug.md`, numbered by scanning for the highest existing number; create the directory lazily. Format: a title and 1-3 sentences (context, decision, why). Optional sections (Status, Considered Options, Consequences) only when they add real value.

## Record the outcome

When the user confirms shared understanding, finish with a short summary of the decisions, threat model and NFRs. Record any deliberate trade-off the user ruled on:

```
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/scripts" python3 -m kinetic.state add-ruling --run <dir> --what "..." --why "..." --cost "..."
```

The orchestrator owns phase changes and gates; do not set them here.

Adapted from mattpocock/skills (grill-with-docs, grilling, domain-modeling), MIT License.
