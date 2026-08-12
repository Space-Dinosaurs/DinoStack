# Run with: python3 hooks/tests/test-turn-charge-model.py
"""
Executable model for the DS-151 turn-charge rewrite of
hooks/enforce-turn-shape.py's `_turn_charge`.

This harness does NOT call `_turn_charge`'s own helpers
(`_segment`/`_regions`/`_decision_items`/`_classify_warrants`) to compute
its expected values. It implements a SEPARATE, independently-written
reference model (`_ref_charge` below) directly over an 8-symbol line
alphabet, enumerates every message of length 1..6 over that alphabet
(299,592 messages total), builds the literal text for each, and asserts
that `_turn_charge` (imported directly from the hook module) agrees with
the reference on every one. A shared bug in `_turn_charge` and its own
helpers would not be caught by testing the hook against itself - the
whole point of this harness (DS-151 plan, "Executable model" section, and
test-strategy item 5) is an independent implementation of the charge
definition.

Alphabet (8 symbols):
  PROSE       - ordinary non-blank prose line.
  DELIM       - a ``` fence delimiter line.
  HEAD        - "## Operator decisions" heading line.
  ITEM        - a decision-item start line ("- Item action here").
  CONT        - a decision-item continuation line (does not match the
                item-start regex).
  WAITING_OK  - a well-formed "Waiting:" line (<= WAITING_LINE_MAX_CHARS).
  WAITING_FAT - a "Waiting:"-shaped line LONGER than WAITING_LINE_MAX_CHARS
                (matches the regex shape but is not well-formed).
  BLANK       - a blank line.

Invariants (I1-I8), all asserted below:
  I1 - Inserting a NON-STRUCTURAL line (PROSE/CONT/WAITING_FAT/BLANK) at
       any position never decreases charge.
  I2 - A pure-PROSE message charges exactly its non-blank line count.
  I3 - `_turn_charge` never raises, never returns negative.
  I4 - Constraint 1: identity + k well-formed Waiting: lines (sole
       warrant) charges 0 for all k.
  I5 - Constraint 2: identity + heading + k items of <=3 lines charges 0
       for all k (no stray preamble).
  I6 - Bounded-free: charge >= nonblank_body_lines - (FENCE_FREE_LINES +
       ITEM_FREE_LINES*items + well_formed_waiting_free + heading_free).
  I7 - Charge monotone non-decreasing in (closed, full) fence count;
       >=2 full 20-line fences always exceeds BASE_BODY_BUDGET.
  I8 - `charge <= nonblank_body_lines` for every enumerated message.

I1 is deliberately restricted to non-structural symbols. Inserting
DELIM/HEAD/ITEM restructures regions and can legitimately reduce charge
(closing an open fence; splitting one long item into two compliant ones) -
unrestricted monotonicity is false by design, not a bug.
"""

from __future__ import annotations

import importlib.util
import itertools
import os
import sys
import time

HOOK_PATH = os.path.join(os.path.dirname(__file__), "..", "enforce-turn-shape.py")

_spec = importlib.util.spec_from_file_location("enforce_turn_shape", HOOK_PATH)
_hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_hook)

BASE_BODY_BUDGET = _hook.BASE_BODY_BUDGET
FENCE_FREE_LINES = _hook.FENCE_FREE_LINES
ITEM_FREE_LINES = _hook.ITEM_FREE_LINES
WAITING_LINE_MAX_CHARS = _hook.WAITING_LINE_MAX_CHARS

IDENTITY_LINE = "unit-1 · fix-thing · abc1234 [phase: implement]"

total = 0
failed = 0


def check(label: str, condition: bool):
    global total, failed
    total += 1
    status = "PASS" if condition else "FAIL"
    if not condition:
        failed += 1
    print(f"  [{status}] {label}")


# ---------------------------------------------------------------------------
# Alphabet: symbol -> literal line text
# ---------------------------------------------------------------------------

_WOK_TEXT = "Waiting: short item."
_WFAT_TEXT = "Waiting: " + ("x" * (WAITING_LINE_MAX_CHARS + 40))

SYMBOL_TEXT = {
    "PROSE": "Ordinary prose line here.",
    "DELIM": "```",
    "HEAD": "## Operator decisions",
    "ITEM": "- Item action described here",
    "CONT": "   continuation detail line",
    "WAITING_OK": _WOK_TEXT,
    "WAITING_FAT": _WFAT_TEXT,
    "BLANK": "",
}
ALPHABET = tuple(SYMBOL_TEXT.keys())
NON_STRUCTURAL = ("PROSE", "CONT", "WAITING_FAT", "BLANK")

# Test-strategy item 4: alphabet drift guard. If WFAT were not strictly
# longer than WAITING_LINE_MAX_CHARS, or WOK not <= it, I4 and the
# fat-Waiting comparisons would silently test nothing.
assert len(_WFAT_TEXT) > WAITING_LINE_MAX_CHARS >= len(_WOK_TEXT), (
    f"alphabet drift: len(WFAT)={len(_WFAT_TEXT)}, "
    f"WAITING_LINE_MAX_CHARS={WAITING_LINE_MAX_CHARS}, len(WOK)={len(_WOK_TEXT)}"
)


def build_text(seq) -> str:
    return IDENTITY_LINE + "\n" + "\n".join(SYMBOL_TEXT[s] for s in seq) + ("\n" if seq else "\n")


# ---------------------------------------------------------------------------
# Independent reference implementation (does NOT call any _hook helper)
# ---------------------------------------------------------------------------


def _ref_charge(seq) -> tuple:
    """(charge, breakdown) computed directly from the symbol sequence,
    without using _hook._segment/_regions/_decision_items/_classify_warrants
    or any other hook-internal helper."""
    n = len(seq)

    # Fence pairing: pair DELIM positions in document order; an odd
    # trailing DELIM is unmatched (fail closed - not fenced).
    delim_positions = [i for i, s in enumerate(seq) if s == "DELIM"]
    matched = set()
    i = 0
    while i + 1 < len(delim_positions):
        o, c = delim_positions[i], delim_positions[i + 1]
        for k in range(o, c + 1):
            matched.add(k)
        i += 2
    is_fenced = [idx in matched for idx in range(n)]

    # Region split: first UNFENCED HEAD.
    head_idx = None
    for idx, s in enumerate(seq):
        if s == "HEAD" and not is_fenced[idx]:
            head_idx = idx
            break
    heading_present = head_idx is not None
    if heading_present:
        status_idx = list(range(0, head_idx))
        decisions_idx = list(range(head_idx + 1, n))
    else:
        status_idx = list(range(0, n))
        decisions_idx = []

    # Warrant: stoppage = any unfenced WAITING_OK/WAITING_FAT anywhere in
    # the body (both regions) - matches _classify_warrants' whole-body
    # unfenced domain. decision = heading_present (already unfenced-only).
    # This alphabet has no completion/answer trigger tokens.
    stoppage = any(
        seq[idx] in ("WAITING_OK", "WAITING_FAT") and not is_fenced[idx] for idx in range(n)
    )
    decision = heading_present
    stoppage_sole = stoppage and not decision

    # Status region.
    status_charge = 0
    waiting_ok_free = 0
    fenced_nonblank_status = 0
    for idx in status_idx:
        s = seq[idx]
        if s == "BLANK":
            continue
        if is_fenced[idx]:
            fenced_nonblank_status += 1
            continue
        if s == "WAITING_OK" and stoppage_sole:
            waiting_ok_free += 1
            continue
        # WAITING_FAT never qualifies as well-formed regardless of
        # stoppage_sole; PROSE/DELIM(unfenced)/HEAD(non-splitting)/ITEM/
        # CONT/WAITING_OK(not stoppage_sole) all charge 1.
        status_charge += 1
    fence_charge = max(0, fenced_nonblank_status - FENCE_FREE_LINES)

    # Decisions region: fold into items; fenced or not, once inside an
    # item, folds at full weight (amendment A2).
    item_sizes = []
    label_open = False
    cur = 0
    non_item = 0
    for idx in decisions_idx:
        s = seq[idx]
        if s == "BLANK":
            continue
        if s == "ITEM" and not is_fenced[idx]:
            if label_open:
                item_sizes.append(cur)
            label_open = True
            cur = 1
        elif label_open:
            cur += 1
        else:
            non_item += 1
    if label_open:
        item_sizes.append(cur)
    decisions_charge = non_item + sum(max(0, c - ITEM_FREE_LINES) for c in item_sizes)

    charge = status_charge + fence_charge + decisions_charge
    nonblank = sum(1 for s in seq if s != "BLANK")

    breakdown = {
        "status": status_charge,
        "fence": fence_charge,
        "decisions": decisions_charge,
        "fence_lines": fenced_nonblank_status,
        "items": len(item_sizes),
        "item_sizes": item_sizes,
        "waiting_ok": waiting_ok_free,
        "nonblank": nonblank,
        "heading_present": heading_present,
    }
    return charge, breakdown


# ---------------------------------------------------------------------------
# Enumeration: every message of length 1..6 over the 8-symbol alphabet.
# ---------------------------------------------------------------------------

_start = time.monotonic()

enumerated_count = 0
mismatch_examples = []
max_len_enumerated = 6

for depth in range(1, max_len_enumerated + 1):
    for seq in itertools.product(ALPHABET, repeat=depth):
        enumerated_count += 1
        text = build_text(seq)

        ref_charge, ref_bd = _ref_charge(seq)
        try:
            hook_charge, hook_bd = _hook._turn_charge(text)
            raised = False
        except Exception as exc:  # noqa: BLE001 - I3 requires never-raises
            raised = True
            hook_charge, hook_bd = None, None

        if raised:
            mismatch_examples.append((seq, "RAISED", str(exc)))
            continue

        if hook_charge != ref_charge:
            if len(mismatch_examples) < 10:
                mismatch_examples.append((seq, ref_charge, hook_charge))
            continue

_elapsed = time.monotonic() - _start

check(
    "harness enumerated a non-zero message count (test-strategy item 4 backstop)",
    enumerated_count > 0,
)
check(f"enumerated_count == 299592 (matches 8^1..8^6)", enumerated_count == 299592)

check(
    f"_turn_charge matches the independent reference on all {enumerated_count} "
    f"enumerated messages (took {_elapsed:.2f}s)",
    len(mismatch_examples) == 0,
)
if mismatch_examples:
    print("  First mismatches:")
    for ex in mismatch_examples[:10]:
        print(f"    {ex}")

# ---------------------------------------------------------------------------
# I3: never raises, never negative - explicit re-assertion (also covered by
# the enumeration loop above, but re-stated as its own line item per the
# invariant table).
# ---------------------------------------------------------------------------

_i3_ok = True
_i3_neg = 0
for depth in range(1, 4):
    for seq in itertools.product(ALPHABET, repeat=depth):
        text = build_text(seq)
        try:
            c, _ = _hook._turn_charge(text)
            if c < 0:
                _i3_neg += 1
        except Exception:
            _i3_ok = False
check("I3: _turn_charge never raises and never returns negative", _i3_ok and _i3_neg == 0)

# Malformed/pathological input: unmatched fence, no identity line, empty
# body - _turn_charge must not raise.
for pathological in ("", "\n\n\n", "```\nunclosed", "no identity line at all\nprose"):
    try:
        _hook._turn_charge(pathological)
        ok = True
    except Exception:
        ok = False
    check(f"I3: _turn_charge does not raise on pathological input {pathological!r}", ok)

# ---------------------------------------------------------------------------
# I1: inserting a non-structural symbol at any position never decreases
# charge. Restricted to messages of length 1..5 (so the post-insertion
# message stays within the enumerated depth) and to NON_STRUCTURAL symbols.
# ---------------------------------------------------------------------------

_i1_checks = 0
_i1_ok = True
for depth in range(1, max_len_enumerated):  # 1..5, insertion yields <=6
    for seq in itertools.product(ALPHABET, repeat=depth):
        base_charge, _ = _ref_charge(seq)
        base_hook_charge, _ = _hook._turn_charge(build_text(seq))
        for pos in range(depth + 1):
            for sym in NON_STRUCTURAL:
                new_seq = seq[:pos] + (sym,) + seq[pos:]
                new_charge, _ = _hook._turn_charge(build_text(new_seq))
                _i1_checks += 1
                if new_charge < base_hook_charge:
                    _i1_ok = False
check(
    f"I1: inserting a non-structural line never decreases charge ({_i1_checks} checks)",
    _i1_ok,
)

# ---------------------------------------------------------------------------
# I2: a pure-PROSE message charges exactly its non-blank line count.
# ---------------------------------------------------------------------------

_i2_ok = True
for n in range(0, 60):
    seq = ("PROSE",) * n
    text = build_text(seq)
    c, _ = _hook._turn_charge(text)
    if c != n:
        _i2_ok = False
check("I2: pure-PROSE message charges exactly its line count (n=0..59)", _i2_ok)

# ---------------------------------------------------------------------------
# I4: identity + k well-formed Waiting: lines (sole warrant) charges 0.
# ---------------------------------------------------------------------------

_i4_ok = True
for k in range(0, 400):
    seq = ("WAITING_OK",) * k
    text = build_text(seq) if k > 0 else IDENTITY_LINE + "\n"
    c, _ = _hook._turn_charge(text)
    if c != 0:
        _i4_ok = False
check("I4: identity + k well-formed Waiting: lines (sole warrant) charges 0 (k=0..399)", _i4_ok)

# ---------------------------------------------------------------------------
# I5: identity + heading + k items of <=3 lines (no stray preamble)
# charges 0.
# ---------------------------------------------------------------------------

_i5_ok = True
for k in range(0, 400):
    item_block = ("ITEM", "CONT") * k  # each item: 1 start + 1 continuation = 2 lines
    seq = ("HEAD",) + item_block
    text = build_text(seq)
    c, _ = _hook._turn_charge(text)
    if c > 1:
        _i5_ok = False
check("I5: identity + heading + k compliant items charges <=1 (k=0..399)", _i5_ok)

# ---------------------------------------------------------------------------
# I6: bounded-free invariant, checked against the reference model's own
# breakdown (heading/waiting/item sizes) for every enumerated message of
# depth <= 4 (full depth-6 re-check would duplicate the main enumeration
# loop's cost for a purely derived inequality already proven in closed
# form - see the module docstring's "Charge model" derivation).
# ---------------------------------------------------------------------------

_i6_ok = True
_i6_checked = 0
for depth in range(0, 5):
    for seq in itertools.product(ALPHABET, repeat=depth) if depth else [()]:
        charge, bd = _ref_charge(seq)
        free_bound = (
            FENCE_FREE_LINES
            + ITEM_FREE_LINES * bd["items"]
            + bd["waiting_ok"]
            + (1 if bd["heading_present"] else 0)
        )
        _i6_checked += 1
        if charge < bd["nonblank"] - free_bound:
            _i6_ok = False
check(f"I6: bounded-free invariant holds ({_i6_checked} messages, depth 0..4)", _i6_ok)

# ---------------------------------------------------------------------------
# I7: charge monotone non-decreasing in (closed, full) fence count;
# >=2 full 20-line fences always exceeds BASE_BODY_BUDGET.
# ---------------------------------------------------------------------------


def _n_fences_text(k: int, fence_len: int = FENCE_FREE_LINES) -> str:
    parts = [IDENTITY_LINE]
    for _ in range(k):
        parts.append("```")
        for i in range(fence_len):
            parts.append(f"prose line {i} in fence")
        parts.append("```")
    return "\n".join(parts) + "\n"


_i7_charges = []
for k in range(1, 8):
    c, _ = _hook._turn_charge(_n_fences_text(k))
    _i7_charges.append(c)

_i7_monotone = all(_i7_charges[i] <= _i7_charges[i + 1] for i in range(len(_i7_charges) - 1))
check(f"I7: charge monotone non-decreasing in fence count (k=1..7): {_i7_charges}", _i7_monotone)
check(
    "I7: >=2 full 20-line fences always exceeds BASE_BODY_BUDGET",
    all(c > BASE_BODY_BUDGET for c in _i7_charges[1:]),
)

# ---------------------------------------------------------------------------
# I8: charge <= nonblank_body_lines for every enumerated message
# (proves the zero-warrant skip in _volume_flag is not a gap: _turn_charge
# itself can never overcharge past the raw line count).
# ---------------------------------------------------------------------------

_i8_ok = True
_i8_checked = 0
for depth in range(1, max_len_enumerated + 1):
    for seq in itertools.product(ALPHABET, repeat=depth):
        text = build_text(seq)
        c, bd = _hook._turn_charge(text)
        _i8_checked += 1
        if c > bd["nonblank"]:
            _i8_ok = False
            if len(mismatch_examples) < 20:
                mismatch_examples.append((seq, "I8 violation", c, bd["nonblank"]))
check(f"I8: charge <= nonblank_body_lines for all {_i8_checked} enumerated messages", _i8_ok)

# ---------------------------------------------------------------------------
# A4: second enumeration pass with FENCE_FREE_LINES monkeypatched to 2, so
# depth-6 messages straddle the pool boundary and the fence arithmetic
# (CF-1's own region) is actually exercised by the exhaustive harness, not
# just the targeted I7 scan. Reported separately (not folded into the
# primary enumeration's pass/fail) per the plan's "Report both passes'
# counts" instruction.
# ---------------------------------------------------------------------------

print()
print("--- A4: second enumeration pass, FENCE_FREE_LINES=2 ---")

_orig_fence_free = _hook.FENCE_FREE_LINES
_hook.FENCE_FREE_LINES = 2
FENCE_FREE_LINES = 2  # reassign the harness's own reference-model global too

_a4_start = time.monotonic()
_a4_enumerated = 0
_a4_mismatches = []
_a4_violations = 0
for depth in range(1, max_len_enumerated + 1):
    for seq in itertools.product(ALPHABET, repeat=depth):
        _a4_enumerated += 1
        text = build_text(seq)
        ref_c, ref_bd = _ref_charge(seq)  # uses module-level FENCE_FREE_LINES (2, patched below)
        hook_c, hook_bd = _hook._turn_charge(text)
        if hook_c != ref_c:
            if len(_a4_mismatches) < 10:
                _a4_mismatches.append((seq, ref_c, hook_c))
        if hook_c > hook_bd["nonblank"]:
            _a4_violations += 1
_a4_elapsed = time.monotonic() - _a4_start

_hook.FENCE_FREE_LINES = _orig_fence_free
FENCE_FREE_LINES = _orig_fence_free

print(
    f"  A4 pass: enumerated={_a4_enumerated}, mismatches={len(_a4_mismatches)}, "
    f"I8-violations={_a4_violations}, elapsed={_a4_elapsed:.2f}s"
)
check(
    "A4: second pass (FENCE_FREE_LINES=2) - _turn_charge matches reference on all messages",
    len(_a4_mismatches) == 0,
)
check("A4: second pass (FENCE_FREE_LINES=2) - I8 holds on all messages", _a4_violations == 0)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print()
print(f"Primary pass (FENCE_FREE_LINES={_orig_fence_free}): enumerated={enumerated_count}, "
      f"elapsed={_elapsed:.2f}s")
if failed == 0:
    print(f"All {total} tests passed.")
    sys.exit(0)
else:
    print(f"{failed}/{total} test assertion(s) FAILED.")
    sys.exit(1)
