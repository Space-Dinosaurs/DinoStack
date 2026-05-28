# THIRD_PARTY_NOTICES.md seed

**Status:** Seed list produced by `dependency-auditor` agent on 2026-05-27. Intended as the raw attribution data for the eventual `THIRD_PARTY_NOTICES.md` once IR-2's copyright-holder string is finalized.

**Not a shippable file.** This is a planning artifact under `docs/planning/`. The final `THIRD_PARTY_NOTICES.md` lives at repo root and ships with the OSS launch.

## Context

- **Project license (outbound):** Apache-2.0 (per IR-2).
- **Dep ecosystems scanned:** npm (2 manifests — `scripts/`, `.opencode/`), pip (`evals/requirements.txt`).
- **Total unique deps:** 178 (1 Python + 177 npm across both trees, deduplicated).
- **License-compatibility verdict:** All deps Apache-2.0 compatible (MIT / Apache-2.0 / ISC / BSD-2-Clause / BSD-3-Clause / MIT-0 / 0BSD / Python-2.0). No blocking findings.

## Open follow-ups before this becomes `THIRD_PARTY_NOTICES.md`

1. **Copyright-holder string** for the project's own NOTICE header — pending IR-2 ownership resolution.
2. **Apache NOTICE propagation sweep** — the 19 Apache-2.0 deps listed below may carry their own `NOTICE` files in their distribution; Apache §4(d) requires reproducing them. Walk `node_modules/<apache-dep>/NOTICE` for each once a build env is stood up. Apache-2.0 deps in the inventory: `@puppeteer/browsers`, `puppeteer-core`, `chromium-bidi`, `webdriver-bidi-protocol`, `devtools-protocol` (Chromium Authors); `mathjax-full`, `mhchemparser`, `mj-context-menu`, `speech-rule-engine` (MathJax / related); `b4a`, `bare-events`, `bare-fs`, `bare-os`, `bare-path`, `bare-stream`, `bare-url`, `events-universal`, `text-decoder` (Holepunch); `detect-libc` (Lovell Fuller); `kubernetes-types` (Lyra Naeseth).
3. **Python-side CVE scan** — `pip-audit` not installed during the audit; rerun with `pip install pip-audit && pip-audit -r evals/requirements.txt` to close the gap. PyYAML's only widely-discussed CVE (CVE-2020-14343) was fixed in 5.4; current floor `>=6.0` is unaffected.
4. **CVE remediation (independent of this file):**
   - HIGH `tmp <0.2.6` (GHSA-ph9p-34f9-6g65) — `npm audit fix` in `scripts/` or pin `tmp>=0.2.6` via `overrides`.
   - MODERATE `uuid 13.0.0` (GHSA-w5hq-g745-h8pq) — upgrade `.opencode/` to `uuid@13.0.1`.

## Seed attribution list

Format: `- <package> (<version>) — <license> — <copyright holder or "see upstream">`

```
- @babel/code-frame (7.29.0) — MIT — The Babel Team
- @babel/helper-validator-identifier (7.28.5) — MIT — The Babel Team
- @csstools/postcss-is-pseudo-class (5.0.3) — MIT-0 — Jonathan Neal
- @csstools/selector-resolve-nested (3.1.0) — MIT-0 — see upstream
- @csstools/selector-specificity (5.0.0) — MIT-0 — see upstream
- @marp-team/marp-cli (4.3.1) — MIT — Marp team
- @marp-team/marp-core (4.3.0) — MIT — Marp team
- @marp-team/marpit-svg-polyfill (2.1.0) — MIT — Marp team
- @marp-team/marpit (3.2.1) — MIT — Marp team
- @msgpackr-extract/msgpackr-extract-darwin-x64 (3.0.3) — MIT — Kris Zyp
- @opencode-ai/plugin (1.14.19) — MIT — see upstream
- @opencode-ai/sdk (1.14.19) — MIT — see upstream
- @puppeteer/browsers (2.13.2) — Apache-2.0 — The Chromium Authors
- @standard-schema/spec (1.1.0) — MIT — Colin McDonnell
- @tootallnate/quickjs-emscripten (0.23.0) — MIT — see upstream
- @types/node (25.9.0) — MIT — see upstream
- @types/yauzl (2.10.3) — MIT — see upstream
- @xmldom/xmldom (0.9.10) — MIT — see upstream
- accepts (1.3.8) — MIT — see upstream
- agent-base (7.1.4) — MIT — Nathan Rajlich
- ansi-regex (5.0.1) — MIT — Sindre Sorhus
- ansi-styles (4.3.0) — MIT — Sindre Sorhus
- argparse (2.0.1) — Python-2.0 — see upstream
- ast-types (0.13.4) — MIT — Ben Newman
- b4a (1.8.1) — Apache-2.0 — Holepunch
- bare-events (2.8.3) — Apache-2.0 — Holepunch
- bare-fs (4.7.1) — Apache-2.0 — Holepunch
- bare-os (3.9.1) — Apache-2.0 — Holepunch
- bare-path (3.0.0) — Apache-2.0 — Holepunch
- bare-stream (2.13.1) — Apache-2.0 — Holepunch
- bare-url (2.4.3) — Apache-2.0 — Holepunch
- basic-ftp (5.3.1) — MIT — Patrick Juchli
- batch (0.6.1) — MIT — TJ Holowaychuk
- buffer-crc32 (0.2.13) — MIT — Brian J. Brennan
- callsites (3.1.0) — MIT — Sindre Sorhus
- chokidar (4.0.3) — MIT — Paul Miller
- chromium-bidi (14.0.0) — Apache-2.0 — The Chromium Authors
- cliui (8.0.1) — ISC — Ben Coe
- color-convert (2.0.1) — MIT — Heather Arthur
- color-name (1.1.4) — MIT — DY
- commander (13.1.0) — MIT — TJ Holowaychuk
- commander (2.20.3) — MIT — TJ Holowaychuk
- commander (8.3.0) — MIT — TJ Holowaychuk
- cosmiconfig (9.0.1) — MIT — Daniel Fischer
- cross-spawn (7.0.6) — MIT — André Cruz
- cssesc (3.0.0) — MIT — Mathias Bynens
- cssfilter (0.0.10) — MIT — Zongmin Lei
- data-uri-to-buffer (6.0.2) — MIT — Nathan Rajlich
- debug (2.6.9) — MIT — TJ Holowaychuk
- debug (4.4.3) — MIT — Josh Junon
- degenerator (5.0.1) — MIT — Nathan Rajlich
- depd (1.1.2) — MIT — Douglas Christopher Wilson
- detect-libc (2.1.2) — Apache-2.0 — Lovell Fuller
- devtools-protocol (0.0.1608973) — BSD-3-Clause — The Chromium Authors
- effect (4.0.0-beta.48) — MIT — see upstream
- emoji-regex (8.0.0) — MIT — Mathias Bynens
- end-of-stream (1.4.5) — MIT — Mathias Buus
- entities (4.5.0) — BSD-2-Clause — Felix Boehm
- env-paths (2.2.1) — MIT — Sindre Sorhus
- error-ex (1.3.4) — MIT — see upstream
- escalade (3.2.0) — MIT — Luke Edwards
- escape-html (1.0.3) — MIT — see upstream
- escodegen (2.1.0) — BSD-2-Clause — see upstream
- esm (3.2.25) — MIT — John-David Dalton
- esprima (4.0.1) — BSD-2-Clause — Ariya Hidayat
- estraverse (5.3.0) — BSD-2-Clause — see upstream
- esutils (2.0.3) — BSD-2-Clause — see upstream
- events-universal (1.0.1) — Apache-2.0 — Holepunch
- extract-zip (2.0.1) — BSD-2-Clause — max ogden
- fast-check (4.7.0) — MIT — Nicolas DUBIEN
- fast-fifo (1.3.2) — MIT — Mathias Buus
- fd-slicer (1.1.0) — MIT — Andrew Kelley
- find-my-way-ts (0.1.6) — MIT — Tomas Della Vedova
- get-caller-file (2.0.5) — ISC — Stefan Penner
- get-stream (5.2.0) — MIT — Sindre Sorhus
- get-uri (6.0.5) — MIT — Nathan Rajlich
- highlight.js (11.11.1) — BSD-3-Clause — Josh Goebel
- http-errors (1.8.1) — MIT — Jonathan Ong
- http-proxy-agent (7.0.2) — MIT — Nathan Rajlich
- https-proxy-agent (7.0.6) — MIT — Nathan Rajlich
- import-fresh (3.3.1) — MIT — Sindre Sorhus
- inherits (2.0.4) — ISC — see upstream
- ini (6.0.0) — ISC — GitHub Inc.
- ip-address (10.2.0) — MIT — Beau Gunderson
- is-arrayish (0.2.1) — MIT — Qix
- is-fullwidth-code-point (3.0.0) — MIT — Sindre Sorhus
- isexe (2.0.0) — ISC — Isaac Z. Schlueter
- js-tokens (4.0.0) — MIT — Simon Lydell
- js-yaml (4.1.1) — MIT — Vladimir Zapparov
- json-parse-even-better-errors (2.3.1) — MIT — Kat Marchán
- katex (0.16.47) — MIT — see upstream
- kubernetes-types (1.30.0) — Apache-2.0 — Lyra Naeseth
- lines-and-columns (1.2.4) — MIT — Brian Donovan
- linkify-it (5.0.0) — MIT — see upstream
- lodash.kebabcase (4.1.1) — MIT — John-David Dalton
- lru-cache (7.18.3) — ISC — Isaac Z. Schlueter
- markdown-it-front-matter (0.2.4) — MIT — ParkSB
- markdown-it (14.1.1) — MIT — see upstream
- mathjax-full (3.2.2) — Apache-2.0 — see upstream
- mdurl (2.0.0) — MIT — see upstream
- mhchemparser (4.2.1) — Apache-2.0 — Martin Hensel
- mime-db (1.52.0) — MIT — see upstream
- mime-types (2.1.35) — MIT — see upstream
- mitt (3.0.1) — MIT — see upstream
- mj-context-menu (0.6.1) — Apache-2.0 — see upstream
- ms (2.0.0) — MIT — see upstream
- ms (2.1.3) — MIT — see upstream
- msgpackr-extract (3.0.3) — MIT — Kris Zyp
- msgpackr (1.11.10) — MIT — Kris Zyp
- multipasta (0.2.7) — MIT — Tim Smart
- nanoid (3.3.12) — MIT — Andrey Sitnik
- negotiator (0.6.3) — MIT — see upstream
- netmask (2.1.1) — MIT — Olivier Poitrey
- node-gyp-build-optional-packages (5.2.2) — MIT — Mathias Buus
- once (1.4.0) — ISC — Isaac Z. Schlueter
- pac-proxy-agent (7.2.0) — MIT — Nathan Rajlich
- pac-resolver (7.0.1) — MIT — Nathan Rajlich
- parent-module (1.0.1) — MIT — Sindre Sorhus
- parse-json (5.2.0) — MIT — Sindre Sorhus
- parseurl (1.3.3) — MIT — see upstream
- path-key (3.1.1) — MIT — Sindre Sorhus
- pend (1.2.0) — MIT — Andrew Kelley
- picocolors (1.1.1) — ISC — Alexey Raspopov
- postcss-nesting (13.0.2) — MIT-0 — see upstream
- postcss-selector-parser (7.1.1) — MIT — see upstream
- postcss (8.5.14) — MIT — Andrey Sitnik
- progress (2.0.3) — MIT — TJ Holowaychuk
- proxy-agent (6.5.0) — MIT — Nathan Rajlich
- proxy-from-env (1.1.0) — MIT — Rob Wu
- pump (3.0.4) — MIT — Mathias Buus Madsen
- punycode.js (2.3.1) — MIT — Mathias Bynens
- puppeteer-core (24.43.1) — Apache-2.0 — The Chromium Authors
- pure-rand (8.4.0) — MIT — Nicolas DUBIEN
- readdirp (4.1.2) — MIT — Thorsten Lorenz
- require-directory (2.1.1) — MIT — Troy Goode
- resolve-from (4.0.0) — MIT — Sindre Sorhus
- semver (7.8.0) — ISC — GitHub Inc.
- serve-index (1.9.2) — MIT — Douglas Christopher Wilson
- setprototypeof (1.2.0) — ISC — Wes Todd
- shebang-command (2.0.0) — MIT — Kevin Mårtensson
- shebang-regex (3.0.0) — MIT — Sindre Sorhus
- smart-buffer (4.2.0) — MIT — Josh Glazebrook
- socks-proxy-agent (8.0.5) — MIT — Nathan Rajlich
- socks (2.8.9) — MIT — Josh Glazebrook
- source-map-js (1.2.1) — BSD-3-Clause — Valentin 7rulnik Semirulnik
- source-map (0.6.1) — BSD-3-Clause — Nick Fitzgerald
- speech-rule-engine (4.1.4) — Apache-2.0 — see upstream
- statuses (1.5.0) — MIT — see upstream
- streamx (2.25.0) — MIT — Mathias Buus
- string-width (4.2.3) — MIT — Sindre Sorhus
- strip-ansi (6.0.1) — MIT — Sindre Sorhus
- tar-fs (3.1.2) — MIT — Mathias Buus
- tar-stream (3.2.0) — MIT — Mathias Buus
- teex (1.0.1) — MIT — Mathias Buus
- text-decoder (1.2.7) — Apache-2.0 — Holepunch
- tmp (0.2.5) — MIT — KARASZI István
- toidentifier (1.0.1) — MIT — Douglas Christopher Wilson
- toml (4.1.1) — MIT — Michelle Tilley
- tslib (2.8.1) — 0BSD — Microsoft Corp.
- typed-query-selector (2.12.2) — MIT — Pig Fang
- uc.micro (2.1.0) — MIT — see upstream
- undici-types (7.24.6) — MIT — see upstream
- util-deprecate (1.0.2) — MIT — Nathan Rajlich
- uuid (13.0.0) — MIT — see upstream
- webdriver-bidi-protocol (0.4.1) — Apache-2.0 — The Chromium Authors
- which (2.0.2) — ISC — Isaac Z. Schlueter
- wicked-good-xpath (1.3.0) — MIT — Google Inc.
- wrap-ansi (7.0.0) — MIT — Sindre Sorhus
- wrappy (1.0.2) — ISC — Isaac Z. Schlueter
- ws (8.20.1) — MIT — Einar Otto Stangvik
- xss (1.0.15) — MIT — Zongmin Lei
- y18n (5.0.8) — ISC — Ben Coe
- yaml (2.8.3) — ISC — Eemeli Aro
- yargs-parser (21.1.1) — ISC — Ben Coe
- yargs (17.7.2) — MIT — see upstream
- yauzl (2.10.0) — MIT — Josh Wolfe
- zod (3.25.76) — MIT — Colin McDonnell
- zod (4.1.8) — MIT — Colin McDonnell
- pyyaml (>=6.0) — MIT — Ingy döt Net and contributors
```
