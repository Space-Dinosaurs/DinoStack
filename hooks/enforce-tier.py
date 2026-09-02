#!/usr/bin/env python3
"""
Purpose: PreToolUse hook that backstops the METHODOLOGY §Risk-Classification
         "Mandatory Tier-3 review escalation" rule on Claude Code by denying an
         EXPLICIT model downgrade below Tier-3-or-above on a mandated-Tier-3
         review spawn. As of PR #313 the skeptic and security-auditor
         frontmatter default to model: opus, so OMITTING the model param
         already yields Tier 3. The only way to get a sub-Tier-3 review is an
         explicit downgrade param - so this hook gates on "explicit
         sub-Tier-3 model param" (anything not matching TIER3_OR_ABOVE_MARKERS
         - "opus" or "fable", per DS-226), the precise, low-false-positive
         signal. Escalate-only: it never blocks the omit-the-param
         (role-default) path, and never touches non-review agents.

         As of DS-77, the hook ALSO backstops the "Mandatory Tier-3 authoring
         escalation (Plan+ADR-tier units)" rule for AUTHORING roles (architect,
         adr-generator, product-discovery): it denies an explicit
         sub-Tier-3 model param on those spawns when the brief matches an authoring
         Tier-3 escalation marker (ADR / cross-track / architecture-decision
         vocabulary). See the "authoring roles" Failure-modes carve-out below
         for the important limitations of this backstop.

         NOTE - Task/Agent rename: Claude Code renamed the subagent-spawn tool
         from "Task" to "Agent". This hook guards on BOTH names
         (`tool_name in ("Task", "Agent")`). install.sh wires both matcher
         blocks; the internal guard is belt-and-suspenders.

         security-auditor: ANY explicit sub-Tier-3 downgrade is denied (spec
         mandates Tier 3 unconditionally). skeptic: an explicit sub-Tier-3
         downgrade is denied ONLY when the spawn brief (prompt + description)
         matches a Tier-3 escalation marker - a non-mandated skeptic may
         legitimately run a cheaper model (e.g. budget mode). architect /
         adr-generator / product-discovery: an explicit sub-Tier-3 downgrade is
         denied ONLY when the spawn brief matches an authoring Tier-3
         escalation marker (independent marker list from the review-role one).

Public API: Run as a Claude Code PreToolUse hook (matcher: "Task" or "Agent").
            Reads JSON from stdin, writes hookSpecificOutput JSON to stdout when
            denying, exits 0 always.

Upstream deps: Python 3 stdlib only (json, os, re, sys, importlib.util). No
               external deps. `from __future__ import annotations` keeps the
               file importable on Python 3.8/3.9 (PEP 604 `X | None` hints
               would crash there; the other enforce-*.py hooks avoid union
               syntax for the same reason). Also a soft-dependency on the
               sibling hooks/lib/enforcement_log.py fire-logging helper
               (dynamic import, fails open to a no-op logger).

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
    - Non-review, non-authoring subagent_type, absent model param, or any
      Tier-3-or-above (opus/fable) model: allow.
    - Coverage gap (documented, intentional; scoped to the REVIEW-role /
      `_MARKERS` path only - see the separate authoring-roles carve-out below
      for the authoring-role path): the "novel architecture constraining
      future choices" Tier-3 signal is NOT keyword-detectable without
      over-firing on routine reviews, so it is NOT mechanically caught here
      for skeptic/security-auditor spawns. The conductor's explicit
      model: opus and the skeptic frontmatter default remain the controls for
      that signal. This hook backstops the other four escalation signal
      categories for review roles (security/auth/crypto/payments/secrets;
      irreversible; release/deploy/production; high blast radius/shared
      utility).
    - Authoring roles (architect / adr-generator / product-discovery) carve-out
      (documented, intentional): the true trigger for the "Mandatory Tier-3
      authoring escalation" rule is a STRUCTURAL signal - the unit reaches
      Plan+ADR tier (cross-track span, or "architecture decision constraining
      future choices") per the Planning Artifacts trigger table
      (content/sections/03-planning-artifacts.md) - computed by the CONDUCTOR,
      not present anywhere in tool_input. This hook therefore CANNOT
      deterministically detect an ADR-tier authoring spawn; the PRIMARY
      control is the conductor passing model: opus explicitly (see
      content/references/risk-config-and-tiers.md §Mandatory Tier-3 authoring
      escalation). This hook only BACKSTOPS an explicit sub-Opus downgrade
      when the brief matches `_AUTHOR_MARKER_PATTERNS` - best-effort, and it
      WILL MISS an ADR-tier authoring spawn whose brief omits that vocabulary
      (this hook only backstops an explicit sub-Tier-3 downgrade).
      Critically, an OMITTED model param on an authoring-role spawn resolves
      to the Sonnet frontmatter default (Role-default tier table) and is
      ALLOWED by this hook - the omit path is the conductor's responsibility
      to get right, not this hook's; operators must not over-trust this
      backstop as a substitute for the conductor's explicit param.
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
# content/references/risk-config-and-tiers.md Role-default tier table.
MANDATED_TIER3 = {"skeptic", "security-auditor"}

# Authoring roles whose Tier-3 escalation is CONDUCTOR-declared (model: opus) on
# Plan+ADR-tier units (cross-track / architecture-constraining), per the
# "Mandatory Tier-3 review escalation" rule in
# content/references/risk-config-and-tiers.md. These roles default to Sonnet/Tier 2
# (Role-default tier table) - the escalation is a CONDITIONAL rule, not a default.
# This hook only backstops an explicit sub-Opus downgrade when the brief names the
# architecture/ADR signal; it CANNOT see the structural Plan+ADR trigger. See the
# manifest Failure modes "authoring roles" carve-out.
MANDATED_TIER3_AUTHOR = {"architect", "adr-generator", "product-discovery"}

# Tier-3-or-above model markers (case-insensitive substrings of the model
# param). Opus and Fable (the tier above Opus) both satisfy Tier 3 or above;
# this is a floor WIDENING (DS-226) - every existing sonnet/haiku/other deny
# path is unchanged.
TIER3_OR_ABOVE_MARKERS = ("opus", "fable")

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

# Tier-3 AUTHORING escalation markers (case-insensitive, word-boundary
# anchored), independent of _MARKER_PATTERNS above - these track the
# structural "Plan+ADR tier" signal (cross-track / architecture-decision-
# constraining) from the Planning Artifacts trigger table, not the review-role
# signal categories. \badr\b is word-boundary anchored so it does not match
# "author"/"adroit" (substring trap).
_AUTHOR_MARKER_PATTERNS = [
    r"\badr\b",
    r"\bcross[- ]track\b",
    r"\barchitectur\w*[- ]decision\b",
    r"\bconstrain\w* future choices\b",
    r"\bplan\s*\+\s*adr\b",
    r"\bplan[- ]?tier\b",
    r"\bnovel architecture\b",
]
_AUTHOR_MARKERS = [re.compile(p, re.IGNORECASE) for p in _AUTHOR_MARKER_PATTERNS]


def _brief_matches_tier3(brief):
    """Return the first matching marker pattern string, or None."""
    for rx in _MARKERS:
        if rx.search(brief):
            return rx.pattern
    return None


def _author_brief_matches(brief):
    """Return the first matching authoring-escalation marker pattern string, or None."""
    for rx in _AUTHOR_MARKERS:
        if rx.search(brief):
            return rx.pattern
    return None


def _load_log_fire():
    """Best-effort dynamic import of the shared fire-logging helper.

    Falls back to a no-op when the sibling module cannot be loaded (missing
    file, syntax error, snapshot copy drift) - fire-logging is additive
    telemetry, never a hard dependency of the enforcement decision itself.

    Called lazily from inside the deny branch (never at module scope) so the
    overwhelming majority of invocations - every silent allow, and every
    kill-switched invocation that exits before main() runs its checks - never
    read, compile, or exec this file at all.
    """
    try:
        import importlib.util as _ilu

        here = os.path.dirname(os.path.abspath(__file__))
        mod_path = os.path.join(here, "lib", "enforcement_log.py")
        spec = _ilu.spec_from_file_location("enforcement_log", mod_path)
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.log_fire
    except Exception:
        return lambda *a, **k: None


def _deny(data, reason):
    # Decision print comes FIRST, unconditionally. Telemetry is loaded and
    # called only after the decision has reached stdout, and is wrapped in
    # its own try/except so a raising log_fire (e.g. a signature mismatch
    # from a half-applied lib snapshot) can never suppress or follow this
    # deny - see hooks/lib/enforcement_log.py manifest "Failure modes".
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    try:
        _load_log_fire()(data, "enforce-tier", "deny", reason)
    except Exception:
        pass
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
        if agent not in MANDATED_TIER3 and agent not in MANDATED_TIER3_AUTHOR:
            sys.exit(0)

        # Absent / null / non-string model param -> frontmatter default (Opus).
        model = tinput.get("model")
        if not isinstance(model, str) or not model.strip():
            sys.exit(0)

        # Any Tier-3-or-above model (alias "opus"/"fable" or a full id like
        # claude-opus-4-8 / claude-fable-5-1) -> allow.
        model_lower = model.lower()
        if any(marker in model_lower for marker in TIER3_OR_ABOVE_MARKERS):
            sys.exit(0)

        brief = (
            str(tinput.get("prompt") or "")
            + " "
            + str(tinput.get("description") or "")
        )

        # Explicit sub-Tier-3 downgrade on a mandated-Tier-3 agent.
        if agent == "security-auditor":
            _deny(
                data,
                f"{tool_name} spawn blocked: security-auditor was spawned with "
                f"model={model!r}, an explicit downgrade below Tier 3. The "
                "security-auditor spec mandates Tier 3 (Opus or above) unconditionally "
                "(METHODOLOGY.md Risk-Classification: Mandatory Tier-3 review "
                "escalation + Role-default tier table). Fix: omit the model "
                "param to use the Opus role default, or pass model: opus (or fable). "
                "To disable this guard: set AE_TIER_GUARD_DISABLE=1 and restart "
                "Claude Code."
            )

        # Authoring roles (architect / adr-generator / product-discovery): deny
        # only when the brief matches an authoring Tier-3 escalation marker.
        # These roles default to Sonnet - an omitted model param is ALLOWED
        # (see manifest Failure modes "authoring roles" carve-out). Placed
        # before the skeptic branch so an author agent never falls through to
        # skeptic-only logic.
        if agent in MANDATED_TIER3_AUTHOR:
            marker = _author_brief_matches(brief)
            if marker is not None:
                _deny(
                    data,
                    f"{tool_name} spawn blocked: {agent} was spawned with "
                    f"model={model!r}, an explicit downgrade below Tier 3, but "
                    "the brief matches an authoring Tier-3 escalation signal "
                    f"(pattern {marker!r}). Per the Mandatory Tier-3 review "
                    "escalation rule, an architect/adr-generator/"
                    "product-discovery authoring a Plan+ADR-tier (cross-track "
                    "/ architecture-constraining) unit MUST be Tier 3 (Opus or "
                    "above). "
                    "Fix: pass model: opus (or fable) on this spawn. (Do NOT omit the "
                    "model param - these roles default to Sonnet. To disable "
                    "this guard: set AE_TIER_GUARD_DISABLE=1 and restart "
                    "Claude Code.)"
                )
            sys.exit(0)

        # agent == "skeptic": deny only if the brief reads high-stakes.
        marker = _brief_matches_tier3(brief)
        if marker is not None:
            _deny(
                data,
                f"{tool_name} spawn blocked: skeptic was spawned with "
                f"model={model!r}, an explicit downgrade below Tier 3, but the "
                f"brief matches a Tier-3 escalation signal (pattern {marker!r}). "
                "Per METHODOLOGY.md Risk-Classification (Mandatory Tier-3 review "
                "escalation), a Skeptic reviewing a security/irreversible/"
                "high-blast-radius/release unit MUST be Tier 3 (Opus or above). Fix: "
                "omit the model param to use the Opus role default, or pass "
                "model: opus (or fable). If this unit is genuinely not Tier-3 and you intend "
                "a budget review, set AE_TIER_GUARD_DISABLE=1 and restart."
            )

        # Non-mandated skeptic with a benign brief -> allow the downgrade.
        sys.exit(0)

    except Exception:
        # Defense-in-depth: any unexpected error exits 0 (fail-open).
        sys.exit(0)


if __name__ == "__main__":
    main()
