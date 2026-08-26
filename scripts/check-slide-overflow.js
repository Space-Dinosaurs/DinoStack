#!/usr/bin/env node
// Purpose: Measure rendered docs/slides/*-slides.html section heights in a
//          headless Chrome and fail when content exceeds the 720px slide
//          boundary without a matching entry in
//          scripts/slide-overflow-baseline.json (the ratchet file). Distinct
//          from scripts/check-slides-sync.sh, which only checks that
//          docs/slides/*.html matches a fresh render of its .md source - it
//          says nothing about whether that render actually FITS on the
//          slide.
//
// Public API: node scripts/check-slide-overflow.js [--deck <html path>]...
//               [--baseline <path>] [--repeat N] [--measurements-json <path>]
//               [--dump-overflows]
//             Default (no --deck, no --measurements-json): live-measures
//             every docs/slides/*-slides.html via headless Chrome. `--deck`
//             (repeatable) restricts live measurement to exactly the named
//             files. `--measurements-json` skips ALL browser code and reads
//             pre-computed measurements from disk (used by the browserless
//             bin/tests/test_check_slide_overflow.sh suite). `--dump-
//             overflows` performs a live measurement against an empty
//             baseline and prints the resulting overflow membership as JSON
//             to stdout, for baseline population/re-baselining - it does not
//             read scripts/slide-overflow-baseline.json at all.
//             Exit codes: 0 clean; 1 new overflow or stale baseline entry;
//             2 font load error (not a real verdict - environment issue);
//             3 measurement unstable across --repeat runs.
//
// Upstream deps: docs/slides/*-slides.html (rendered decks - see scripts/
//                build-slides.sh); scripts/slide-overflow-baseline.json
//                (ratchet file, membership only, no px values); puppeteer-
//                core + @puppeteer/browsers (LAZILY required - only inside
//                the live-measurement code path, so --measurements-json
//                mode has zero browser dependency); Chrome-for-Testing
//                downloaded on demand into scripts/node_modules/.chrome-
//                for-testing-cache; network (Chrome download + Google Fonts
//                the decks @import).
//
// Downstream consumers: scripts/check-slide-overflow.sh (wrapper: staleness-
//                        gated npm ci, conditional build-slides.sh, then
//                        this script); scripts/check-slide-overflow-live-
//                        selftest.sh (fixture-based live-mode scenarios);
//                        bin/tests/test_check_slide_overflow.sh (browserless
//                        --measurements-json scenarios); .github/workflows/
//                        slides-sync.yml check-slide-overflow job (advisory,
//                        not in the main ruleset's required-checks list).
//
// Failure modes: exit 2 (FONT LOAD ERROR) is a fail-CLOSED environment
//                signal, not a real overflow verdict - fires when Chrome
//                could not load any font face (offline, blocked font host).
//                exit 3 (MEASUREMENT UNSTABLE) fires only under --repeat N>1
//                when the SET of overflowing (deck,id) pairs differs across
//                runs. A missing --measurements-json file, an empty deck
//                glob, or a puppeteer/Chrome-for-Testing resolution failure
//                all exit non-zero with a message naming the cause.
//                Two additional hard-failure paths (Skeptic CRIT-silent-exit):
//                (1) after install()/computeExecutablePath resolve, the
//                resolved executablePath is verified with fs.existsSync -
//                a broken/partial install (e.g. an aborted extraction)
//                exits non-zero naming the missing path instead of letting
//                puppeteer-core's launch() fail in a way that can leave the
//                extraction promise never settling. (2) a completion
//                sentinel (`completed`) is set true only on a genuine
//                verdict path (reportAndExit, the dump-overflows path, or a
//                caught error path); a `process.on('exit', ...)` handler
//                checks it and forces exit 1 with "aborted before reaching
//                a verdict" if the process is about to exit 0 without ever
//                having reached one - this is the actual fix for the
//                previously-claimed-but-untrue assumption that a run always
//                produces output: a stalled/abandoned async
//                operation (observed with a stubbed @puppeteer/browsers
//                whose install() never resolves) used to let node drain
//                the event loop and exit 0 with zero output. The browser
//                launch itself always passes `--no-sandbox
//                --disable-setuid-sandbox` (see the launch() call site for
//                the safety justification) - without it, ubuntu-24.04+ CI
//                runners fail launch with "No usable sandbox!" (FATAL,
//                zygote_host_impl_linux.cc, signal 6) since they block
//                unprivileged user namespaces via AppArmor.
//
// Performance: cold run downloads Chrome-for-Testing (network; cached in
//              scripts/node_modules/.chrome-for-testing-cache ONLY on a
//              machine that persists that directory across runs - in CI,
//              with no actions/cache step configured for it, every job run
//              downloads fresh; locally, an npm ci in between runs deletes
//              it too, since npm ci always wipes node_modules first - see
//              scripts/check-slide-overflow.sh's Failure modes). Each deck
//              gets its own fresh browser context + page - this is the sole
//              load-bearing determinism mechanism (a reused page converges
//              on wrong values, measured) - so runtime scales linearly with
//              deck count, not sublinearly.

'use strict';

const fs = require('fs');
const path = require('path');

const TOLERANCE_PX = 2;
const OVERFLOW_THRESHOLD_PX = 720 + TOLERANCE_PX;
const SETTLE_ATTEMPTS = 5;

// Skeptic CRIT-silent-exit (b): a completion sentinel. Reproduced with a
// stubbed @puppeteer/browsers whose install() never resolves - main()'s
// promise never settles, the event loop drains once nothing else is
// pending, and node exits 0 with ZERO output (neither a verdict nor an
// error is ever printed). `markCompleted()` is called on every genuine
// verdict path (reportAndExit's two branches, the --dump-overflows path,
// each early-return error path in main(), and the top-level main().catch()
// handler). The process.on('exit', ...) handler below fires unconditionally
// as the LAST thing node does before actually exiting; if the process is
// about to exit 0 without ever having reached a verdict, that is itself a
// bug class (an abandoned async operation) and must not report success.
let completed = false;
function markCompleted() {
  completed = true;
}
process.on('exit', (code) => {
  if (!completed && code === 0) {
    console.error('check-slide-overflow: aborted before reaching a verdict');
    process.exitCode = 1;
  }
});

function parseArgs(argv) {
  const opts = {
    decks: [],
    baseline: path.join(__dirname, 'slide-overflow-baseline.json'),
    repeat: 1,
    measurementsJson: null,
    dumpOverflows: false,
  };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--deck') {
      opts.decks.push(argv[++i]);
    } else if (arg === '--baseline') {
      opts.baseline = argv[++i];
    } else if (arg === '--repeat') {
      const raw = argv[++i];
      const parsed = Number(raw);
      if (!Number.isInteger(parsed) || parsed < 1) {
        throw new Error(
          `check-slide-overflow: --repeat requires a positive integer, got: ${raw}`
        );
      }
      opts.repeat = parsed;
    } else if (arg === '--measurements-json') {
      opts.measurementsJson = argv[++i];
    } else if (arg === '--dump-overflows') {
      opts.dumpOverflows = true;
    } else {
      throw new Error(`check-slide-overflow: unrecognized argument: ${arg}`);
    }
  }
  if (opts.dumpOverflows && opts.measurementsJson) {
    throw new Error(
      'check-slide-overflow: --dump-overflows and --measurements-json are mutually exclusive'
    );
  }
  return opts;
}

function loadBaseline(baselinePath) {
  if (!fs.existsSync(baselinePath)) {
    return {};
  }
  return JSON.parse(fs.readFileSync(baselinePath, 'utf8'));
}

function deckBasename(deckPathOrName) {
  return path.basename(deckPathOrName);
}

// Pure compare/ratchet function - no browser, no fs beyond what's already
// loaded into memory. measurements: [{deck, slides: [{id, title,
// scrollHeight}]}]. baseline: {deckBasename: [sectionId, ...]}.
// scopeDecks: when non-null, restricts comparison + orphan-deck/orphan-slide
// checks to exactly these deck basenames (the --deck mode contract: other
// decks' baseline entries are never evaluated).
function compare(measurements, baseline, scopeDecks) {
  const failures = [];
  const scopedMeasurements = scopeDecks
    ? measurements.filter((m) => scopeDecks.includes(deckBasename(m.deck)))
    : measurements;
  const measuredDeckNames = new Set(scopedMeasurements.map((m) => deckBasename(m.deck)));
  let baselinedOverflowsStillPresent = 0;
  let totalSlides = 0;

  for (const { deck, slides } of scopedMeasurements) {
    const deckName = deckBasename(deck);
    const baselineIds = new Set(baseline[deckName] || []);
    const measuredIds = new Set();

    for (const slide of slides) {
      totalSlides++;
      measuredIds.add(slide.id);
      const overflowing = slide.scrollHeight > OVERFLOW_THRESHOLD_PX;
      const inBaseline = baselineIds.has(slide.id);

      if (overflowing && !inBaseline) {
        const over = Math.round(slide.scrollHeight - 720);
        failures.push(
          `check-slide-overflow: OVERFLOW ${deckName} slide ${slide.id} ("${slide.title}"): ` +
            `content height ${Math.round(slide.scrollHeight)}px exceeds 720px boundary by ${over}px ` +
            `(not in baseline - add a scripts/slide-overflow-baseline.json entry if pre-existing debt, ` +
            `or fix the slide if new)`
        );
      } else if (overflowing && inBaseline) {
        baselinedOverflowsStillPresent++;
      } else if (!overflowing && inBaseline) {
        failures.push(
          `check-slide-overflow: STALE BASELINE ${deckName} slide ${slide.id} ("${slide.title}"): ` +
            `baseline lists this as known overflow but it measures ${Math.round(slide.scrollHeight)}px - ` +
            `remove this entry from scripts/slide-overflow-baseline.json`
        );
      }
    }

    if (!scopeDecks) {
      for (const id of baselineIds) {
        if (!measuredIds.has(id)) {
          failures.push(
            `check-slide-overflow: STALE BASELINE (orphan slide) ${deckName} slide ${id}: ` +
              `no longer exists in this deck - remove from scripts/slide-overflow-baseline.json`
          );
        }
      }
    }
  }

  if (!scopeDecks) {
    for (const deckName of Object.keys(baseline)) {
      if (!measuredDeckNames.has(deckName)) {
        failures.push(
          `check-slide-overflow: STALE BASELINE (orphan deck) ${deckName}: ` +
            `no longer exists - remove from scripts/slide-overflow-baseline.json`
        );
      }
    }
  }

  return {
    failures,
    totalSlides,
    baselinedOverflowsStillPresent,
    deckCount: scopedMeasurements.length,
  };
}

function dumpOverflowsJson(measurements) {
  const result = {};
  for (const { deck, slides } of measurements) {
    const deckName = deckBasename(deck);
    const ids = slides
      .filter((s) => s.scrollHeight > OVERFLOW_THRESHOLD_PX)
      .map((s) => s.id);
    if (ids.length > 0) {
      result[deckName] = ids;
    }
  }
  return result;
}

// --- Live measurement (browser) path ---

async function resolveChromeExecutablePath() {
  const { install, computeExecutablePath, detectBrowserPlatform, resolveBuildId } =
    require('@puppeteer/browsers');
  const cacheDir = path.join(__dirname, 'node_modules', '.chrome-for-testing-cache');
  const platform = detectBrowserPlatform();
  const buildId = await resolveBuildId('chrome', platform, 'stable');
  const installed = await install({
    browser: 'chrome',
    buildId,
    cacheDir,
  });
  const executablePath =
    installed.executablePath ||
    computeExecutablePath({
      browser: 'chrome',
      buildId,
      cacheDir,
    });
  // Skeptic CRIT-silent-exit (a): a broken/partial install (e.g. an
  // extraction that silently stalled and left an incomplete browser
  // directory) can still return a path from computeExecutablePath - it is
  // computed from the build id, not verified against disk. Fail loudly
  // here instead of letting puppeteer-core's launch() fail in a way that
  // risks never settling.
  if (!fs.existsSync(executablePath)) {
    throw new Error(
      `check-slide-overflow: resolved Chrome executable does not exist on disk: ${executablePath} ` +
        `(install()/extraction likely incomplete - try removing ${cacheDir} and re-running)`
    );
  }
  return executablePath;
}

async function measureDeck(browser, deckPath, blockHosts) {
  const context = await browser.createBrowserContext();
  if (process.env.AE_DEBUG_CONTEXT_COUNT === '1') {
    // Written AFTER the createBrowserContext() await so this line observes
    // an actual new context, not merely a measureDeck() call (Skeptic
    // MAJ-context-count: writing this before the await made the selftest's
    // guard decorative - it would print 2 for 2 decks even if context
    // creation were hoisted out of the per-deck loop and shared).
    process.stderr.write('context-created\n');
  }
  try {
    const page = await context.newPage();

    if (blockHosts.length > 0) {
      await page.setRequestInterception(true);
      page.on('request', (req) => {
        const url = req.url();
        if (url.startsWith('file://')) {
          req.continue();
          return;
        }
        let hostname = '';
        try {
          hostname = new URL(url).hostname;
        } catch (_err) {
          req.continue();
          return;
        }
        if (blockHosts.includes(hostname)) {
          req.abort();
        } else {
          req.continue();
        }
      });
    }

    const abspath = path.resolve(deckPath);
    await page.goto(`file://${abspath}`, { waitUntil: 'load' });

    let previous = null;
    let current = null;
    // Running per-section max across ALL settle attempts, keyed by section
    // id (Skeptic MAJ-max-fallback: the prior version compared `previous`
    // to `current` where the loop had already set `previous = current`
    // before exiting, so on the non-convergence path it computed
    // Math.max(x, x) === x - inert exactly where the conservative fallback
    // was supposed to matter). Updated every attempt, not just the last two.
    const maxHeightById = new Map();
    for (let attempt = 0; attempt < SETTLE_ATTEMPTS; attempt++) {
      await page.evaluate(
        () =>
          new Promise((resolve) => {
            requestAnimationFrame(() => requestAnimationFrame(resolve));
          })
      );
      await page.evaluate(() => document.fonts.ready);

      current = await page.evaluate(() => {
        const sections = Array.from(document.querySelectorAll('section[id]'));
        return sections.map((section) => {
          const heading = section.querySelector('h1,h2');
          return {
            id: section.id,
            title: heading ? heading.textContent : '',
            scrollHeight: section.scrollHeight,
          };
        });
      });

      for (const slide of current) {
        const prevMax = maxHeightById.get(slide.id);
        if (prevMax === undefined || slide.scrollHeight > prevMax) {
          maxHeightById.set(slide.id, slide.scrollHeight);
        }
      }

      if (previous && sameMeasurement(previous, current)) {
        break;
      }
      previous = current;
    }

    // Conservative: use the running max across every attempt observed,
    // not just the final one, so a transient overshoot on an earlier
    // attempt is never silently discarded on the non-convergence path.
    const finalSlides = current.map((slide) => ({
      id: slide.id,
      title: slide.title,
      scrollHeight: maxHeightById.get(slide.id),
    }));

    const fontCheck = await page.evaluate(() => {
      const faces = Array.from(document.fonts);
      return {
        size: document.fonts.size,
        anyError: faces.some((f) => f.status === 'error'),
        anyLoaded: faces.some((f) => f.status === 'loaded'),
        errorCount: faces.filter((f) => f.status === 'error').length,
      };
    });

    return { slides: finalSlides, fontCheck };
  } finally {
    await context.close();
  }
}

function sameMeasurement(a, b) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i].id !== b[i].id) return false;
    if (a[i].scrollHeight !== b[i].scrollHeight) return false;
  }
  return true;
}

function checkFontFailure(deckName, fontCheck) {
  if (fontCheck.size === 0) {
    return `check-slide-overflow: FONT LOAD ERROR ${deckName}: no fonts registered (offline?) - measurement aborted, not a real overflow verdict`;
  }
  if (fontCheck.anyError) {
    return `check-slide-overflow: FONT LOAD ERROR ${deckName}: ${fontCheck.errorCount} font face(s) failed to load (font-file host blocked?) - measurement aborted, not a real overflow verdict`;
  }
  if (!fontCheck.anyLoaded) {
    return `check-slide-overflow: FONT LOAD ERROR ${deckName}: no font face reached loaded status - measurement aborted, not a real overflow verdict`;
  }
  return null;
}

async function liveMeasureAll(deckPaths) {
  const puppeteer = require('puppeteer-core');
  const executablePath = await resolveChromeExecutablePath();
  // --no-sandbox/--disable-setuid-sandbox: this gate only ever loads
  // repo-controlled local file:// HTML (rendered docs/slides/*.html), so
  // Chromium's OS-level sandbox adds no protection here, and ubuntu-24.04+
  // CI runners block unprivileged user namespaces via AppArmor, which
  // otherwise fails Chrome launch with "No usable sandbox!" (FATAL,
  // zygote_host_impl_linux.cc).
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });

  const blockHosts = (process.env.AE_TEST_BLOCK_HOSTS || '')
    .split(',')
    .map((h) => h.trim())
    .filter(Boolean);

  try {
    const measurements = [];
    for (const deckPath of deckPaths) {
      const deckName = deckBasename(deckPath);
      const { slides, fontCheck } = await measureDeck(browser, deckPath, blockHosts);
      const fontError = checkFontFailure(deckName, fontCheck);
      if (fontError) {
        const err = new Error(fontError);
        err.isFontError = true;
        throw err;
      }
      measurements.push({ deck: deckPath, slides });
    }
    return measurements;
  } finally {
    await browser.close();
  }
}

function overflowSetKey(measurements) {
  const pairs = [];
  for (const { deck, slides } of measurements) {
    const deckName = deckBasename(deck);
    for (const slide of slides) {
      if (slide.scrollHeight > OVERFLOW_THRESHOLD_PX) {
        pairs.push(`${deckName}::${slide.id}`);
      }
    }
  }
  return pairs.sort();
}

function findDefaultDecks() {
  const slidesDir = path.join(__dirname, '..', 'docs', 'slides');
  return fs
    .readdirSync(slidesDir)
    .filter((f) => f.endsWith('-slides.html'))
    .sort()
    .map((f) => path.join(slidesDir, f));
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));

  if (opts.measurementsJson) {
    if (!fs.existsSync(opts.measurementsJson)) {
      console.error(
        `check-slide-overflow: --measurements-json file not found: ${opts.measurementsJson}`
      );
      markCompleted();
      process.exitCode = 1;
      return;
    }
    const measurements = JSON.parse(fs.readFileSync(opts.measurementsJson, 'utf8'));
    const baseline = loadBaseline(opts.baseline);
    const scopeDecks = opts.decks.length > 0 ? opts.decks.map(deckBasename) : null;
    const { failures, totalSlides, baselinedOverflowsStillPresent, deckCount } = compare(
      measurements,
      baseline,
      scopeDecks
    );
    reportAndExit(failures, deckCount, totalSlides, baselinedOverflowsStillPresent);
    return;
  }

  const deckPaths = opts.decks.length > 0 ? opts.decks : findDefaultDecks();
  if (deckPaths.length === 0) {
    console.error('check-slide-overflow: no docs/slides/*-slides.html decks found');
    markCompleted();
    process.exitCode = 1;
    return;
  }

  let measurements;
  try {
    measurements = await liveMeasureAll(deckPaths);
    if (opts.repeat > 1) {
      const firstKey = overflowSetKey(measurements).join('|');
      for (let run = 2; run <= opts.repeat; run++) {
        const rerunMeasurements = await liveMeasureAll(deckPaths);
        const key = overflowSetKey(rerunMeasurements).join('|');
        if (key !== firstKey) {
          const flapped = diffOverflowKeys(firstKey, key);
          console.error(
            `check-slide-overflow: MEASUREMENT UNSTABLE across N=${opts.repeat} runs - ${flapped} flapped between runs`
          );
          markCompleted();
          process.exitCode = 3;
          return;
        }
      }
    }
  } catch (err) {
    if (err && err.isFontError) {
      console.error(err.message);
      markCompleted();
      process.exitCode = 2;
      return;
    }
    throw err;
  }

  if (opts.dumpOverflows) {
    console.log(JSON.stringify(dumpOverflowsJson(measurements), null, 2));
    markCompleted();
    process.exitCode = 0;
    return;
  }

  const baseline = loadBaseline(opts.baseline);
  const scopeDecks = opts.decks.length > 0 ? opts.decks.map(deckBasename) : null;
  const { failures, totalSlides, baselinedOverflowsStillPresent, deckCount } = compare(
    measurements,
    baseline,
    scopeDecks
  );
  reportAndExit(failures, deckCount, totalSlides, baselinedOverflowsStillPresent);
}

function diffOverflowKeys(a, b) {
  const setA = new Set(a.split('|').filter(Boolean));
  const setB = new Set(b.split('|').filter(Boolean));
  const diff = [];
  for (const k of setA) if (!setB.has(k)) diff.push(k);
  for (const k of setB) if (!setA.has(k)) diff.push(k);
  return diff.join(', ') || '(unknown pair)';
}

function reportAndExit(failures, deckCount, slideCount, baselinedOverflowsStillPresent) {
  if (failures.length > 0) {
    for (const f of failures) {
      console.error(f);
    }
    markCompleted();
    process.exitCode = 1;
    return;
  }
  console.log(
    `check-slide-overflow: ${deckCount} decks, ${slideCount} slides, 0 new overflows, ` +
      `0 stale baseline entries (${baselinedOverflowsStillPresent} pre-existing baselined overflows still present)`
  );
  markCompleted();
  process.exitCode = 0;
}

main().catch((err) => {
  console.error(`check-slide-overflow: ${err && err.stack ? err.stack : err}`);
  markCompleted();
  process.exitCode = 1;
});
