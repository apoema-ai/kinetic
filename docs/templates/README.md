# Templates

Two document templates, sourced from an audit of `docs.credify.tech` (see
`~/workspace/byond/plans/docs-credify-tech-hld-lld-template-audit.md` for the full
evidence and methodology behind these picks). Placeholder text in each template is
marked `*[like this — italic, in brackets]*`; replace it with real content and delete
the markers.

## `hld-template.md` — High-Level Design

**Use for:** the *first* design pass on a new epic/feature, before any implementation
detail is settled. Answers "what are we building, roughly how, what's the blast
radius, and how big is it" — enough to get a decomposition into stories and a
commit-worthy estimate. Write this before `design-template.md`, not instead of it.

**Not for:** API contracts, data models, sequence diagrams, or anything
implementation-level — that belongs in the design doc once the HLD is approved.

**Provenance:** there is no template file for this in `docs.credify.tech` — the shape
here is reverse-engineered from 31 real `hld.md` documents under `teams/investor/`
(100% of all HLDs in that repo), which all converge on this structure by convention
(enforced by an external Claude Code plugin skill, not a checked-in file). Treat this
as a formalization of that de facto standard, not a copy of an official template.

## `design-template.md` — Tech Design Document (Design / LLD)

**Use for:** the detailed, implementation-level design once the high-level approach
(HLD, or equivalent alignment) is agreed. Covers diagrams, data model, API contracts,
and the concrete decisions an engineer needs to actually build the feature.

**Not for:** the initial "should we build this and roughly how" pass — start with the
HLD template for that, then use this one to go deep.

**Provenance:** copied from `teams/bnpl/design-template.md` in `docs.credify.tech` —
the only literal template *file* found anywhere in that repo, explicitly linked as
the thing to use from both `teams/bnpl/README.md` and `teams/bnpl/CLAUDE.md`, and
actively followed by ~14 of 18 real tech-design docs as of the audit (most recent:
2026-08-11).

## Quick pick

| If you're... | Use |
|---|---|
| Starting a new epic, need story breakdown + estimate | `hld-template.md` |
| Ready to design the actual implementation | `design-template.md` |
| A small, well-understood change | Neither — skip straight to implementation notes |
