/**
 * Purpose: Generates CHANGELOG.md and docs/changelog.html from merged GitHub
 *          PRs by querying the GitHub CLI. Full regeneration on every run -
 *          idempotent given the same set of merged PRs.
 *
 * Public API: Run as a CLI script: node scripts/generate-changelog.js [--limit <n>]
 *
 * Upstream deps: Node.js built-ins only (child_process, fs, path);
 *                gh CLI (must be authenticated); git remote (auto-detected by gh).
 *
 * Downstream consumers: .github/workflows/changelog-publish.yml (nightly CI),
 *                       docs/changelog.html (published to docs site).
 *
 * Failure modes: exits 1 if `gh pr list` fails (unauthenticated, no network,
 *                wrong directory). Does NOT fail on zero PRs - writes empty
 *                changelog gracefully. Safe to retry; no side effects beyond
 *                writing the two output files.
 *
 * Performance: ~2-5 s for a typical repo (one gh network call + JSON parse +
 *              synchronous file writes). The --limit cap bounds memory usage.
 *
 * NOTE: The inlined CSS below is copied from docs/index.html and will drift if
 *       that file's CSS variables, fonts, or component classes change. When
 *       updating docs/index.html styles, update the HEAD_CSS constant here too.
 */

'use strict';

const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

// ── CLI args ────────────────────────────────────────────────────────────────

const args = process.argv.slice(2);
let limit = 1000;
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--limit' && args[i + 1]) {
    limit = parseInt(args[i + 1], 10);
    if (isNaN(limit) || limit < 1) {
      console.error('--limit must be a positive integer');
      process.exit(1);
    }
    i++;
  }
}

// ── Paths ────────────────────────────────────────────────────────────────────

const repoRoot = path.resolve(__dirname, '..');
const changelogMdPath = path.join(repoRoot, 'CHANGELOG.md');
const changelogHtmlPath = path.join(repoRoot, 'docs', 'changelog.html');

// ── HTML escaping (public-site safety) ──────────────────────────────────────

function htmlEscape(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ── Fetch PRs via gh CLI ─────────────────────────────────────────────────────

let raw;
try {
  raw = execFileSync(
    'gh',
    ['pr', 'list', '--state', 'merged', '--json',
     'number,title,labels,mergedAt,author,url', '--limit', String(limit)],
    { encoding: 'utf8' }
  );
} catch (err) {
  process.stderr.write(err.stderr || err.message);
  process.exit(1);
}

const allPRs = JSON.parse(raw);

// ── Filtering ────────────────────────────────────────────────────────────────

function hasTypeLabel(pr) {
  const typeLabels = ['type:feat', 'type:fix', 'type:docs', 'type:chore',
                      'type:refactor', 'type:perf', 'type:test', 'type:breaking'];
  return pr.labels.some(l => typeLabels.includes(l.name));
}

function hasDependenciesLabel(pr) {
  return pr.labels.some(l => l.name === 'dependencies');
}

function isBotAuthor(pr) {
  return pr.author && pr.author.login && pr.author.login.endsWith('[bot]');
}

const prs = allPRs.filter(pr => {
  // Exclude dependency noise regardless of author
  if (hasDependenciesLabel(pr)) return false;
  // Exclude bots unless they carry an explicit type label
  if (isBotAuthor(pr) && !hasTypeLabel(pr)) return false;
  return true;
});

// ── Classification ───────────────────────────────────────────────────────────

const SECTION_ORDER = [
  'Breaking Changes',
  'Features',
  'Fixes',
  'Performance',
  'Refactoring',
  'Documentation',
  'Tests',
  'Maintenance',
  'Uncategorized',
];

// Conventional-commit prefix -> section name
const PREFIX_MAP = [
  [/^feat(\([^)]*\))?!?:/i,     'Features'],
  [/^fix(\([^)]*\))?!?:/i,      'Fixes'],
  [/^docs(\([^)]*\))?!?:/i,     'Documentation'],
  [/^chore(\([^)]*\))?!?:/i,    'Maintenance'],
  [/^refactor(\([^)]*\))?!?:/i, 'Refactoring'],
  [/^perf(\([^)]*\))?!?:/i,     'Performance'],
  [/^test(\([^)]*\))?!?:/i,     'Tests'],
];

// Full prefix pattern for stripping: type(scope)?!?:
const STRIP_RE = /^[a-zA-Z]+(\([^)]*\))?!?:\s*/;

// Breaking change: ! after type/scope, or explicit label
function isBreaking(pr) {
  if (pr.labels.some(l => l.name === 'breaking-change')) return true;
  return /^[a-zA-Z]+(\([^)]*\))?!:/i.test(pr.title);
}

function classifyPR(pr) {
  if (isBreaking(pr)) return 'Breaking Changes';
  for (const [re, section] of PREFIX_MAP) {
    if (re.test(pr.title)) return section;
  }
  return 'Uncategorized';
}

function stripPrefix(title) {
  const stripped = title.replace(STRIP_RE, '').trim();
  return stripped.length > 0 ? stripped : title;
}

// ── Grouping ─────────────────────────────────────────────────────────────────

function utcDate(mergedAt) {
  // Returns YYYY-MM-DD in UTC
  return mergedAt.slice(0, 10);
}

// Build: { date -> { section -> [pr, ...] } }
const byDate = {};
for (const pr of prs) {
  const date = utcDate(pr.mergedAt);
  if (!byDate[date]) byDate[date] = {};
  const section = classifyPR(pr);
  if (!byDate[date][section]) byDate[date][section] = [];
  byDate[date][section].push(pr);
}

// Sort dates descending
const sortedDates = Object.keys(byDate).sort((a, b) => (a < b ? 1 : -1));

// Within each date+section, sort PRs by number descending
for (const date of sortedDates) {
  for (const section of Object.keys(byDate[date])) {
    byDate[date][section].sort((a, b) => b.number - a.number);
  }
}

// ── Markdown generation ──────────────────────────────────────────────────────

function buildMarkdown() {
  const lines = [
    '<!-- generated by scripts/generate-changelog.js - do not edit by hand -->',
    '<!-- regenerate: node scripts/generate-changelog.js -->',
    '',
    '# Changelog',
    '',
  ];

  for (const date of sortedDates) {
    lines.push(`## ${date}`, '');
    for (const section of SECTION_ORDER) {
      const sectionPRs = byDate[date][section];
      if (!sectionPRs || sectionPRs.length === 0) continue;
      lines.push(`### ${section}`, '');
      for (const pr of sectionPRs) {
        const title = stripPrefix(pr.title);
        lines.push(`- **#${pr.number}** [${title}](${pr.url}) - ${pr.author.login}`);
      }
      lines.push('');
    }
  }

  return lines.join('\n');
}

// ── HTML generation ──────────────────────────────────────────────────────────

// Copied verbatim from docs/index.html <head> CSS block.
// Update this constant when docs/index.html CSS variables or component classes change.
const HEAD_CSS = `  :root {
    --bg-base:         #02050C;
    --bg-raised:       #060B16;
    --bg-surface:      #0A1020;
    --bg-overlay:      #0D1426;
    --bg-deep:         #04070F;

    --border-faint:    rgba(255, 255, 255, 0.07);
    --border-subtle:   rgba(255, 255, 255, 0.12);
    --border-default:  rgba(255, 255, 255, 0.18);
    --border-strong:   rgba(255, 255, 255, 0.30);

    --text-bright:     #ffffff;
    --text-primary:    #eaf1fb;
    --text-secondary:  rgba(234, 241, 251, 0.74);
    --text-muted:      #9bb0cc;
    --text-dim:        #6a7c97;

    --cyan:            #18E0FF;
    --cyan-dim:        rgba(24, 224, 255, 0.32);
    --cyan-glow:       rgba(24, 224, 255, 0.14);

    --violet:          #b06bff;
    --violet-dim:      rgba(176, 107, 255, 0.32);
    --violet-glow:     rgba(176, 107, 255, 0.13);

    --green:           #3ad99a;
    --green-dim:       rgba(58, 217, 154, 0.32);
    --green-glow:      rgba(58, 217, 154, 0.13);

    --gold:            #E9B521;
    --gold-dim:        rgba(233, 181, 33, 0.32);
    --gold-glow:       rgba(233, 181, 33, 0.13);

    --rose:            #ff5d73;
    --rose-dim:        rgba(255, 93, 115, 0.32);
    --rose-glow:       rgba(255, 93, 115, 0.13);

    --amber-soft:      #E9B521;
    --sky:             #18E0FF;

    --radius-sm:  4px;
    --radius-md:  8px;
    --radius-lg:  14px;

    --nav-width: 224px;
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }
  html { scroll-behavior: smooth; scroll-padding-top: 28px; }

  ::selection { background: rgba(24, 224, 255, 0.30); color: #ffffff; }

  body {
    font-family: 'Nunito Sans', system-ui, sans-serif;
    background-color: var(--bg-base);
    background-image:
      radial-gradient(1100px 600px at 16% -8%, rgba(24, 224, 255, 0.10), transparent 60%),
      radial-gradient(900px 520px at 98% 2%, rgba(176, 107, 255, 0.09), transparent 58%),
      radial-gradient(1000px 760px at 62% 112%, rgba(24, 224, 255, 0.05), transparent 60%);
    background-attachment: fixed;
    color: var(--text-primary);
    padding: 52px 40px 96px calc(var(--nav-width) + 48px);
    min-height: 100vh;
    font-size: 17px;
    line-height: 1.7;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    overflow-x: hidden;
  }

  body::-webkit-scrollbar { width: 10px; height: 10px; }
  body::-webkit-scrollbar-track { background: transparent; }
  body::-webkit-scrollbar-thumb {
    background: rgba(24, 224, 255, 0.18);
    border-radius: 999px;
    border: 2px solid transparent;
    background-clip: padding-box;
  }
  body::-webkit-scrollbar-thumb:hover { background: rgba(24, 224, 255, 0.34); background-clip: padding-box; }

  .doc-header {
    margin-bottom: 18px;
    padding-bottom: 26px;
    border-bottom: 1px solid var(--border-subtle);
    position: relative;
  }
  h1 {
    font-family: 'Orbitron', system-ui, sans-serif;
    font-size: clamp(40px, 6vw, 60px);
    font-weight: 800;
    color: var(--text-bright);
    letter-spacing: 0.015em;
    line-height: 1.05;
    margin-bottom: 12px;
    text-shadow: 0 0 30px rgba(24, 224, 255, 0.35);
  }
  .subtitle {
    font-family: 'Nunito Sans', system-ui, sans-serif;
    font-size: 19px;
    font-weight: 400;
    color: var(--text-secondary);
    letter-spacing: 0.005em;
    margin-bottom: 12px;
    max-width: 72ch;
  }
  .byline {
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    color: var(--text-muted);
    letter-spacing: 0.04em;
    text-transform: uppercase;
    margin-bottom: 12px;
  }

  .side-nav {
    position: fixed;
    top: 0; left: 0;
    width: var(--nav-width);
    height: 100vh;
    background: var(--bg-deep);
    border-right: 1px solid var(--border-faint);
    padding: 28px 0;
    overflow-y: auto;
    z-index: 100;
  }
  .side-nav::-webkit-scrollbar { width: 0; }

  .side-nav-brand {
    padding: 0 20px;
    margin-bottom: 24px;
  }
  .side-nav-logo {
    display: block;
    width: 100%;
    max-width: 176px;
    height: auto;
    filter: drop-shadow(0 0 12px rgba(24, 224, 255, 0.4));
  }
  .side-nav-divider {
    border: 0;
    border-top: 1px solid var(--border-faint);
    margin: 0 20px 20px 20px;
  }

  .side-nav a {
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 7px 20px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
    color: var(--text-muted);
    text-decoration: none;
    border-left: 2px solid transparent;
    transition: color 0.18s, background 0.18s, border-color 0.18s;
    letter-spacing: 0.01em;
  }
  .side-nav a:hover {
    color: var(--text-primary);
    background: rgba(255, 255, 255, 0.03);
  }
  .side-nav a.active {
    color: var(--cyan);
    background: var(--cyan-glow);
    border-left-color: var(--cyan);
  }
  .side-nav .nav-dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    flex-shrink: 0;
    opacity: 0.9;
    box-shadow: 0 0 6px currentColor;
  }

  @media (max-width: 920px) {
    .side-nav { display: none; }
    body { padding-left: 24px; padding-right: 24px; }
  }

  .section {
    padding-block: 48px 40px;
    padding-inline: 0;
    position: relative;
    border-top: 1px solid var(--border-faint);
  }
  .section:first-child {
    border-top: none;
    padding-top: 36px;
  }

  strong { font-weight: 700; color: var(--text-bright); }

  a { color: var(--cyan); text-decoration: none; transition: color 0.18s, text-shadow 0.18s; }
  a:hover { color: var(--text-bright); text-shadow: 0 0 12px rgba(24, 224, 255, 0.5); }

  /* Changelog-specific styles */
  .cl-date-heading {
    font-family: 'Orbitron', system-ui, sans-serif;
    font-size: clamp(20px, 2.5vw, 28px);
    font-weight: 700;
    color: var(--text-bright);
    letter-spacing: 0.04em;
    margin-bottom: 20px;
    text-shadow: 0 0 20px rgba(24, 224, 255, 0.20);
  }
  .cl-section-heading {
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    font-weight: 500;
    color: var(--text-muted);
    letter-spacing: 0.10em;
    text-transform: uppercase;
    margin: 20px 0 8px;
  }
  .cl-section-heading:first-of-type { margin-top: 0; }
  .cl-list {
    list-style: none;
    padding: 0;
    margin: 0 0 4px;
  }
  .cl-list li {
    display: flex;
    align-items: baseline;
    gap: 10px;
    padding: 5px 0;
    border-bottom: 1px solid var(--border-faint);
    font-size: 15px;
    color: var(--text-secondary);
    line-height: 1.65;
  }
  .cl-list li:last-child { border-bottom: none; }
  .cl-pr-badge {
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: var(--text-dim);
    background: var(--bg-surface);
    border: 1px solid var(--border-faint);
    border-radius: var(--radius-sm);
    padding: 1px 6px;
    white-space: nowrap;
    flex-shrink: 0;
  }
  .cl-pr-title { flex: 1; }
  .cl-author {
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: var(--text-dim);
    white-space: nowrap;
    flex-shrink: 0;
  }
  .cl-empty {
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
    color: var(--text-dim);
    padding: 24px 0;
  }

  @media (prefers-reduced-motion: reduce) {
    html { scroll-behavior: auto; }
    * { transition: none !important; animation: none !important; }
  }`;

function buildHTML(generatedDate) {
  const navLinks = `
  <a href="index.html"><span class="nav-dot" style="background: var(--text-muted);"></span> Home</a>
  <hr class="side-nav-divider">
  <a href="#changelog" class="active"><span class="nav-dot" style="background: var(--cyan);"></span> Changelog</a>`;

  let dateSections = '';

  if (sortedDates.length === 0) {
    dateSections = `<div class="cl-empty">No merged PRs found.</div>`;
  } else {
    for (const date of sortedDates) {
      let sectionContent = '';
      for (const section of SECTION_ORDER) {
        const sectionPRs = byDate[date][section];
        if (!sectionPRs || sectionPRs.length === 0) continue;
        sectionContent += `        <h3 class="cl-section-heading">${htmlEscape(section)}</h3>\n`;
        sectionContent += `        <ul class="cl-list">\n`;
        for (const pr of sectionPRs) {
          const title = stripPrefix(pr.title);
          sectionContent += `          <li>
            <span class="cl-pr-badge">#${htmlEscape(String(pr.number))}</span>
            <span class="cl-pr-title"><a href="${htmlEscape(pr.url)}" target="_blank" rel="noopener noreferrer">${htmlEscape(title)}</a></span>
            <span class="cl-author">${htmlEscape(pr.author.login)}</span>
          </li>\n`;
        }
        sectionContent += `        </ul>\n`;
      }
      dateSections += `      <div class="section">
        <h2 class="cl-date-heading">${htmlEscape(date)}</h2>
${sectionContent}      </div>\n`;
    }
  }

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#02050C">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><circle cx='16' cy='16' r='10' fill='none' stroke='%2318E0FF' stroke-width='3'/></svg>">
<title>Changelog - DinoStack</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500;600;700;800;900&family=Nunito+Sans:wght@400;600;700&family=JetBrains+Mono:wght@300;400;500&display=swap" rel="stylesheet">
<style>
${HEAD_CSS}
</style>
</head>
<body>

<!-- Side Navigation -->
<nav class="side-nav">
  <div class="side-nav-brand">
    <img class="side-nav-logo" src="images/dinostack-logo.svg" alt="DinoStack" />
  </div>${navLinks}
</nav>

<div class="doc-header" id="changelog">
  <h1>Changelog</h1>
  <p class="subtitle">All merged pull requests, grouped by date and type.</p>
  <p class="byline">Last updated: ${htmlEscape(generatedDate)}</p>
</div>

<main>
${dateSections}</main>

</body>
</html>`;
}

// ── Write outputs ─────────────────────────────────────────────────────────────

const today = new Date().toISOString().slice(0, 10);

const markdownContent = buildMarkdown();
const htmlContent = buildHTML(today);

fs.writeFileSync(changelogMdPath, markdownContent, 'utf8');
fs.writeFileSync(changelogHtmlPath, htmlContent, 'utf8');

// ── Summary ───────────────────────────────────────────────────────────────────

console.log(`Wrote CHANGELOG.md and docs/changelog.html (${prs.length} PRs across ${sortedDates.length} dates)`);
