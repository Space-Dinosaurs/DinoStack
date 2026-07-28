# Run with: python3 hooks/tests/test-enforce-no-abdication.py
"""
Unit + smoke tests for hooks/enforce-no-abdication.py.

Each case pipes a JSON payload into the hook via stdin and asserts ALLOW
(exit 0, no stdout) or BLOCK (exit 0, {"decision":"block","reason":"..."}).

The smoke checks at the bottom pipe crafted payloads into the actual hook
process to verify the end-to-end block/allow behavior, including valid-JSON
output shape.

Test coverage:
  - Kill-switch (AE_ABDICATION_GUARD_DISABLE=1) -> ALLOW
  - stop_hook_active=true -> ALLOW (primary re-entrancy guard)
  - Config disabled (abdication_guard_enabled not true) -> ALLOW
  - Config enabled + abdication message -> BLOCK with valid JSON
  - Config enabled + non-abdication message -> ALLOW
  - last_assistant_message field present (both cases)
  - transcript_path fallback when last_assistant_message absent
  - Each positive permission phrase
  - Each hard-stop negative gate token
  - (recommended) and "proceeding with" negative gate
  - Counter increments and CAP halts blocking
  - Counter resets on new user turn (via user_msg_count advance)
  - Corrupt counter file -> treated as 0
  - DS-109: counter tmp is pid-suffixed; a peer's in-flight tmp (legacy fixed
    name or a different pid's suffixed name) survives our write untouched
  - Malformed stdin -> ALLOW (fail-open)
  - Smoke: abdicating payload -> exactly one valid JSON block object
  - Smoke: clean payload -> empty stdout
  - Prose-ballot: 2-item 'Operator decisions' block, no recommendations -> BLOCK
  - Prose-ballot: same block, every item recommended -> ALLOW
  - Prose-ballot: single-item block -> ALLOW
  - Prose-ballot: ballot saturated with negative-gate vocabulary still BLOCKs
    (the escape this check exists to close)
  - Prose-ballot: mixed block (1 recommended + 1 unrecommended item) -> ALLOW
  - Negative gate regression: a genuine single irreversible-action
    confirmation (no Operator decisions heading) still passes -> ALLOW
  - REGRESSION: verbatim real-world 5-item bold-numbered ballot fires
  - Prose-ballot: bold-numbered bare/all-recommended/single-item/fenced-body/
    mixed-formatting variants
  - REGRESSION (Skeptic MAJOR 2): indented sub-bullets not counted as items
  - REGRESSION (Skeptic MAJOR 3): heading quoted inside a fence -> ALLOW
  - REGRESSION (Skeptic MAJOR 4): narrative paragraphs, no list syntax,
    under the heading -> ALLOW (no paragraph-mode fallback)
  - Heading tightening: 3-hash heading and trailing-colon heading -> BLOCK
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import shutil

HOOK_PATH = os.path.join(
    os.path.dirname(__file__), "..", "enforce-no-abdication.py"
)

# Mirrors CONSECUTIVE_BLOCK_CAP in enforce-no-abdication.py. The hook runs as a
# subprocess so we cannot import the constant; this is a fixed-contract value.
CONSECUTIVE_BLOCK_CAP = 2

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_hook(
    payload: str,
    env: dict | None = None,
    timeout: int = 10,
) -> tuple[int, str, str]:
    merged_env = os.environ.copy()
    # Default: disable kill-switch so tests can exercise the normal path.
    merged_env.pop("AE_ABDICATION_GUARD_DISABLE", None)
    if env:
        merged_env.update(env)
    result = subprocess.run(
        [sys.executable, HOOK_PATH],
        input=payload,
        capture_output=True,
        text=True,
        env=merged_env,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def is_allow(returncode: int, stdout: str) -> bool:
    """ALLOW: exit 0 and no block decision in stdout."""
    if returncode != 0:
        return False
    stripped = stdout.strip()
    if not stripped:
        return True
    try:
        obj = json.loads(stripped)
        return obj.get("decision") != "block"
    except Exception:
        return True  # unparseable output -> not a block


def is_block(returncode: int, stdout: str) -> bool:
    """BLOCK: exit 0, {"decision":"block","reason":<non-empty str>} on stdout."""
    if returncode != 0:
        return False
    stripped = stdout.strip()
    if not stripped:
        return False
    try:
        obj = json.loads(stripped)
        return (
            obj.get("decision") == "block"
            and isinstance(obj.get("reason"), str)
            and len(obj["reason"]) > 0
        )
    except Exception:
        return False


def make_config_file(tmp_dir: str, enabled: bool = True) -> str:
    """Write a .agentic/config.json with abdication_guard_enabled set."""
    agentic_dir = os.path.join(tmp_dir, ".agentic")
    os.makedirs(agentic_dir, exist_ok=True)
    config_path = os.path.join(agentic_dir, "config.json")
    with open(config_path, "w") as f:
        json.dump({"abdication_guard_enabled": enabled}, f)
    return config_path


def make_transcript(tmp_dir: str, messages: list[dict]) -> str:
    """Write a JSONL transcript file and return its path."""
    path = os.path.join(tmp_dir, "transcript.jsonl")
    with open(path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")
    return path


# An abdication message that should trigger a block.
ABDICATING_MSG = "I've analyzed the problem. Would you like me to proceed with the fix?"

# A clean message that should not trigger a block.
CLEAN_MSG = "I've analyzed the problem and found the root cause. The fix involves updating the timeout parameter in config.ts."

# ---------------------------------------------------------------------------
# Test cases using last_assistant_message field (no transcript needed)
# ---------------------------------------------------------------------------

def make_payload(
    cwd: str,
    last_assistant_message: str | None = None,
    stop_hook_active: bool = False,
    transcript_path: str = "",
) -> str:
    payload: dict = {
        "hook_event_name": "Stop",
        "session_id": "test-session-001",
        "cwd": cwd,
        "stop_hook_active": stop_hook_active,
        "permission_mode": "default",
    }
    if last_assistant_message is not None:
        payload["last_assistant_message"] = last_assistant_message
    if transcript_path:
        payload["transcript_path"] = transcript_path
    return json.dumps(payload)


def run_cases(cases: list[tuple[str, str, str, dict | None]]) -> int:
    """Run a list of (label, payload, expected, env) tuples. Returns fail count."""
    failed = 0
    for label, payload, expected, env in cases:
        rc, stdout, stderr = run_hook(payload, env=env)
        if expected == "ALLOW":
            ok = is_allow(rc, stdout)
        else:
            ok = is_block(rc, stdout)
        status = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"  [{status}] {label}")
        if not ok:
            print(f"         expected: {expected}")
            print(f"         rc:       {rc}")
            print(f"         stdout:   {stdout!r}")
            print(f"         stderr:   {stderr!r}")
    return failed


# ---------------------------------------------------------------------------
# Build test cases
# ---------------------------------------------------------------------------

def build_cases(tmp_dir: str) -> list[tuple[str, str, str, dict | None]]:
    make_config_file(tmp_dir, enabled=True)
    disabled_dir = os.path.join(tmp_dir, "disabled_cwd")
    os.makedirs(disabled_dir, exist_ok=True)
    make_config_file(disabled_dir, enabled=False)

    no_config_dir = os.path.join(tmp_dir, "no_config_cwd")
    os.makedirs(no_config_dir, exist_ok=True)

    cases: list[tuple[str, str, str, dict | None]] = []

    # --- Kill-switch ---
    cases.append((
        "Kill-switch AE_ABDICATION_GUARD_DISABLE=1 -> ALLOW",
        make_payload(tmp_dir, last_assistant_message=ABDICATING_MSG),
        "ALLOW",
        {"AE_ABDICATION_GUARD_DISABLE": "1"},
    ))

    # --- stop_hook_active ---
    cases.append((
        "stop_hook_active=true -> ALLOW (primary re-entrancy guard)",
        make_payload(tmp_dir, last_assistant_message=ABDICATING_MSG, stop_hook_active=True),
        "ALLOW",
        None,
    ))

    # --- Config checks ---
    cases.append((
        "Config disabled (abdication_guard_enabled=false) -> ALLOW",
        make_payload(disabled_dir, last_assistant_message=ABDICATING_MSG),
        "ALLOW",
        None,
    ))
    cases.append((
        "Config absent (no config.json) -> ALLOW (fail-open default off)",
        make_payload(no_config_dir, last_assistant_message=ABDICATING_MSG),
        "ALLOW",
        None,
    ))

    # --- Core block/allow on last_assistant_message ---
    cases.append((
        "Abdication msg ('Would you like me to proceed') -> BLOCK",
        make_payload(tmp_dir, last_assistant_message=ABDICATING_MSG),
        "BLOCK",
        None,
    ))
    cases.append((
        "Clean msg (no permission phrase) -> ALLOW",
        make_payload(tmp_dir, last_assistant_message=CLEAN_MSG),
        "ALLOW",
        None,
    ))

    # --- Malformed stdin ---
    cases.append((
        "Malformed stdin -> ALLOW (fail-open)",
        "not-json",
        "ALLOW",
        None,
    ))
    cases.append((
        "Empty stdin -> ALLOW (fail-open)",
        "",
        "ALLOW",
        None,
    ))

    # --- Positive patterns (each phrase) ---
    # Each phrase test uses a fresh isolated subdirectory so counter state from
    # prior block events does not accumulate and hit the CAP before all phrases
    # are tested. (The cap test exercises counter accumulation separately.)
    for i, phrase_msg in enumerate([
        "want me to",
        "should I",
        "shall I",
        "would you like me to",
        "do you want me to",
        "let me know if you'd like",
        "ready to proceed",
        "should I go ahead",
        "want me to go ahead",
    ]):
        phrase_dir = os.path.join(tmp_dir, f"phrase_{i}")
        os.makedirs(phrase_dir, exist_ok=True)
        make_config_file(phrase_dir, enabled=True)
        msg = f"I've finished the analysis. {phrase_msg.capitalize()} continue with the implementation?"
        cases.append((
            f"Positive phrase '{phrase_msg}' + question mark -> BLOCK",
            make_payload(phrase_dir, last_assistant_message=msg),
            "BLOCK",
            None,
        ))

    # --- Negative gate tokens ---
    for gate_token in [
        "destructive",
        "irreversible",
        "force push",
        "force-push",
        "delete",
        "drop table",
        "schema migration",
        "production deploy",
        "cannot derive",
        "missing credential",
        "api key",
        "which environment",
        "which workspace",
        "merge to main",
    ]:
        msg = f"This operation is {gate_token}. Should I proceed?"
        cases.append((
            f"Negative gate '{gate_token}' suppresses block -> ALLOW",
            make_payload(tmp_dir, last_assistant_message=msg),
            "ALLOW",
            None,
        ))

    # --- Negative gate: irreversibility phrasings (Skeptic Major #2) ---
    # Full-sentence probes that previously wrongly BLOCKED.
    irreversibility_probes = [
        "This permanently removes the production database and cannot be undone. Should I proceed?",
        "This will permanently delete every record. Want me to proceed?",
        "This permanently wipes the cache. Should I go ahead?",
        "This action can't be undone. Want me to proceed?",
        "This will overwrite the existing file. Should I proceed?",
        "The data is unrecoverable after this. Want me to proceed?",
        "There is no undo for this step. Should I proceed?",
        "This risks data loss. Want me to proceed?",
    ]
    for i, probe in enumerate(irreversibility_probes):
        cases.append((
            f"Irreversibility probe #{i} suppresses block -> ALLOW",
            make_payload(tmp_dir, last_assistant_message=probe),
            "ALLOW",
            None,
        ))

    # --- Negative gate: product-judgment / design-fork (Skeptic Major #3) ---
    fork_probes = [
        "The choice changes the data model. Which direction do you want me to take?",
        "There are two viable paths. Which approach should I use?",
        "Which option do you want me to implement?",
        "Which of these schemas should I commit to?",
        "This changes the schema in a way that is hard to reverse. Should I proceed?",
        "This is a load-bearing decision. Want me to proceed?",
        "This is a design decision with long-term impact. Should I proceed?",
        "This changes the api contract. Want me to proceed?",
    ]
    for i, probe in enumerate(fork_probes):
        cases.append((
            f"Design-fork probe #{i} suppresses block -> ALLOW",
            make_payload(tmp_dir, last_assistant_message=probe),
            "ALLOW",
            None,
        ))

    # --- Special negative gates: (recommended) and proceeding with ---
    cases.append((
        "'(recommended)' suffix suppresses block -> ALLOW",
        make_payload(
            tmp_dir,
            last_assistant_message=(
                "Proceeding with approach A (recommended). Want me to start?"
            ),
        ),
        "ALLOW",
        None,
    ))
    cases.append((
        "'proceeding with' suppresses block -> ALLOW",
        make_payload(
            tmp_dir,
            last_assistant_message=(
                "Proceeding with the migration unless you say otherwise. Should I go ahead?"
            ),
        ),
        "ALLOW",
        None,
    ))
    cases.append((
        "'unless you say otherwise' suppresses block -> ALLOW",
        make_payload(
            tmp_dir,
            last_assistant_message=(
                "I'll use approach B unless you say otherwise. Want me to proceed?"
            ),
        ),
        "ALLOW",
        None,
    ))

    # --- No message text -> ALLOW ---
    cases.append((
        "Empty last_assistant_message + no transcript -> ALLOW",
        make_payload(tmp_dir, last_assistant_message=""),
        "ALLOW",
        None,
    ))

    # --- Sentence-granularity regression (line-vs-sentence false negative) ---
    # REGRESSION: the exact failing shape reported against the pre-fix hook.
    # _is_abdication used to check only the final non-empty LINE for a
    # trailing "?". A permission-seeking question followed by declarative
    # sentences on the same line (or subsequent lines) defeated it because
    # the last line ended in "." rather than "?".
    trailing_declaratives_dir = os.path.join(tmp_dir, "trailing_declaratives_cwd")
    os.makedirs(trailing_declaratives_dir, exist_ok=True)
    make_config_file(trailing_declaratives_dir, enabled=True)
    cases.append((
        "REGRESSION: permission question + trailing declaratives on same line -> BLOCK",
        make_payload(
            trailing_declaratives_dir,
            last_assistant_message=(
                "Two pre-existing bugs surfaced during QA:\n"
                "1. An operator hits an infinite redirect loop on a gated page.\n"
                "2. App-wide WCAG AA form-hint contrast debt.\n\n"
                "Want me to file those two as Linear tickets? Learnings captured "
                "to memory. Awaiting the deploy confirmation."
            ),
        ),
        "BLOCK",
        None,
    ))

    # Non-regression: a permission question with NO trailing text must still
    # fire (sentence-splitting must not weaken the original detection path).
    no_trailing_dir = os.path.join(tmp_dir, "no_trailing_cwd")
    os.makedirs(no_trailing_dir, exist_ok=True)
    make_config_file(no_trailing_dir, enabled=True)
    cases.append((
        "Permission question with no trailing text -> BLOCK (no regression)",
        make_payload(
            no_trailing_dir,
            last_assistant_message="I've finished the analysis. Should I proceed with the fix?",
        ),
        "BLOCK",
        None,
    ))

    # Trailing declarative text with NO permission question anywhere -> ALLOW.
    no_permission_dir = os.path.join(tmp_dir, "no_permission_cwd")
    os.makedirs(no_permission_dir, exist_ok=True)
    make_config_file(no_permission_dir, enabled=True)
    cases.append((
        "Trailing declaratives, no permission question -> ALLOW",
        make_payload(
            no_permission_dir,
            last_assistant_message=(
                "Filed the two tickets as DS-100 and DS-101. Learnings captured "
                "to memory. Awaiting the deploy confirmation."
            ),
        ),
        "ALLOW",
        None,
    ))

    # Precision guard: a permission phrase in a non-question sentence, with an
    # unrelated "?" appearing in a LATER sentence, must NOT fire. Same-sentence
    # co-occurrence is required, not mere tail co-presence.
    precision_dir = os.path.join(tmp_dir, "precision_cwd")
    os.makedirs(precision_dir, exist_ok=True)
    make_config_file(precision_dir, enabled=True)
    cases.append((
        "Precision: permission phrase and unrelated later '?' in different sentences -> ALLOW",
        make_payload(
            precision_dir,
            last_assistant_message=(
                "Should I proceed was my first instinct, but I went ahead and "
                "shipped it myself. Did the CI run finish yet?"
            ),
        ),
        "ALLOW",
        None,
    ))

    return cases


# ---------------------------------------------------------------------------
# Prose-ballot cases (content/sections/02-delegation.md "Operator decisions
# go last in the turn" + "AskUserQuestion precondition" - the ban on
# co-equal ballots applies identically to prose, not just the tool call.)
# ---------------------------------------------------------------------------

def build_prose_ballot_cases(tmp_dir: str) -> list[tuple[str, str, str, dict | None]]:
    cases: list[tuple[str, str, str, dict | None]] = []

    def fresh_dir(name: str) -> str:
        d = os.path.join(tmp_dir, name)
        os.makedirs(d, exist_ok=True)
        make_config_file(d, enabled=True)
        return d

    # --- 2-item ballot, no recommendations -> BLOCK ---
    cases.append((
        "Prose ballot: 2-item Operator decisions, no recommendations -> BLOCK",
        make_payload(
            fresh_dir("ballot_bare"),
            last_assistant_message=(
                "Found two viable migration strategies.\n\n"
                "## Operator decisions\n"
                "- Use a blue-green cutover: this reverses decision #203 and "
                "cannot be undone once the old cluster is decommissioned.\n"
                "- Use a rolling upgrade: this is a load-bearing decision "
                "that changes the schema in a way that is hard to reverse.\n"
            ),
        ),
        "BLOCK",
        None,
    ))

    # --- Same shape, every item recommended -> ALLOW ---
    cases.append((
        "Prose ballot: every item carries a recommendation -> ALLOW",
        make_payload(
            fresh_dir("ballot_all_recommended"),
            last_assistant_message=(
                "Found two decisions this turn.\n\n"
                "## Operator decisions\n"
                "- Cache eviction policy: Recommendation: LRU, matches the "
                "existing cache module. Reversible with a one-line config flip.\n"
                "- Retry backoff: use exponential backoff (Recommended) - "
                "matches src/http/client.ts. Reversible with a one-line revert.\n"
            ),
        ),
        "ALLOW",
        None,
    ))

    # --- Single item -> ALLOW ("A single item never fires") ---
    cases.append((
        "Prose ballot: single-item Operator decisions block -> ALLOW",
        make_payload(
            fresh_dir("ballot_single"),
            last_assistant_message=(
                "One decision this turn.\n\n"
                "## Operator decisions\n"
                "- Delete the stale branch: this is irreversible and cannot "
                "be undone. Proceeding requires your confirmation.\n"
            ),
        ),
        "ALLOW",
        None,
    ))

    # --- Ballot saturated with negative-gate vocabulary still fires ---
    # REGRESSION: this is the exact escape observed in the incident that
    # motivated this check - a ballot phrased with irreversibility/design-
    # fork tokens that would suppress _is_abdication's permission-phrase
    # check must NOT suppress the ballot check.
    cases.append((
        "REGRESSION: ballot saturated with negative-gate vocabulary still BLOCKs",
        make_payload(
            fresh_dir("ballot_negative_gate_saturated"),
            last_assistant_message=(
                "Two design forks surfaced during the migration.\n\n"
                "## Operator decisions\n"
                "- Option A: this is destructive, irreversible, and cannot "
                "be undone once merged - it permanently deletes the legacy "
                "table and reverses decision #203, a load-bearing design "
                "decision with schema migration implications.\n"
                "- Option B: this is a design fork requiring a force push "
                "to rewrite history; data loss is possible and unrecoverable "
                "if the wrong branch is targeted.\n"
            ),
        ),
        "BLOCK",
        None,
    ))

    # --- Mixed block: 1 recommended + 1 unrecommended -> ALLOW ---
    # "An item carrying a recommendation does not count toward the
    # violation" - only 1 of 2 items lacks a recommendation here, below the
    # 2-unrecommended threshold.
    cases.append((
        "Prose ballot: mixed block (1 recommended, 1 not) -> ALLOW",
        make_payload(
            fresh_dir("ballot_mixed"),
            last_assistant_message=(
                "One flagged item, one already resolved.\n\n"
                "## Operator decisions\n"
                "- Logging library: Recommendation: keep pino, matches "
                "existing usage across the service.\n"
                "- Retention window: needs your call, no default derivable "
                "from existing config.\n"
            ),
        ),
        "ALLOW",
        None,
    ))

    # --- No Operator decisions heading + genuine single irreversible
    # confirmation still passes the ORIGINAL negative gate (no regression
    # introduced by adding the ballot check). ---
    cases.append((
        "Negative-gate regression: single irreversible confirmation, no heading -> ALLOW",
        make_payload(
            fresh_dir("no_heading_single_confirm"),
            last_assistant_message=(
                "This permanently deletes the legacy table and cannot be "
                "undone. Should I proceed?"
            ),
        ),
        "ALLOW",
        None,
    ))

    # =========================================================================
    # REGRESSION (coordinator-verified escape): real conductor ballots use
    # bold-numbered paragraph items ("**1. Title.** body"), not markdown list
    # syntax. The original _ITEM_START_RE matched only "-", "*", and plain
    # numbered lines, so it detected ZERO items in a real 5-item ballot and
    # never fired. This is the VERBATIM real-world sample (structure and
    # wording matched to the actual conductor output that escaped detection):
    # items 2, 3, 4 carry "Recommendation:", items 1 and 5 do not - 2
    # unrecommended items should fire the guard. Item 1 also contains a
    # fenced code block, which must not itself be miscounted as a second item
    # or have its diff-like/list-like content misread as a new item marker.
    # =========================================================================
    REAL_BALLOT_SAMPLE = (
        "Wrapping up. Several things need your input before I continue.\n\n"
        "## Operator decisions\n\n"
        "**1. Run one command to unblock PR #516.** Force-push was denied "
        "to both the engineer and me. I traced it to a branch-protection "
        "rule that blocks force-push on any branch matching `feature/*` "
        "regardless of author. This is a repo-owner-only setting; I cannot "
        "change it myself. Run:\n\n"
        "```\n"
        "gh api repos/Space-Dinosaurs/DinoStack/branches/feature/tier-filter/protection -X DELETE\n"
        "```\n\n"
        "then re-run the rebase. There is no derivable default here - only "
        "you hold the permission to change branch protection.\n\n"
        "**2. PR #422 - rebase, extract, or close?** PR #422 has drifted "
        "far enough from main that a straight rebase would touch 40+ "
        "files. Recommendation: **extract the tier-filter mechanism** into "
        "its own PR and close #422 - the rest of its diff is already "
        "superseded by #480. Reversible: reopen #422 from its current "
        "branch tip if the extraction turns out wrong.\n\n"
        "**3. Approve removing rate-limit retries?** The retry loop added "
        "in #390 masks a genuine upstream 429 rather than backing off "
        "correctly, and every retry burns another API call against our "
        "quota. Recommendation: **approve**; one commit to revert.\n\n"
        "**4. Re-track evals/runner/ and evals/scoring/ in git?** These "
        "were gitignored during the early eval-harness spike and never "
        "re-added. Recommendation: **re-track the code** (not the "
        "generated output) - matches how the rest of evals/ is tracked.\n\n"
        "**5. Probe the SubagentStop payload with me present?** The only "
        "route to real cost and duration telemetry for subagent spawns is "
        "capturing a live SubagentStop payload, which requires you to "
        "trigger a subagent spawn while I watch stdin. This can't be "
        "scripted or deferred - it needs a live session with both of us "
        "present.\n"
    )
    cases.append((
        "REGRESSION (real ballot sample, coordinator-verified escape): "
        "5-item bold-numbered ballot, items 1+5 unrecommended -> BLOCK",
        make_payload(
            fresh_dir("real_ballot_sample"),
            last_assistant_message=REAL_BALLOT_SAMPLE,
        ),
        "BLOCK",
        None,
    ))

    # --- Bold-numbered items, 2+ without a recommendation -> BLOCK ---
    cases.append((
        "Bold-numbered ballot: 2 items, no recommendations -> BLOCK",
        make_payload(
            fresh_dir("bold_numbered_bare"),
            last_assistant_message=(
                "## Operator decisions\n\n"
                "**1. Delete the orphaned branch?** This is irreversible "
                "once merged and cannot be undone.\n\n"
                "**2. Rotate the leaked token?** This is a design decision "
                "with long-term impact on the auth flow.\n"
            ),
        ),
        "BLOCK",
        None,
    ))

    # --- Bold-numbered items, every item carries Recommendation: -> ALLOW ---
    cases.append((
        "Bold-numbered ballot: every item carries Recommendation: -> ALLOW",
        make_payload(
            fresh_dir("bold_numbered_all_recommended"),
            last_assistant_message=(
                "## Operator decisions\n\n"
                "**1. Cache eviction policy.** Recommendation: **LRU** - "
                "matches the existing cache module.\n\n"
                "**2. Retry backoff.** Recommendation: **exponential** - "
                "matches src/http/client.ts.\n"
            ),
        ),
        "ALLOW",
        None,
    ))

    # --- Single bold-numbered item with no recommendation -> ALLOW ---
    cases.append((
        "Single bold-numbered item, no recommendation -> ALLOW",
        make_payload(
            fresh_dir("bold_numbered_single"),
            last_assistant_message=(
                "## Operator decisions\n\n"
                "**1. Delete the stale branch?** This is irreversible and "
                "cannot be undone. Proceeding requires your confirmation.\n"
            ),
        ),
        "ALLOW",
        None,
    ))

    # --- One item plus a fenced code block -> ALLOW (fence != second item) ---
    cases.append((
        "Bold-numbered single item with a fenced code block body -> ALLOW",
        make_payload(
            fresh_dir("bold_numbered_single_with_fence"),
            last_assistant_message=(
                "## Operator decisions\n\n"
                "**1. Run this command to unblock the branch.** This is "
                "irreversible and cannot be undone. Run:\n\n"
                "```\n"
                "- this diff-style line must not be read as a bullet item\n"
                "+ neither must this one\n"
                "```\n\n"
                "There is no derivable default here.\n"
            ),
        ),
        "ALLOW",
        None,
    ))

    # --- Mixed formatting: one markdown list item + one bold-numbered item,
    # both unrecommended -> BLOCK ---
    cases.append((
        "Mixed formatting: 1 markdown-list item + 1 bold-numbered item, "
        "both unrecommended -> BLOCK",
        make_payload(
            fresh_dir("mixed_formatting_ballot"),
            last_assistant_message=(
                "## Operator decisions\n"
                "- Rotate the signing key: this is a design decision with "
                "long-term impact and cannot be undone once rotated.\n\n"
                "**2. Approve the schema migration?** This changes the "
                "schema in a way that is hard to reverse.\n"
            ),
        ),
        "BLOCK",
        None,
    ))

    # =========================================================================
    # MAJOR 2 REGRESSION (Skeptic-verified): indented sub-bullets under a
    # single fully-recommended item were counted as separate top-level items.
    # An indented "- the DCO check passed" is a supporting detail of its
    # parent item, not a new decision, and must not be counted.
    # =========================================================================
    cases.append((
        "REGRESSION (Skeptic MAJOR 2): single recommended item with 2 "
        "indented sub-bullets -> ALLOW (sub-bullets not counted as items)",
        make_payload(
            fresh_dir("indented_sub_bullets_single_item"),
            last_assistant_message=(
                "## Operator decisions\n\n"
                "**1. Merge PR #516.** Recommendation: merge now; CI is "
                "green.\n"
                "   - the DCO check passed\n"
                "   - the adapter-sync check passed\n"
            ),
        ),
        "ALLOW",
        None,
    ))
    cases.append((
        "REGRESSION (Skeptic MAJOR 2): 2 recommended items, each with an "
        "indented sub-bullet -> ALLOW",
        make_payload(
            fresh_dir("indented_sub_bullets_two_items"),
            last_assistant_message=(
                "## Operator decisions\n\n"
                "**1. Merge PR #516.** Recommendation: merge now.\n"
                "   - CI is green\n\n"
                "**2. Close DS-114.** Recommendation: close as done.\n"
                "   - all acceptance criteria met\n"
            ),
        ),
        "ALLOW",
        None,
    ))

    # =========================================================================
    # MAJOR 3 REGRESSION (Skeptic-verified): the heading was searched for in
    # UNMASKED text, so a fenced example quoting this rule's own heading
    # text (a PR body explaining this change, a /ds-wrap note, a Skeptic
    # digest) would match and swallow everything after the fence as a fake
    # "block". Fences must be masked before the heading search runs.
    # =========================================================================
    cases.append((
        "REGRESSION (Skeptic MAJOR 3): heading text quoted inside a fenced "
        "example -> ALLOW (fence masked before heading search)",
        make_payload(
            fresh_dir("heading_inside_fence"),
            last_assistant_message=(
                "This PR adds detection for a specific block shape:\n\n"
                "```\n"
                "## Operator decisions\n"
                "- Option A: no recommendation given\n"
                "- Option B: no recommendation given\n"
                "```\n\n"
                "That's the shape the hook now catches. Implementation "
                "complete, quality gates pass.\n"
            ),
        ),
        "ALLOW",
        None,
    ))

    # =========================================================================
    # MAJOR 4 REGRESSION (Skeptic-verified): the removed paragraph-mode
    # fallback over-fired on ordinary non-ballot narrative under the
    # heading. With the fallback removed, a "nothing to decide" narrative
    # with no list/number syntax must never fire (returns 0 items, below
    # the 2-item threshold), even though it is 2 blank-line-separated
    # paragraphs.
    # =========================================================================
    cases.append((
        "REGRESSION (Skeptic MAJOR 4): narrative paragraphs, no list "
        "syntax, under the heading -> ALLOW (no paragraph-mode fallback)",
        make_payload(
            fresh_dir("narrative_no_list_syntax"),
            last_assistant_message=(
                "## Operator decisions\n\n"
                "None this turn. Everything was derivable from the five "
                "default sources.\n\n"
                "I proceeded with the worktree-isolated engineer per "
                "AGENTS.md.\n"
            ),
        ),
        "ALLOW",
        None,
    ))

    # --- Heading tightening: 3-hash heading must still be caught ---
    cases.append((
        "Heading tightening: '### Operator decisions' (3-hash) -> BLOCK",
        make_payload(
            fresh_dir("heading_three_hash"),
            last_assistant_message=(
                "### Operator decisions\n\n"
                "- Option A: no recommendation given, design decision.\n"
                "- Option B: no recommendation given, load-bearing.\n"
            ),
        ),
        "BLOCK",
        None,
    ))

    # --- Heading tightening: trailing colon must still be caught ---
    cases.append((
        "Heading tightening: '## Operator decisions:' (trailing colon) -> BLOCK",
        make_payload(
            fresh_dir("heading_trailing_colon"),
            last_assistant_message=(
                "## Operator decisions:\n\n"
                "- Option A: no recommendation given, design decision.\n"
                "- Option B: no recommendation given, load-bearing.\n"
            ),
        ),
        "BLOCK",
        None,
    ))

    return cases


# ---------------------------------------------------------------------------
# Counter tests (require filesystem state)
# ---------------------------------------------------------------------------

def test_counter_cap(tmp_dir: str) -> int:
    """Test that the counter cap halts blocking after CONSECUTIVE_BLOCK_CAP fires."""
    print("\n  [Counter cap tests]")
    failed = 0
    cap_dir = os.path.join(tmp_dir, "cap_cwd")
    os.makedirs(cap_dir, exist_ok=True)
    make_config_file(cap_dir, enabled=True)
    agentic_dir = os.path.join(cap_dir, ".agentic")

    # Seed the counter at CAP - 1 (1) with no user messages yet.
    counter_path = os.path.join(agentic_dir, ".abdication-guard-fire-count")
    with open(counter_path, "w") as f:
        json.dump({"count": 1, "last_user_msg_count": 0}, f)

    # First call: count=1, last_user_msg_count=0, no transcript -> should still block
    # (count < CAP=2) and increment to 2.
    payload1 = make_payload(cap_dir, last_assistant_message=ABDICATING_MSG)
    rc1, stdout1, _ = run_hook(payload1)
    ok1 = is_block(rc1, stdout1)
    print(f"    [{'PASS' if ok1 else 'FAIL'}] Counter at 1/2 -> BLOCK (fires, increments to 2)")
    if not ok1:
        failed += 1
        print(f"         rc={rc1} stdout={stdout1!r}")

    # Read counter - should now be 2.
    with open(counter_path) as f:
        state = json.load(f)
    ok_count = state["count"] == 2
    print(f"    [{'PASS' if ok_count else 'FAIL'}] Counter incremented to 2")
    if not ok_count:
        failed += 1

    # Second call: count=2 = CAP -> should NOT block.
    payload2 = make_payload(cap_dir, last_assistant_message=ABDICATING_MSG)
    rc2, stdout2, _ = run_hook(payload2)
    ok2 = is_allow(rc2, stdout2)
    print(f"    [{'PASS' if ok2 else 'FAIL'}] Counter at CAP=2 -> ALLOW (halted)")
    if not ok2:
        failed += 1
        print(f"         rc={rc2} stdout={stdout2!r}")

    return failed


def test_54360_loop_terminates(tmp_dir: str) -> int:
    """REGRESSION (Skeptic CRITICAL): the #54360 infinite-loop scenario.

    Simulates: stop_hook_active NEVER flips to true across re-entries (CC bug
    #54360), AND the model runs tools while "proceeding" so the transcript
    accumulates tool_result lines recorded as type:"user" between blocks.

    The OLD _count_user_messages counted those tool_result lines as user turns,
    so current_user_msg_count inflated on every re-entry, the reset condition
    (current > last) fired every time, count was pinned at 1, the CAP was never
    reached, and the hook blocked FOREVER.

    After the fix, tool_result and meta lines are NOT counted as genuine human
    turns, so the user-turn count stays flat across re-entries, the counter
    accumulates, and blocking STOPS at CONSECUTIVE_BLOCK_CAP. This test fails
    against the pre-fix code and passes after.
    """
    print("\n  [#54360 loop-termination regression]")
    failed = 0
    loop_dir = os.path.join(tmp_dir, "loop54360_cwd")
    os.makedirs(loop_dir, exist_ok=True)
    make_config_file(loop_dir, enabled=True)

    # The transcript at the moment the hook is first (re-)entered: one genuine
    # human turn, then an abdicating assistant message.
    transcript_lines = [
        # Genuine human turn (real text content) - CC native shape.
        {"type": "user", "message": {"content": [{"type": "text", "text": "Do the work"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": ABDICATING_MSG}]}},
    ]

    # We simulate up to CAP+2 re-entries. stop_hook_active stays FALSE the whole
    # time (the bug). Between each re-entry, the model "proceeded" and ran a
    # tool, so a tool_result line (type:"user") is appended - exactly the
    # inflation vector that broke the old counter.
    blocked_each_round = []
    max_rounds = CONSECUTIVE_BLOCK_CAP + 2
    for round_idx in range(max_rounds):
        transcript_path = make_transcript(loop_dir, transcript_lines)
        payload = json.dumps({
            "hook_event_name": "Stop",
            "session_id": "loop-54360",
            "cwd": loop_dir,
            "stop_hook_active": False,  # the bug: never propagates
            "permission_mode": "default",
            "transcript_path": transcript_path,
            "last_assistant_message": ABDICATING_MSG,
        })
        rc, stdout, _ = run_hook(payload)
        blocked = is_block(rc, stdout)
        blocked_each_round.append(blocked)

        # Simulate the model proceeding and running a tool: append a tool_result
        # line recorded as type:"user" (the inflation vector), plus the next
        # abdicating assistant message it re-stops on.
        transcript_lines.append({
            "type": "user",
            "message": {"content": [
                {"type": "tool_result", "tool_use_id": f"t{round_idx}", "content": "ok"}
            ]},
        })
        transcript_lines.append({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": ABDICATING_MSG}]},
        })

    # Assertion: the loop must TERMINATE. After CONSECUTIVE_BLOCK_CAP blocks the
    # hook must stop blocking (allow the stop), proving no infinite loop.
    num_blocks = sum(blocked_each_round)
    terminated = (not blocked_each_round[-1]) and num_blocks <= CONSECUTIVE_BLOCK_CAP
    print(
        f"    [{'PASS' if terminated else 'FAIL'}] #54360: stop_hook_active never flips + "
        f"tool_result inflation -> loop terminates at cap "
        f"(blocks={num_blocks}, pattern={blocked_each_round})"
    )
    if not terminated:
        failed += 1
        print(f"         blocked_each_round={blocked_each_round}")
        print(f"         num_blocks={num_blocks} (cap={CONSECUTIVE_BLOCK_CAP})")

    return failed


def test_counter_reset_on_new_user_turn(tmp_dir: str) -> int:
    """Test that a new user message resets the counter."""
    print("\n  [Counter reset tests]")
    failed = 0
    reset_dir = os.path.join(tmp_dir, "reset_cwd")
    os.makedirs(reset_dir, exist_ok=True)
    make_config_file(reset_dir, enabled=True)
    agentic_dir = os.path.join(reset_dir, ".agentic")

    # Seed counter at CAP with last_user_msg_count=1.
    counter_path = os.path.join(agentic_dir, ".abdication-guard-fire-count")
    with open(counter_path, "w") as f:
        json.dump({"count": 2, "last_user_msg_count": 1}, f)

    # Build a transcript with 2 user messages (simulating a new user turn).
    transcript = make_transcript(reset_dir, [
        {"role": "user", "content": [{"type": "text", "text": "Hello"}]},
        {"role": "assistant", "content": [{"type": "text", "text": CLEAN_MSG}]},
        {"role": "user", "content": [{"type": "text", "text": "Now proceed"}]},
        {"role": "assistant", "content": [{"type": "text", "text": ABDICATING_MSG}]},
    ])

    # Call with transcript; user_msg_count=2 > last_user_msg_count=1 -> reset.
    # After reset, count=0 < CAP=2 -> should block.
    payload = make_payload(
        reset_dir,
        last_assistant_message=ABDICATING_MSG,
        transcript_path=transcript,
    )
    rc, stdout, _ = run_hook(payload)
    ok = is_block(rc, stdout)
    print(f"    [{'PASS' if ok else 'FAIL'}] Counter reset on new user turn (2>1) -> BLOCK again")
    if not ok:
        failed += 1
        print(f"         rc={rc} stdout={stdout!r}")

    return failed


def test_unwritable_counter_allows_stop(tmp_dir: str) -> int:
    """REGRESSION: unwritable .agentic/ + stop_hook_active never set -> no infinite block.

    Simulates the conjunction identified in the Skeptic Minor finding:
      - .agentic/ directory is read-only, so _write_counter always fails.
      - stop_hook_active never flips to True (CC bug #54360).

    Pre-fix behavior: _write_counter fails silently, the count never increments,
    the loop bound is lost, and the hook blocks on every invocation indefinitely.

    Post-fix behavior: the hook only emits a block AFTER the incremented count
    has been successfully persisted. On write failure it exits 0 (allow-stop)
    so the session is never stuck in an infinite block loop.
    """
    print("\n  [Unwritable counter + #54360 conjunction regression]")
    failed = 0
    unwrite_dir = os.path.join(tmp_dir, "unwritable_cwd")
    os.makedirs(unwrite_dir, exist_ok=True)
    agentic_dir = os.path.join(unwrite_dir, ".agentic")
    os.makedirs(agentic_dir, exist_ok=True)

    # Write config while the directory is still writable.
    config_path = os.path.join(agentic_dir, "config.json")
    with open(config_path, "w") as f:
        json.dump({"abdication_guard_enabled": True}, f)

    # Make .agentic/ read-only so counter writes fail (file creation denied).
    os.chmod(agentic_dir, 0o555)
    try:
        # Simulate CAP+2 re-entries with stop_hook_active=False (bug never fixed).
        # Each call finds count=0 (read fails, defaults to 0), tries to write new
        # count, fails, and - under the fix - must ALLOW rather than block.
        blocked_rounds = []
        for i in range(CONSECUTIVE_BLOCK_CAP + 2):
            payload = json.dumps({
                "hook_event_name": "Stop",
                "session_id": "unwritable-regression",
                "cwd": unwrite_dir,
                "stop_hook_active": False,   # bug: never propagates
                "permission_mode": "default",
                "last_assistant_message": ABDICATING_MSG,
            })
            rc, stdout, _ = run_hook(payload)
            blocked_rounds.append(is_block(rc, stdout))

        # Every invocation must ALLOW (no block without a persisted loop bound).
        all_allowed = not any(blocked_rounds)
        print(
            f"    [{'PASS' if all_allowed else 'FAIL'}] "
            f"Unwritable .agentic/ + stop_hook_active=False on {CONSECUTIVE_BLOCK_CAP + 2} "
            f"invocations -> all ALLOW (no infinite block loop)"
        )
        if not all_allowed:
            failed += 1
            print(f"         blocked_rounds={blocked_rounds} (expected all False)")
    finally:
        # Restore write permission so temp dir cleanup succeeds.
        os.chmod(agentic_dir, 0o755)

    return failed


def test_corrupt_counter_file(tmp_dir: str) -> int:
    """Test that a corrupt counter file is treated as 0."""
    print("\n  [Corrupt counter file tests]")
    failed = 0
    corrupt_dir = os.path.join(tmp_dir, "corrupt_cwd")
    os.makedirs(corrupt_dir, exist_ok=True)
    make_config_file(corrupt_dir, enabled=True)
    agentic_dir = os.path.join(corrupt_dir, ".agentic")
    counter_path = os.path.join(agentic_dir, ".abdication-guard-fire-count")
    with open(counter_path, "w") as f:
        f.write("NOT JSON {{{{")

    payload = make_payload(corrupt_dir, last_assistant_message=ABDICATING_MSG)
    rc, stdout, _ = run_hook(payload)
    ok = is_block(rc, stdout)
    print(f"    [{'PASS' if ok else 'FAIL'}] Corrupt counter file treated as 0 -> BLOCK")
    if not ok:
        failed += 1
        print(f"         rc={rc} stdout={stdout!r}")
    return failed


def test_write_counter_pid_suffixed_tmp(tmp_dir: str) -> int:
    """DS-109 regression: _write_counter's staging file must be pid-suffixed.

    Pre-fix, _write_counter always wrote to the SAME fixed `<counter>.tmp`
    name regardless of which process called it. Confirmed by execution
    against the pre-fix hook: pre-planting a peer's in-flight content at that
    exact path and then running the hook silently truncates and consumes it
    (open(tmp, "w") overwrites it, then os.replace renames it away) - the
    peer's staging data is destroyed with no error, no trace. Post-fix, the
    tmp name is `<counter>.tmp.<our-own-pid>`, so this process can never
    write through, or rename away, a name any other process owns.

    This test asserts the observable contract from the outside: after a
    normal successful hook invocation that writes the counter, a peer's
    pre-planted in-flight tmp files - both the legacy fixed `.tmp` name and a
    different pid's `.tmp.<otherpid>` name - survive the run untouched,
    byte-for-byte.
    """
    print("\n  [DS-109: counter tmp naming + peer-tmp survival]")
    failed = 0
    pid_dir = os.path.join(tmp_dir, "pid_tmp_cwd")
    os.makedirs(pid_dir, exist_ok=True)
    make_config_file(pid_dir, enabled=True)
    agentic_dir = os.path.join(pid_dir, ".agentic")
    os.makedirs(agentic_dir, exist_ok=True)
    counter_path = os.path.join(agentic_dir, ".abdication-guard-fire-count")

    # Pre-plant two "peer" staging files: the legacy fixed name (what every
    # writer shared pre-fix) and a pid-suffixed name for a pid that is
    # provably not this test process's own.
    legacy_fixed_peer_tmp = counter_path + ".tmp"
    foreign_pid = f"{os.getpid()}9"
    peer_tmp = counter_path + f".tmp.{foreign_pid}"
    with open(legacy_fixed_peer_tmp, "w") as f:
        f.write("PEER_INFLIGHT_DATA_LEGACY_NAME")
    with open(peer_tmp, "w") as f:
        f.write("PEER_INFLIGHT_DATA_PID_SUFFIXED")

    payload = make_payload(pid_dir, last_assistant_message=ABDICATING_MSG)
    rc, stdout, _ = run_hook(payload)
    ok_block = is_block(rc, stdout)
    print(f"    [{'PASS' if ok_block else 'FAIL'}] hook still blocks/writes the counter normally")
    if not ok_block:
        failed += 1

    with open(legacy_fixed_peer_tmp) as f:
        legacy_survived = f.read() == "PEER_INFLIGHT_DATA_LEGACY_NAME"
    print(f"    [{'PASS' if legacy_survived else 'FAIL'}] peer's legacy fixed-name .tmp survives untouched")
    if not legacy_survived:
        failed += 1

    with open(peer_tmp) as f:
        pid_survived = f.read() == "PEER_INFLIGHT_DATA_PID_SUFFIXED"
    print(f"    [{'PASS' if pid_survived else 'FAIL'}] peer's pid-suffixed .tmp.<otherpid> survives untouched")
    if not pid_survived:
        failed += 1

    # Our own real write should have landed cleanly with no leftover tmp of
    # ANY shape (own-pid-suffixed or otherwise) once the subprocess exits.
    leftover = [
        f for f in os.listdir(agentic_dir)
        if f.startswith(".abdication-guard-fire-count.tmp")
        and f not in (os.path.basename(legacy_fixed_peer_tmp), os.path.basename(peer_tmp))
    ]
    ok_no_leftover = leftover == []
    print(f"    [{'PASS' if ok_no_leftover else 'FAIL'}] no orphaned own-tmp remains (found: {leftover or 'none'})")
    if not ok_no_leftover:
        failed += 1

    return failed


def test_transcript_fallback(tmp_dir: str) -> int:
    """Test transcript_path fallback when last_assistant_message is absent."""
    print("\n  [Transcript fallback tests]")
    failed = 0
    transcript_dir = os.path.join(tmp_dir, "transcript_cwd")
    os.makedirs(transcript_dir, exist_ok=True)
    make_config_file(transcript_dir, enabled=True)

    # Transcript with an abdicating assistant message.
    transcript = make_transcript(transcript_dir, [
        {"role": "user", "content": [{"type": "text", "text": "Do the thing"}]},
        {"role": "assistant", "content": [
            {"type": "text", "text": "I've analyzed it."},
            {"type": "text", "text": " Would you like me to proceed?"},
        ]},
    ])
    # No last_assistant_message field - only transcript_path.
    payload = json.dumps({
        "hook_event_name": "Stop",
        "session_id": "test-transcript-001",
        "cwd": transcript_dir,
        "stop_hook_active": False,
        "permission_mode": "default",
        "transcript_path": transcript,
    })
    rc, stdout, _ = run_hook(payload)
    ok = is_block(rc, stdout)
    print(f"    [{'PASS' if ok else 'FAIL'}] Transcript fallback (abdicating) -> BLOCK")
    if not ok:
        failed += 1
        print(f"         rc={rc} stdout={stdout!r}")

    # Transcript with a clean assistant message.
    transcript2 = make_transcript(transcript_dir, [
        {"role": "user", "content": [{"type": "text", "text": "Do the thing"}]},
        {"role": "assistant", "content": [
            {"type": "text", "text": CLEAN_MSG},
        ]},
    ])
    payload2 = json.dumps({
        "hook_event_name": "Stop",
        "session_id": "test-transcript-002",
        "cwd": transcript_dir,
        "stop_hook_active": False,
        "permission_mode": "default",
        "transcript_path": transcript2,
    })
    rc2, stdout2, _ = run_hook(payload2)
    ok2 = is_allow(rc2, stdout2)
    print(f"    [{'PASS' if ok2 else 'FAIL'}] Transcript fallback (clean) -> ALLOW")
    if not ok2:
        failed += 1
        print(f"         rc={rc2} stdout={stdout2!r}")

    return failed


# ---------------------------------------------------------------------------
# Smoke tests: end-to-end subprocess verification of output shape
# ---------------------------------------------------------------------------

def test_smoke(tmp_dir: str) -> int:
    """End-to-end smoke checks: verify exact output shape from the hook process."""
    print("\n  [Smoke tests]")
    failed = 0

    smoke_dir = os.path.join(tmp_dir, "smoke_cwd")
    os.makedirs(smoke_dir, exist_ok=True)
    make_config_file(smoke_dir, enabled=True)

    # Smoke 1: abdicating payload -> exactly one valid JSON block object.
    payload_block = make_payload(smoke_dir, last_assistant_message=ABDICATING_MSG)
    rc, stdout, stderr = run_hook(payload_block)
    try:
        obj = json.loads(stdout.strip())
        shape_ok = (
            rc == 0
            and obj.get("decision") == "block"
            and isinstance(obj.get("reason"), str)
            and len(obj["reason"]) > 10
            # Ensure it is NOT nested under hookSpecificOutput (wrong shape for Stop hooks).
            and "hookSpecificOutput" not in obj
        )
    except Exception:
        shape_ok = False
    print(f"    [{'PASS' if shape_ok else 'FAIL'}] Smoke: abdicating -> valid flat block JSON (decision+reason at top level)")
    if not shape_ok:
        failed += 1
        print(f"         rc={rc} stdout={stdout!r} stderr={stderr!r}")

    # Smoke 2: clean payload -> empty stdout.
    smoke_dir2 = os.path.join(tmp_dir, "smoke_cwd2")
    os.makedirs(smoke_dir2, exist_ok=True)
    make_config_file(smoke_dir2, enabled=True)
    payload_allow = make_payload(smoke_dir2, last_assistant_message=CLEAN_MSG)
    rc2, stdout2, stderr2 = run_hook(payload_allow)
    empty_ok = rc2 == 0 and stdout2.strip() == ""
    print(f"    [{'PASS' if empty_ok else 'FAIL'}] Smoke: clean msg -> empty stdout (no JSON emitted)")
    if not empty_ok:
        failed += 1
        print(f"         rc={rc2} stdout={stdout2!r} stderr={stderr2!r}")

    # Smoke 3: kill-switch -> empty stdout even on abdicating message.
    smoke_dir3 = os.path.join(tmp_dir, "smoke_cwd3")
    os.makedirs(smoke_dir3, exist_ok=True)
    make_config_file(smoke_dir3, enabled=True)
    payload_kill = make_payload(smoke_dir3, last_assistant_message=ABDICATING_MSG)
    rc3, stdout3, _ = run_hook(payload_kill, env={"AE_ABDICATION_GUARD_DISABLE": "1"})
    kill_ok = rc3 == 0 and stdout3.strip() == ""
    print(f"    [{'PASS' if kill_ok else 'FAIL'}] Smoke: kill-switch -> empty stdout (enforcement disabled)")
    if not kill_ok:
        failed += 1
        print(f"         rc={rc3} stdout={stdout3!r}")

    return failed


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def main() -> None:
    total_failed = 0

    with tempfile.TemporaryDirectory() as tmp_dir:
        # Core parametric cases.
        cases = build_cases(tmp_dir)
        print(f"\nRunning {len(cases)} parametric cases...")
        total_failed += run_cases(cases)

        # Prose-ballot cases.
        ballot_cases = build_prose_ballot_cases(tmp_dir)
        print(f"\nRunning {len(ballot_cases)} prose-ballot cases...")
        total_failed += run_cases(ballot_cases)

        # Counter tests.
        total_failed += test_counter_cap(tmp_dir)
        total_failed += test_54360_loop_terminates(tmp_dir)
        total_failed += test_counter_reset_on_new_user_turn(tmp_dir)
        total_failed += test_corrupt_counter_file(tmp_dir)
        total_failed += test_unwritable_counter_allows_stop(tmp_dir)
        total_failed += test_write_counter_pid_suffixed_tmp(tmp_dir)

        # Transcript fallback.
        total_failed += test_transcript_fallback(tmp_dir)

        # Smoke tests.
        total_failed += test_smoke(tmp_dir)

    print()
    total_cases = (
        len(cases)
        + len(ballot_cases)
        + 3   # counter cap: 3 assertions
        + 1   # #54360 loop-termination regression
        + 1   # counter reset
        + 1   # corrupt counter
        + 1   # unwritable counter + #54360 conjunction regression
        + 2   # transcript fallback
        + 3   # smoke checks
    )
    if total_failed == 0:
        print(f"All tests passed.")
        sys.exit(0)
    else:
        print(f"{total_failed} test assertion(s) FAILED.")
        sys.exit(1)


if __name__ == "__main__":
    main()
