#!/usr/bin/env python3
"""
Purpose: PreToolUse hook that backstops the METHODOLOGY §Risk-Classification
         "Mandatory Tier-3 review escalation" rule on Claude Code by denying an
         EXPLICIT model downgrade on a mandated-Tier-3 review spawn. As of PR
         #313 the skeptic and security-auditor frontmatter default to
         model: opus, so OMITTING the model param already yields Tier 3. The
         only way to get a sub-Opus review is an explicit downgrade param - so
         this hook gates on "explicit non-opus model param", the precise,
         low-false-positive signal. Escalate-only: it never blocks the
         omit-the-param (role-default) path, and never touches non-review agents.

         NOTE - Task/Agent rename: Claude Code renamed the subagent-spawn tool
         from "Task" to "Agent". This hook guards on BOTH names
         (`tool_name in ("Task", "Agent")`). install.sh wires both matcher
         blocks; the internal guard is belt-and-suspenders.

         security-auditor: ANY explicit non-opus downgrade is denied (spec
         mandates Tier 3 unconditionally). skeptic: an explicit non-opus
         downgrade is denied ONLY when the spawn brief (prompt + description)
         matches a Tier-3 escalation marker - a non-mandated skeptic may
         legitimately run a cheaper model (e.g. budget mode).

Public API: Run as a Claude Code PreToolUse hook (matcher: "Task" or "Agent").
            Reads JSON from stdin, writes hookSpecificOutput JSON to stdout when
            denying, exits 0 always.

Upstream deps: Python 3 stdlib only (json, os, re, sys). No external deps.
               `from __future__ import annotations` keeps the file importable on
               Python 3.8/3.9 (PEP 604 `X | None` hints would crash there; the
               other enforce-*.py hooks avoid union syntax for the same reason).

Downstream consumers: Claude Code hook runner (PreToolUse event for the Task /
                      Agent tool). Wired via ~/.claude/settings.json by
                      .claude/install.sh (matcher blocks "Task" and "Agent").

Failure modes:
    - Malformed stdin / null / non-dict tool_input: fail-open (exit 0). A hook
      bug must never brick spawns - enforcement gaps beat blanket blocks.
    - Kill-switch (AE_TIER_GUARD_DISABLE=1): fail-open immediately before
      reading stdin. To disable: set AE_TIER_GUARD_DISABLE=1 in the shell that
      launches Claude Code, or remove the hook from ~/.claude/settings.json.
    - Non-Task/Agent tool_name: passthrough (exit 0).
    - Non-review subagent_type, absent model param, or any opus model: allow.
    - Coverage gap (documented, intentional): the "novel architecture
      constraining future choices" Tier-3 signal is NOT keyword-detectable
      without over-firing on routine reviews, so it is NOT mechanically caught
      here. The conductor's explicit model: opus and the skeptic frontmatter
      default remain the controls for that signal. This hook backstops the other
      four escalation signal categories (security/auth/crypto/payments/secrets;
      irreversible; release/deploy/production; high blast radius/shared utility).
    - Env-var resolution (CLAUDE_CODE_SUBAGENT_MODEL) is intentionally NOT
      guarded: the hook gates the spawn-call param (intent), not the env
      override, which it cannot see in tool_input and which outranks the param.
    - Older Claude Code (pre-permissionDecision): if deny is ignored, switch to
      exit 2 with the reason on stderr as the fallback path.

Performance: < 1 ms per call (in-memory JSON parse + bounded regex scan over the
             brief + single print, no I/O).
"""

from __future__ import annotations

import json
import os
import re
import sys

# Agents whose review quality is mandated Tier 3 (Opus). Source of truth:
# content/sections/04-risk-classification.md Role-default tier table.
MANDATED_TIER3 = {"skeptic", "security-auditor"}

# Tier-3 escalation markers (case-insensitive, word-boundary anchored) tracking
# four of the five signals in §Risk-Classification "Mandatory Tier-3 review
# escalation" (novel-architecture is intentionally not keyworded - see manifest
# Failure modes). Word boundaries avoid substring traps: \bauth\b does not match
# "author"/"authentic"; \bsecret\b does not match "secretary"; "product"/
# "reproduce" do not match (bare \bprod\b is deliberately omitted as noise).
_MARKER_PATTERNS = [
    # security / auth / crypto / payments / secrets (+ common acronyms)
    r"\bsecurity\b",
    r"\bauth\b", r"\boauth\b", r"\bauthn\b", r"\bauthz\b",
    r"\bauthenticat\w*", r"\bauthoriz\w*",
    r"\bsso\b", r"\boidc\b", r"\brbac\b",
    r"\bcrypto\b", r"\bcryptograph\w*", r"\bencrypt\w*", r"\bdecrypt\w*",
    r"\bjwt\b", r"\bxss\b", r"\bcsrf\b", r"\bsqli\b", r"\bsql injection\b",
    r"\bpii\b",
    r"\bpayment\w*", r"\bpayout\w*", r"\bbilling\b",
    r"\bsecrets?\b", r"\bcredential\w*",
    # irreversible operations
    r"\bdelet\w*", r"\bmigration\b", r"\bmigrate\b", r"\bschema\b",
    r"\bforce[- ]push\b", r"\bdrop table\b", r"\btruncate\b",
    # release / deploy / production
    r"\b(?:re)?deploy\w*", r"\breleases?\b", r"\bproduction\b",
    # high blast radius / shared utility
    r"\bblast radius\b", r"\bshared util\w*", r"\bshared utilit\w*",
    r"\bshared component\b", r"\bshared type\b",
]
_MARKERS = [re.compile(p, re.IGNORECASE) for p in _MARKER_PATTERNS]


def _brief_matches_tier3(brief):
    """Return the first matching marker pattern string, or None."""
    for rx in _MARKERS:
        if rx.search(brief):
            return rx.pattern
    return None


def _deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def main():
    # Kill-switch: fail-open before touching stdin (mirrors singularity hook).
    if os.environ.get("AE_TIER_GUARD_DISABLE") == "1":
        sys.exit(0)

    try:
        try:
            data = json.load(sys.stdin)
        except Exception:
            sys.exit(0)

        tool_name = data.get("tool_name")
        if tool_name not in ("Task", "Agent"):
            sys.exit(0)

        raw_tinput = data.get("tool_input")
        if not isinstance(raw_tinput, dict):
            sys.exit(0)
        tinput = raw_tinput

        agent = tinput.get("subagent_type")
        if agent not in MANDATED_TIER3:
            sys.exit(0)

        # Absent / null / non-string model param -> frontmatter default (Opus).
        model = tinput.get("model")
        if not isinstance(model, str) or not model.strip():
            sys.exit(0)

        # Any Opus model (alias "opus" or full id like claude-opus-4-8) -> allow.
        if "opus" in model.lower():
            sys.exit(0)

        # Explicit non-Opus downgrade on a mandated-Tier-3 agent.
        if agent == "security-auditor":
            _deny(
                f"{tool_name} spawn blocked: security-auditor was spawned with "
                f"model={model!r}, an explicit downgrade below Opus. The "
                "security-auditor spec mandates Tier 3 (Opus) unconditionally "
                "(METHODOLOGY.md Risk-Classification: Mandatory Tier-3 review "
                "escalation + Role-default tier table). Fix: omit the model "
                "param to use the Opus role default, or pass model: opus. "
                "To disable this guard: set AE_TIER_GUARD_DISABLE=1 and restart "
                "Claude Code."
            )

        # agent == "skeptic": deny only if the brief reads high-stakes.
        brief = (
            str(tinput.get("prompt") or "")
            + " "
            + str(tinput.get("description") or "")
        )
        marker = _brief_matches_tier3(brief)
        if marker is not None:
            _deny(
                f"{tool_name} spawn blocked: skeptic was spawned with "
                f"model={model!r}, an explicit downgrade below Opus, but the "
                f"brief matches a Tier-3 escalation signal (pattern {marker!r}). "
                "Per METHODOLOGY.md Risk-Classification (Mandatory Tier-3 review "
                "escalation), a Skeptic reviewing a security/irreversible/"
                "high-blast-radius/release unit MUST be Tier 3 (Opus). Fix: omit "
                "the model param to use the Opus role default, or pass "
                "model: opus. If this unit is genuinely not Tier-3 and you intend "
                "a budget review, set AE_TIER_GUARD_DISABLE=1 and restart."
            )

        # Non-mandated skeptic with a benign brief -> allow the downgrade.
        sys.exit(0)

    except Exception:
        # Defense-in-depth: any unexpected error exits 0 (fail-open).
        sys.exit(0)


if __name__ == "__main__":
    main()
