'use strict';

/**
 * Purpose: ESLint config for hooks/*.js Claude Code hook scripts.
 * Public API: consumed by eslint via --config or auto-discovery.
 * Upstream deps: eslint@8, eslint-recommended ruleset.
 * Downstream consumers: hooks/pre-commit lint gate, local dev.
 * Failure modes: exits non-zero on violations; warn-level rules print but pass.
 * Performance: standard.
 */

module.exports = {
  env: {
    node: true,
    es2022: true,
  },
  parserOptions: {
    ecmaVersion: 2022,
  },
  // Scope to hooks directory only; scripts/ and tests/ excluded.
  ignorePatterns: [
    'content/**',
    'docs/**',
    'scripts/**',
    '.claude/**',
    '.codex/**',
    '.cursor/**',
    '.gemini/**',
    '.kimi/**',
    '.opencode/**',
    '.pi/**',
    '.omp/**',
    '.hermes/**',
    '.openclaw/**',
    'evals/**',
    'node_modules/**',
    'hooks/tests/**',
    'hooks/**/*.test.js',
  ],
  rules: {
    // Core correctness
    'no-undef': 'error',
    'no-unused-vars': ['warn', { args: 'after-used', ignoreRestSiblings: true }],
    'no-console': 'off',          // hook scripts legitimately use console for output
    'strict': ['error', 'global'], // enforce 'use strict' at file level
  },
};
