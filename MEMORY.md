# Memory

## Project Conventions

- **2026-04-28:** This project uses `main` as the sole integration branch. Do not use `develop`/`development` branching model for this repository - all feature/fix/chore work branches from `main` and merges back to `main`.

## Decisions

- **2026-05-18: Adapter-drift CI gate is advisory-only (descoped from hard block).** `adapter-sync.yml` makes content/adapter drift CI-visible (red X) on every PR but is NOT a required status check. Drift is CI-visible but not hard-blocked at merge. To upgrade to a hard merge block: add the `check-adapter-sync` job as a required status check on `main` in repo settings. Accepted by operator 2026-05-18.

- **2026-07-02: DS-48 risk-overclassification tuning shipped.** Wave 1 (#374) loop-cost levers (simple/targeted mechanical metric -> 1-round Skeptic cap + Tier-2 small-unit nudge + mechanical skip-architect/planner; no gate loosened). Lever 9 (#375/#376) collapsed the redundant session-wide `preset` alias into the single `profile` knob (presence-aware resolver + 30-day legacy shim; removal tracked in DS-61). Wave 2 (#388) added a `relaxed`-profile-only bounded 2-3-file Low override + downward tie-break counterweight (opt-in; default/strict unchanged). Wave 2 file/line thresholds are conservative first-ship values, to be tuned against real pod examples.

## Slides (Marp decks, docs/slides/)

- **2026-07-01:** Never include `"mode": "opt-in"` in doc/adapter example JSON unless demonstrating opt-in activation - it silently disables the entire methodology on repos without an `agentic-engineering: opt-in` marker; show only the field being demonstrated (e.g. `{ "profile": "relaxed" }`) or use `"mode": "opt-out"`. (session)

- **2026-06-11: Dark-theme reskin gotcha — Marp `theme: default` leaks high-specificity light styles.** The 15 `*-slides.md` decks were reskinned to the DinoStack "Iridium" dark look (palette/fonts sourced from `docs/index.html`: `#02050C` canvas + cyan/violet radial aura, Orbitron headings, Nunito Sans body, JetBrains Mono code, `#18E0FF` primary). Two non-obvious traps when overriding Marp's default theme via the inline `style:` block: (1) **Table rows render white** — Marp's `section table tr { background: var(--bgColor-default) }` (white) out-specifies a bare `tr` selector. Fix: match its shape exactly — `table tr { background: transparent }` + `table tr:nth-child(2n) { background: rgba(255,255,255,0.03) }`. (2) **Syntax-highlighted code is dark-on-dark** — language-tagged fences (```yaml/json/bash) get highlight.js tokens whose GitHub-theme vars stay in their light branch because `section` keeps `color-scheme: light`. Fix: add `color-scheme: dark` to the `section` rule (flips all `--color-prettylights-syntax-*` to their legible dark-mode values). Plain ``` fences have no tokens, so screenshot a *highlighted* code slide when QA-ing. Edit the `.md` only, then regenerate via `bash scripts/build-slides.sh` (idempotent; `slides-sync.yml` CI gate enforces .md↔.html sync). Canonical Iridium base block now lives identically in all 15 decks' frontmatter.
