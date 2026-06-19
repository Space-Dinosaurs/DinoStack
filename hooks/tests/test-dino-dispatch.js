#!/usr/bin/env node
/**
 * Unit tests: hooks/dino-dispatch.py - the per-event hook dispatcher.
 *
 * Cases:
 *   D1  - merge channels: systemMessage concat (\n\n), additionalContext concat
 *         under hookSpecificOutput, plain-text leaf folded into additionalContext
 *         for UserPromptSubmit.
 *   D2  - event-conditional NEGATIVE: Stop-event run whose leaf emits a
 *         permissionDecision -> dispatcher output has NO permissionDecision.
 *   D3  - event-conditional NEGATIVE: PreToolUse leaf emits decision:"block"
 *         -> dispatcher output has NO top-level decision:block.
 *   D4  - strictest-wins permissionDecision (deny beats allow) for PreToolUse,
 *         reading the nested hookSpecificOutput.permissionDecision form.
 *   D5  - failure isolation: a leaf that exits non-zero is skipped; dispatcher
 *         still exits 0 with valid JSON from the succeeding leaf.
 *   D6  - failure isolation: missing leaf dir -> dispatcher exits 0.
 *   D7  - failure isolation: leaf with unresolvable interpreter is skipped;
 *         other leaves still run.
 *   D8  - PreToolUse matcher-gating: a "# dino-matcher: Task" leaf runs for
 *         tool_name=Task; tool_name=Read fast-paths (no subprocess) with exit 0.
 *   D9  - non-+x leaf is still invoked (mode-independence via explicit interpreter).
 *
 * Run with: node hooks/tests/test-dino-dispatch.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const DISPATCHER = path.resolve(__dirname, '..', 'dino-dispatch.py');

let passed = 0;
let failed = 0;

function assert(condition, message) {
  if (condition) {
    console.log(`  PASS: ${message}`);
    passed++;
  } else {
    console.error(`  FAIL: ${message}`);
    failed++;
  }
}

function assertEqual(actual, expected, message) {
  if (actual === expected) {
    console.log(`  PASS: ${message}`);
    passed++;
  } else {
    console.error(`  FAIL: ${message} (expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)})`);
    failed++;
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Run the dispatcher with the given event name and stdin payload. */
function runDispatcher(tempHooksDir, event, payload) {
  const input = JSON.stringify(payload);
  const result = spawnSync(
    'python3',
    [path.join(tempHooksDir, 'dino-dispatch.py'), event],
    { input, encoding: 'utf8', timeout: 15000 }
  );
  let output = null;
  if (result.stdout && result.stdout.trim()) {
    try { output = JSON.parse(result.stdout.trim()); } catch (_) { /* invalid JSON */ }
  }
  return { status: result.status, stdout: result.stdout || '', stderr: result.stderr || '', output };
}

/**
 * Create a temp hooks dir with a COPIED dispatcher and the given event's leaf dir.
 * We must COPY (not symlink) the dispatcher because Path(__file__).resolve() follows
 * symlinks back to the real hooks/ dir, causing the real leaf dirs to be discovered
 * instead of the temp fixture dirs.
 * Returns { tempDir, leafDir, cleanup }.
 */
function makeTempHooksDir(event) {
  const eventDirMap = {
    UserPromptSubmit: 'userpromptsubmit.d',
    Stop: 'stop.d',
    SessionStart: 'sessionstart.d',
    SessionEnd: 'sessionend.d',
    PreToolUse: 'pretooluse.d',
  };
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'dino-test-'));
  // COPY the dispatcher so Path(__file__).parent resolves to the temp dir,
  // not back to the real hooks/ dir through a symlink.
  fs.copyFileSync(DISPATCHER, path.join(tempDir, 'dino-dispatch.py'));
  const leafDirName = eventDirMap[event] || `${event.toLowerCase()}.d`;
  const leafDir = path.join(tempDir, leafDirName);
  fs.mkdirSync(leafDir, { recursive: true });
  return {
    tempDir, leafDir,
    cleanup() {
      try { fs.rmSync(tempDir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
    },
  };
}

/**
 * Write a JS leaf that emits JSON to stdout and exits with the given code.
 * The dispatcher invokes .js leaves via "node <leaf>", so # is a syntax error.
 * Use Python leaves (.py) when a dino-matcher header is needed.
 */
function writeJsLeaf(leafDir, name, outputObj, exitCode = 0) {
  const outputLine = outputObj !== null
    ? `process.stdout.write(${JSON.stringify(JSON.stringify(outputObj))});`
    : '';
  const content = `#!/usr/bin/env node\n${outputLine}\nprocess.exit(${exitCode});\n`;
  fs.writeFileSync(path.join(leafDir, name), content, 'utf8');
}

/**
 * Write a plain-text leaf (JS) that emits a plain string to stdout.
 */
function writePlainTextJsLeaf(leafDir, name, text) {
  const content = `#!/usr/bin/env node\nprocess.stdout.write(${JSON.stringify(text)});\nprocess.exit(0);\n`;
  fs.writeFileSync(path.join(leafDir, name), content, 'utf8');
}

/**
 * Write a Python leaf that emits JSON to stdout.
 * Python leaves (.py) support '# dino-matcher:' headers natively.
 */
function writePyLeaf(leafDir, name, outputObj, exitCode = 0, extraHeader = '') {
  const outputLine = outputObj !== null
    ? `import json, sys; sys.stdout.write(json.dumps(${JSON.stringify(outputObj)}))`
    : '';
  const content = `#!/usr/bin/env python3\n${extraHeader}${outputLine}\nimport sys; sys.exit(${exitCode})\n`;
  fs.writeFileSync(path.join(leafDir, name), content, 'utf8');
}

// ---------------------------------------------------------------------------
// Test D1: merge channels
// ---------------------------------------------------------------------------
console.log('\nTest D1: merge channels (systemMessage, additionalContext, plain-text)');
{
  const { tempDir, leafDir, cleanup } = makeTempHooksDir('UserPromptSubmit');
  try {
    // Leaf A: systemMessage + additionalContext nested under hookSpecificOutput
    writeJsLeaf(leafDir, '010-leaf-a.js', {
      systemMessage: 'sys-msg-A',
      hookSpecificOutput: { additionalContext: 'ctx-A' },
    });
    // Leaf B: systemMessage + top-level additionalContext
    writeJsLeaf(leafDir, '020-leaf-b.js', {
      systemMessage: 'sys-msg-B',
      additionalContext: 'ctx-B',
    });
    // Leaf C: plain text -> folded into additionalContext for UserPromptSubmit
    writePlainTextJsLeaf(leafDir, '030-leaf-c.js', 'plain-text-C');

    const { status, output } = runDispatcher(tempDir, 'UserPromptSubmit', {});
    assertEqual(status, 0, 'D1: dispatcher exits 0');
    assert(output !== null, 'D1: dispatcher output is valid JSON');
    assertEqual(
      output && output.systemMessage,
      'sys-msg-A\n\nsys-msg-B',
      'D1: systemMessages concat with \\n\\n'
    );
    const ac = output && output.hookSpecificOutput && output.hookSpecificOutput.additionalContext;
    assertEqual(ac, 'ctx-A\nctx-B\nplain-text-C', 'D1: additionalContext from nested + top-level + plain-text');
  } finally {
    cleanup();
  }
}

// ---------------------------------------------------------------------------
// Test D2: NEGATIVE - Stop leaf emitting permissionDecision -> NOT in output
// ---------------------------------------------------------------------------
console.log('\nTest D2: Stop leaf permissionDecision -> NOT in dispatcher output (event-conditional)');
{
  const { tempDir, leafDir, cleanup } = makeTempHooksDir('Stop');
  try {
    writeJsLeaf(leafDir, '010-leaf.js', {
      hookSpecificOutput: { permissionDecision: 'deny', permissionDecisionReason: 'should-not-appear' },
    });
    const { status, output } = runDispatcher(tempDir, 'Stop', {});
    assertEqual(status, 0, 'D2: dispatcher exits 0');
    assert(output !== null, 'D2: valid JSON output');
    const hasPerm = output && output.hookSpecificOutput && output.hookSpecificOutput.permissionDecision !== undefined;
    assert(!hasPerm, 'D2: no permissionDecision in Stop output (event-conditional gate)');
  } finally {
    cleanup();
  }
}

// ---------------------------------------------------------------------------
// Test D3: NEGATIVE - PreToolUse leaf emits decision:"block" -> no top-level
//          decision:block (block-honoring events do NOT include PreToolUse)
// ---------------------------------------------------------------------------
console.log('\nTest D3: PreToolUse leaf decision:block -> no top-level decision:block in output');
{
  const { tempDir, leafDir, cleanup } = makeTempHooksDir('PreToolUse');
  try {
    // Use a Python leaf with dino-matcher: Task header
    writePyLeaf(
      leafDir, '010-block-leaf.py',
      { decision: 'block', reason: 'should-not-appear' },
      0,
      '# dino-matcher: Task\n'
    );
    const { status, output } = runDispatcher(tempDir, 'PreToolUse', { tool_name: 'Task' });
    assertEqual(status, 0, 'D3: dispatcher exits 0');
    // Output may be non-null (leaf ran) or null (fast-path exit before JSON print)
    if (output !== null) {
      assert(output.decision !== 'block', 'D3: no top-level decision:block in PreToolUse output');
    } else {
      // fast-path: the PreToolUse matched but leaf emitted no permissionDecision -> exit 0, no stdout
      assert(true, 'D3: no output means no decision:block propagated');
    }
  } finally {
    cleanup();
  }
}

// ---------------------------------------------------------------------------
// Test D4: strictest-wins permissionDecision (deny beats allow) for PreToolUse
// ---------------------------------------------------------------------------
console.log('\nTest D4: PreToolUse strictest-wins permissionDecision (deny beats allow)');
{
  const { tempDir, leafDir, cleanup } = makeTempHooksDir('PreToolUse');
  try {
    // Leaf 1: returns allow
    writePyLeaf(
      leafDir, '010-allow.py',
      { hookSpecificOutput: { permissionDecision: 'allow', permissionDecisionReason: 'ok' } },
      0,
      '# dino-matcher: Task\n'
    );
    // Leaf 2: returns deny
    writePyLeaf(
      leafDir, '020-deny.py',
      { hookSpecificOutput: { permissionDecision: 'deny', permissionDecisionReason: 'blocked' } },
      0,
      '# dino-matcher: Task\n'
    );
    const { status, output } = runDispatcher(tempDir, 'PreToolUse', { tool_name: 'Task' });
    assertEqual(status, 0, 'D4: dispatcher exits 0');
    assert(output !== null, 'D4: valid JSON output');
    const pd = output && output.hookSpecificOutput && output.hookSpecificOutput.permissionDecision;
    assertEqual(pd, 'deny', 'D4: deny beats allow (strictest-wins)');
  } finally {
    cleanup();
  }
}

// ---------------------------------------------------------------------------
// Test D5: failure isolation - non-zero exit leaf skipped, dispatcher exits 0
// ---------------------------------------------------------------------------
console.log('\nTest D5: failure isolation - non-zero exit leaf skipped, dispatcher exits 0');
{
  const { tempDir, leafDir, cleanup } = makeTempHooksDir('SessionEnd');
  try {
    writeJsLeaf(leafDir, '010-fail.js', null, 1);
    writeJsLeaf(leafDir, '020-ok.js', { systemMessage: 'from-ok' });
    const { status, output } = runDispatcher(tempDir, 'SessionEnd', {});
    assertEqual(status, 0, 'D5: dispatcher exits 0 despite failing leaf');
    assert(output !== null, 'D5: valid JSON output');
    assertEqual(output && output.systemMessage, 'from-ok', 'D5: succeeding leaf output present');
  } finally {
    cleanup();
  }
}

// ---------------------------------------------------------------------------
// Test D6: failure isolation - missing leaf dir -> exits 0
// ---------------------------------------------------------------------------
console.log('\nTest D6: failure isolation - missing leaf dir -> dispatcher exits 0');
{
  // Temp hooks dir with NO leaf dir created for the event.
  // Copy (not symlink) so Path(__file__).parent resolves to the temp dir.
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'dino-test-'));
  fs.copyFileSync(DISPATCHER, path.join(tempDir, 'dino-dispatch.py'));
  try {
    const result = spawnSync('python3', [path.join(tempDir, 'dino-dispatch.py'), 'UserPromptSubmit'], {
      input: '{}', encoding: 'utf8', timeout: 10000,
    });
    assertEqual(result.status, 0, 'D6: exits 0 when leaf dir missing');
    // Output must be parseable (suppressOutput or empty-merge object)
    let output = null;
    if (result.stdout && result.stdout.trim()) {
      try { output = JSON.parse(result.stdout.trim()); } catch (_) { /* ignore */ }
    }
    assert(result.status === 0, 'D6: no crash on missing leaf dir');
  } finally {
    try { fs.rmSync(tempDir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
  }
}

// ---------------------------------------------------------------------------
// Test D7: failure isolation - unresolvable leaf skipped, others run
// ---------------------------------------------------------------------------
console.log('\nTest D7: failure isolation - unresolvable leaf skipped, others run');
{
  const { tempDir, leafDir, cleanup } = makeTempHooksDir('SessionStart');
  try {
    // A leaf with unknown extension and no shebang - interpreter cannot be resolved
    fs.writeFileSync(path.join(leafDir, '010-unknown.xyz'), 'this is not a script\n');
    writeJsLeaf(leafDir, '020-good.js', { systemMessage: 'from-good' });
    const { status, output } = runDispatcher(tempDir, 'SessionStart', {});
    assertEqual(status, 0, 'D7: dispatcher exits 0 despite unresolvable leaf');
    assert(output !== null, 'D7: valid JSON output');
    assertEqual(output && output.systemMessage, 'from-good', 'D7: good leaf output present');
  } finally {
    cleanup();
  }
}

// ---------------------------------------------------------------------------
// Test D8: PreToolUse matcher-gating
// ---------------------------------------------------------------------------
console.log('\nTest D8: PreToolUse matcher-gating (Task match / Read fast-path)');
{
  const { tempDir, leafDir, cleanup } = makeTempHooksDir('PreToolUse');
  try {
    writePyLeaf(
      leafDir, '010-task.py',
      { hookSpecificOutput: { permissionDecision: 'allow' } },
      0,
      '# dino-matcher: Task\n'
    );

    // tool_name=Task -> leaf matches, permissionDecision returned
    const taskResult = runDispatcher(tempDir, 'PreToolUse', { tool_name: 'Task' });
    assertEqual(taskResult.status, 0, 'D8: exits 0 for Task');
    const pd = taskResult.output && taskResult.output.hookSpecificOutput && taskResult.output.hookSpecificOutput.permissionDecision;
    assertEqual(pd, 'allow', 'D8: Task leaf fires -> permissionDecision=allow');

    // tool_name=Read -> fast-path, no leaf matches, exits 0, no stdout
    const readResult = spawnSync('python3', [path.join(tempDir, 'dino-dispatch.py'), 'PreToolUse'], {
      input: JSON.stringify({ tool_name: 'Read' }), encoding: 'utf8', timeout: 10000,
    });
    assertEqual(readResult.status, 0, 'D8: exits 0 for Read (fast-path)');
    assertEqual((readResult.stdout || '').trim(), '', 'D8: Read fast-path emits no stdout');
  } finally {
    cleanup();
  }
}

// ---------------------------------------------------------------------------
// Test D9: non-+x leaf invoked via explicit interpreter (mode-independent)
// ---------------------------------------------------------------------------
console.log('\nTest D9: non-+x leaf invoked via explicit interpreter');
{
  const { tempDir, leafDir, cleanup } = makeTempHooksDir('Stop');
  try {
    const leafPath = path.join(leafDir, '010-no-exec.js');
    fs.writeFileSync(leafPath,
      '#!/usr/bin/env node\nprocess.stdout.write(JSON.stringify({systemMessage:"non-exec-ran"}));\nprocess.exit(0);\n'
    );
    // Strip execute bit - dispatcher must not rely on exec-ability
    fs.chmodSync(leafPath, 0o644);

    const { status, output } = runDispatcher(tempDir, 'Stop', {});
    assertEqual(status, 0, 'D9: dispatcher exits 0 for non-+x leaf');
    assert(output !== null, 'D9: valid JSON output');
    assertEqual(output && output.systemMessage, 'non-exec-ran', 'D9: non-+x leaf ran via explicit interpreter');
  } finally {
    cleanup();
  }
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n--- Results: ${passed} passed, ${failed} failed ---`);
if (failed > 0) process.exit(1);
