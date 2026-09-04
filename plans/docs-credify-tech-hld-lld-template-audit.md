# docs.credify.tech — Most-Used HLD and Design (LLD) Templates

## Context

Audit of `~/workspace/docs.credify.tech` (Credify's internal engineering docs site,
organized as one `teams/<team>/` folder per engineering team) to identify which
templates are actually the most-used ones for two document types:

1. HLD (High-Level Design)
2. Design / Low-Level Design (LLD)

Goal: a defensible, evidence-backed answer — not a guess — plus a recommendation on
which template each category should standardize on going forward. This was a
research/audit task; nothing in `docs.credify.tech` was modified.

## Method

- Repo-wide `find`/`grep` for literal template files, per-team README/CLAUDE.md
  guidance, and actual HLD/Design documents across all 18 teams.
- Verified the two decision-critical source files directly
  (`teams/bnpl/design-template.md`, `teams/investor/README.md`).
- Cross-checked adoption by counting how many real documents reproduce each
  candidate template's header skeleton, and checked git history for recency/currency.

## Findings

### 1. HLD — no in-repo template file; investor's `hld.md` is the de facto standard

- "HLD" as a document type exists **only** under `teams/investor/` — zero hits for
  "High-Level Design" / HLD headers anywhere else in the repo.
- **31 of 31** HLD documents in the entire repo live at
  `teams/investor/features/INV-XXXXX_slug/hld.md`, and nearly all reproduce the same
  header skeleton verbatim. Most recent conforming doc: 2026-08-12 (still active).
- There is no template *file* checked into the repo. The shape is enforced by:
  - Prose contract in `teams/investor/README.md` ("File Content Contracts → `hld.md` —
    Phase 2": architecture overview, services touched, data impacts, assumptions, risk
    factors, decomposition into stories, estimate with variance bands — "Load-bearing").
  - An external Claude Code plugin skill, `investor-workflow:inv-hld-writing`, which
    actually authors the doc and is what produces the consistent structure.
- Observed skeleton (repeats near-verbatim across ~31 docs). No template file exists
  to source section descriptions from, so the descriptions below are synthesized from
  the README's content contract and how the ~31 real documents actually use each
  section — useful as a starting point if this gets checked in as a real
  `hld-template.md` (see Recommendation):
  ```
  # <Title> — High-Level Design (HLD)
  *[One-line problem statement and what this HLD covers.]*

  # Summary
  *[2-4 sentence executive summary: what's being built and why, for a reader who
  won't read the rest of the doc.]*

  # Assumptions
  *[Everything taken as given that, if wrong, changes the design. Split into the
  subsections below.]*
    ### Behavior / feature clarification
    *[Product/behavioral assumptions about how the feature should work.]*
    ### Assumed code state
    *[Assumptions about existing code, schemas, or services this design builds on.]*
    ### Other assumptions
    *[Anything else assumed — timelines, team availability, third-party behavior.]*

  # Technical Approach
  *[The actual design. Split into the subsections below.]*
    ### Sketch
    *[High-level shape of the solution — components touched, new vs. modified,
    rough flow. Diagrams welcome but not required at this phase.]*
    ### Alternative(s) considered
    *[Other approaches evaluated, and why they were rejected in favor of the sketch above.]*

  # Blast Radius — Investor Sub-Domains
  *[Which investor sub-domains this touches and how far the change reaches.]*
    ### Cross-cutting impact
    *[Sub-domains or shared components affected beyond the primary one.]*
    ### Considered and ruled out
    *[Sub-domains initially suspected of being in scope but confirmed unaffected.]*

  # Services & Data Impacts
  *[Concrete inventory of what changes at the service and data layer.]*
    ### Services touched
    *[Every service that needs a code change, even a small one.]*
    ### Data impacts
    *[Schema changes, new tables/columns, migrations, data backfills.]*

  # Decomposition
  *[How this epic breaks down into stories — the input to sprint planning.]*

  # Prior Art
  *[Similar features/patterns already built elsewhere in the codebase that this
  design follows or deliberately departs from.]*

  # Cross-Team Dependencies
  *[Other teams/services whose cooperation, review, or prior changes this depends on.]*

  # Risks & Risk Factors
  *[What could go wrong, how likely, and mitigation if applicable.]*

  # Estimate
  *[Sizing with variance bands — this backs the quarterly commitment, not a rough guess.]*
    ### By sub-domain / By chunk / By milestone
    *[Break the estimate down by whichever grouping best exposes uncertainty.]*

  # Out of Scope
  *[Explicitly what this epic will NOT do, to prevent scope creep during implementation.]*

  # Open Questions
  *[Unresolved items blocking sign-off, each with an owner if possible.]*

  # Appendix A — Deferred review (optional)
  *[Findings from an `/inv-hld-reviewing` pass that were acknowledged but deferred
  rather than addressed before approval.]*
  ```
- No competing HLD convention exists anywhere else in the repo.

### 2. Design / LLD — two real contenders; `teams/bnpl/design-template.md` wins on evidence

**A. `teams/bnpl/design-template.md` — the only literal template file in the whole repo**

- Directly linked as *the* thing to use from both `teams/bnpl/README.md`
  ("please use design-template.md as basis...") and `teams/bnpl/CLAUDE.md`
  ("Key Templates → Design Template: teams/bnpl/design-template.md").
- These two files are the **only** references to `design-template.md` by name in the
  entire repo — i.e. it's explicitly documented as canonical, not just inferred.
- Adoption: **14 of 18** dated tech-design docs under `teams/bnpl/2026/q2/` and
  `.../q3/` conform closely (same header set/order, same emoji markers). Most recent
  conforming doc: 2026-08-11 (still active).
- Independently mirrored (no template file of its own) by 3 of 9 `teams/vq/specs/`
  design docs before drifting to an undocumented leaner format from 2026-06-15 on.
- Header skeleton, with the template's own in-file guidance carried over verbatim
  under each section (this is the actual explanatory text authors see when they copy
  the template, not a synthesis):
  ```
  # Tech Design Document: {short title}

  ## 🌟 Status
  *[Table: Tech Design status (not started/DRAFT/IN PROGRESS/IN REVIEW/COMPLETE),
  Epic link, Tech lead, QA, Designer, Target release.]*

  ## 🎯 Purpose
  *[The exact scope — what this doc is for and is NOT for; the audience; links to
  prerequisite reading; how this ties to the bigger product/platform picture.]*

  ## 🤔 Assumptions
  *[All assumptions relevant to the scope of this document.]*

  ## 📓 Glossary / Legends
  *[Acronyms or short-forms used throughout the doc, or a pointer to where they're
  maintained.]*

  ## 📋 Use cases
  *[The most important use cases as questions, with a pointer to the full list if
  this doc doesn't cover all of them.]*

  ## 🔗 Dependencies
  *[Up/downstream dependencies and a brief explanation of their impact.]*

  ## 🎨 Design details
  *[Use the subsections below as they fit — not all are required, some may repeat,
  some may be nested per use case. Wherever possible, list 2+ options evaluated with
  pros/cons and the recommended one.]*
    ### ⤴️ Design decisions
    *[Key decisions and their rationale — chosen option, alternatives considered, trade-offs.]*
    ### Sequence diagram
    *[Mermaid or sequencediagram.org source/image.]*
    ### Interaction / component diagram
    *[Mermaid C4 or component diagram.]*
    ### Domain model
    *[Class diagram or EER for new/changed entities.]*
    ### Data model
    *[Tables, columns, indexes, retention, partitioning.]*
    ### 📓 API contracts
    *[Sample request/response with as much detail as possible — mandatory vs.
    optional fields, HTTP response codes, etc.]*
      #### Schemas
      *[GraphQL / REST schema, wherever applicable.]*

  ## ❓ Open questions / Action items
  *[Checklist of action items, each assigned to an @owner; open questions with the
  owner responsible for resolving them.]*
    ### ✅ Next steps (optional)
    *[Follow-on work once this design is approved, if applicable.]*
  ```
- Stable since import (single commit, 2026-05-14, migrated wholesale from a prior
  `bnpl-design-docs` repo) yet still actively followed 3 months later.

**B. Investor's `design.md` — documented contract, weakly followed in practice**

- `teams/investor/README.md` defines it as three mandatory sections in one file:
  **Spec** (what/AC), **Design** (how/conventions), **Plan** (ordered tasks tagged
  `isolatable`/`serial`/`coordinated`).
- Only 9 `design.md` files exist (vs. 31 `hld.md`), and only **1 of 9** literally uses
  the `# 1. Spec / # 2. Design / … # 6. Plan` headers. The rest are bespoke
  per-author write-ups — the contract exists in prose but hasn't converged into a
  reproducible template.
- A third, undocumented pattern ("Business Requirements / Functional Requirements /
  Non-Functional Requirements / … / Jira Tickets") recurs across ~5-7 of investor's
  largest epics (e.g. `INV-21611`, `INV-22719`, `INV-22928`), but one of those docs
  explicitly states its source template lives on **Confluence**, outside this repo —
  so it can't be pointed to as an in-repo template file either.

**Verdict:** `teams/bnpl/design-template.md` is the only Design/LLD artifact that is
simultaneously (a) an actual file in the repo, (b) explicitly documented as the thing
to use, and (c) measurably and currently adopted across multiple docs.

## Summary Table

| | HLD | Design / LLD |
|---|---|---|
| Canonical in-repo template file | None (de facto standard only) | `teams/bnpl/design-template.md` |
| Explicitly linked from README/CLAUDE.md | No (prose contract only) | Yes, from two files |
| Adoption | 31/31 HLD docs (100% of all HLDs, all investor) | ~14/18 bnpl + partial vq (~17 docs, 2 teams) |
| Most recent conforming doc | 2026-08-12 | 2026-08-11 |
| Competing patterns | None | Investor's Spec/Design/Plan contract (1/9 literal); Confluence-sourced pattern (undocumented, no in-repo file); vq's later undocumented numbered format |

## Recommendation

- **For Design/LLD docs**: adopt `teams/bnpl/design-template.md` as the org-wide
  starting point. It's the only artifact that is a real, in-repo, explicitly-endorsed,
  actively-followed file — the least risky choice to point other teams at.
- **For HLD docs**: there is no in-repo file to adopt as-is. Two options:
  1. Treat investor's `hld.md` skeleton (documented above) as the de facto standard
     and formalize it by checking a template file into the repo (e.g.
     `teams/investor/hld-template.md`, mirroring how bnpl's design template is
     structured) so other teams can adopt it without depending on the
     `inv-hld-writing` Claude plugin skill.
  2. If HLD as a phase-2 artifact stays investor-specific, no action is needed —
     other teams currently have no equivalent gap they're trying to fill.
- Investor's `design.md` Spec/Design/Plan contract is real but under-followed; if the
  team wants that structure enforced consistently, it's a candidate for the same
  "check in an actual template file" fix recommended for HLD above.
