# docs/slides/

Marp deck sources (`*-slides.md`) and their built `.html` output for the DinoStack methodology's presentation decks.

## Gotchas

Dark-theme reskin gotcha: Marp `theme: default` leaks high-specificity light styles. The 15 `*-slides.md` decks were reskinned to the DinoStack "Iridium" dark look (palette and fonts sourced from `docs/index.html`: `#02050C` canvas plus cyan/violet radial aura, Orbitron headings, Nunito Sans body, JetBrains Mono code, `#18E0FF` primary). Two non-obvious traps when overriding Marp's default theme via the inline `style:` block:

1. Table rows render white - Marp's `section table tr { background: var(--bgColor-default) }` (white) out-specifies a bare `tr` selector. Fix: match its shape exactly with `table tr { background: transparent }` plus `table tr:nth-child(2n) { background: rgba(255,255,255,0.03) }`.
2. Syntax-highlighted code is dark-on-dark - language-tagged fences (yaml/json/bash) get highlight.js tokens whose GitHub-theme vars stay in their light branch because `section` keeps `color-scheme: light`. Fix: add `color-scheme: dark` to the `section` rule, which flips all `--color-prettylights-syntax-*` to their legible dark-mode values.

Plain untagged fences have no tokens, so screenshot a *highlighted* code slide when QA-ing. Edit the `.md` only, then regenerate via `bash scripts/build-slides.sh` (idempotent; the `slides-sync.yml` CI gate enforces `.md` to `.html` sync). The canonical Iridium base block lives identically in all 15 decks' frontmatter.
