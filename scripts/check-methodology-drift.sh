#!/usr/bin/env bash
# Purpose: Verify that the committed per-file methodology baseline manifest
#          matches the live content/sections/ files. Used as a CI gate to catch
#          unintended drift between section files and the documented baseline.
#          The baseline is regenerated in the same commit that intentionally
#          changes methodology content.
#
# Public API: bash scripts/check-methodology-drift.sh
#             bash scripts/check-methodology-drift.sh --regenerate
#             No args: read-only check; exits 0 on match, 1 on any drift.
#             --regenerate: writes scripts/.methodology-baseline.sha256
#             atomically and exits 0. Any other arg: usage on stderr, exit 2.
#
# Upstream deps: scripts/build-methodology.sh --list-files (single-source file
#                glob); scripts/.methodology-baseline.sha256; sha256sum or
#                shasum -a 256.
#
# Downstream consumers: .github/workflows/methodology-drift.yml,
#                       content/commands/ds-update-agentic-engineering.md,
#                       AGENTS.md.
#
# Failure modes: missing/malformed manifest, duplicate basename, empty section
#                set, path-set mismatch, or per-file hash mismatch -> exit 1
#                with diagnostics naming the offending basename. Read-only
#                (no args) has no side effects on the repo. Hard-fails if
#                neither sha256sum nor shasum exists.
#
# Performance: O(total size of section files); one hash per section file.

set -euo pipefail

# REPO_DIR bootstrap uses only bash builtins so the CI-hard-fail path (an
# otherwise empty PATH) can still resolve the repo root before the hasher check.
SRC="${BASH_SOURCE[0]}"
if [[ "$SRC" == */* ]]; then
  SCRIPT_DIR="$(cd "${SRC%/*}" && pwd)"
else
  SCRIPT_DIR="$(pwd)"
fi
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BASELINE_FILE="$REPO_DIR/scripts/.methodology-baseline.sha256"
SECTIONS_DIR="$REPO_DIR/content/sections"

# Canonical manifest header. Written verbatim by --regenerate; the only
# permitted comment line in the file. NO count, NO timestamp, and NO
# output-hash line - a '# <output-hash>' comment would reintroduce the legacy
# single-hash conflict class the per-file manifest replaces.
HEADER='# methodology baseline: one <basename> <sha256> line per content/sections/[0-9][0-9]-*.md'

cleanup() {
  rm -f "${temporary:-}"
}

# --- Mode dispatch ---
regenerate=0
case "${1:-}" in
  "")
    ;;
  --regenerate)
    regenerate=1
    ;;
  *)
    echo "usage: check-methodology-drift.sh [--regenerate]" >&2
    exit 2
    ;;
esac

# --- Hasher selection: prefer sha256sum (Linux/CI), fall back to shasum (macOS).
#     Hard-fail (never skip) if neither exists - a check that silently skips
#     hashing would go green having asserted nothing.
if command -v sha256sum >/dev/null 2>&1; then
  hash_file() { sha256sum "$1" | awk '{print $1}'; }
elif command -v shasum >/dev/null 2>&1; then
  hash_file() { shasum -a 256 "$1" | awk '{print $1}'; }
else
  echo "check-methodology-drift.sh: neither sha256sum nor shasum found on PATH; cannot compute file hashes${CI:+ (CI hard-fail)}" >&2
  exit 1
fi

# --- Live section set: single-source glob from build-methodology.sh --list-files.
#     Do NOT duplicate the find/sort expression here.
live_set="$(bash "$REPO_DIR/scripts/build-methodology.sh" --list-files)"
if [[ -z "$live_set" ]]; then
  echo "check-methodology-drift.sh: empty section set (build-methodology.sh --list-files returned nothing)" >&2
  echo "  Regenerate with: bash scripts/check-methodology-drift.sh --regenerate" >&2
  exit 1
fi

live_names=()
while IFS= read -r name; do
  live_names+=("$name")
done <<< "$live_set"

if [[ "$regenerate" -eq 1 ]]; then
  temporary="$(mktemp "$(dirname "$BASELINE_FILE")/.methodology-baseline.XXXXXX")"
  trap cleanup EXIT HUP INT TERM
  {
    printf '%s\n' "$HEADER"
    while IFS= read -r name; do
      printf '%s %s\n' "$name" "$(hash_file "$SECTIONS_DIR/$name")"
    done <<< "$live_set"
  } > "$temporary"
  mv "$temporary" "$BASELINE_FILE"
  trap - EXIT HUP INT TERM
  exit 0
fi

# --- Read-only check: parse + validate the manifest, then compare against the
#     live set. Report ALL problems, then exit 1 if any were found.

if [[ ! -f "$BASELINE_FILE" ]]; then
  echo "check-methodology-drift.sh: baseline manifest missing: $BASELINE_FILE" >&2
  echo "  Establish/refresh it with: bash scripts/check-methodology-drift.sh --regenerate" >&2
  exit 1
fi

manifest_names=()
manifest_hashes=()
parse_errors=0
line_no=0
while IFS= read -r line || [[ -n "$line" ]]; do
  line_no=$((line_no + 1))

  # Header line (must be line 1, exactly the canonical string).
  if [[ $line_no -eq 1 ]]; then
    if [[ "$line" != "$HEADER" ]]; then
      if [[ "$line" =~ ^[0-9a-f]{64}$ ]]; then
        echo "check-methodology-drift.sh: $BASELINE_FILE line 1: legacy single-hash format detected (expected a per-file manifest)" >&2
      else
        echo "check-methodology-drift.sh: $BASELINE_FILE line 1: malformed header" >&2
        echo "  expected exactly: $HEADER" >&2
      fi
      echo "  Regenerate with: bash scripts/check-methodology-drift.sh --regenerate" >&2
      parse_errors=$((parse_errors + 1))
    fi
    continue
  fi

  # Any comment line other than the canonical header is rejected - a stray
  # '# ...' line could hide a future '# <output-hash>' comment that would
  # reintroduce the legacy single-hash conflict class.
  if [[ "$line" =~ ^# ]]; then
    echo "check-methodology-drift.sh: $BASELINE_FILE line $line_no: unexpected comment line" >&2
    echo "  The only permitted comment is the canonical header on line 1." >&2
    echo "  Regenerate with: bash scripts/check-methodology-drift.sh --regenerate" >&2
    parse_errors=$((parse_errors + 1))
    continue
  fi

  read -ra fields <<< "$line"

  if [[ ${#fields[@]} -eq 1 ]]; then
    echo "check-methodology-drift.sh: $BASELINE_FILE line $line_no: legacy single-hash format detected (expected '<basename> <sha256>')" >&2
    echo "  Regenerate with: bash scripts/check-methodology-drift.sh --regenerate" >&2
    parse_errors=$((parse_errors + 1))
    continue
  fi

  if [[ ${#fields[@]} -ne 2 ]]; then
    echo "check-methodology-drift.sh: $BASELINE_FILE line $line_no: malformed data line (expected exactly '<basename> <sha256>', got ${#fields[@]} fields)" >&2
    echo "  Regenerate with: bash scripts/check-methodology-drift.sh --regenerate" >&2
    parse_errors=$((parse_errors + 1))
    continue
  fi

  name="${fields[0]}"
  hash="${fields[1]}"

  if [[ ! "$hash" =~ ^[0-9a-f]{64}$ ]]; then
    echo "check-methodology-drift.sh: $BASELINE_FILE line $line_no: malformed sha256 for '$name' (expected 64 hex chars, got '${hash}')" >&2
    echo "  Regenerate with: bash scripts/check-methodology-drift.sh --regenerate" >&2
    parse_errors=$((parse_errors + 1))
    continue
  fi

  for seen in "${manifest_names[@]}"; do
    if [[ "$seen" == "$name" ]]; then
      echo "check-methodology-drift.sh: $BASELINE_FILE line $line_no: duplicate basename '$name'" >&2
      echo "  Regenerate with: bash scripts/check-methodology-drift.sh --regenerate" >&2
      parse_errors=$((parse_errors + 1))
      continue 2
    fi
  done

  manifest_names+=("$name")
  manifest_hashes+=("$hash")
done < "$BASELINE_FILE"

if [[ $parse_errors -gt 0 ]]; then
  exit 1
fi

# --- Path-set comparison: manifest names vs live names. Report all extras and
#     all missing so a rename shows both sides.
_contains() {
  local needle="$1"; shift
  local item
  for item in "$@"; do
    [[ "$item" == "$needle" ]] && return 0
  done
  return 1
}

path_errors=0
for name in "${manifest_names[@]}"; do
  if ! _contains "$name" "${live_names[@]}"; then
    echo "check-methodology-drift.sh: baseline lists '$name' but build-methodology.sh --list-files does not (renamed, renumbered, or deleted?)" >&2
    path_errors=$((path_errors + 1))
  fi
done
for name in "${live_names[@]}"; do
  if ! _contains "$name" "${manifest_names[@]}"; then
    echo "check-methodology-drift.sh: build-methodology.sh --list-files emits '$name' but the baseline does not (added?)" >&2
    path_errors=$((path_errors + 1))
  fi
done

if [[ $path_errors -gt 0 ]]; then
  echo "  Regenerate with: bash scripts/check-methodology-drift.sh --regenerate" >&2
  exit 1
fi

# --- Per-file hash comparison. Report ALL mismatches, then exit 1.
hash_errors=0
for name in "${live_names[@]}"; do
  idx=-1
  for i in "${!manifest_names[@]}"; do
    if [[ "${manifest_names[$i]}" == "$name" ]]; then
      idx=$i
      break
    fi
  done
  [[ $idx -ge 0 ]] || continue  # path-set mismatch already reported above

  expected="${manifest_hashes[$idx]}"
  current="$(hash_file "$SECTIONS_DIR/$name")"
  if [[ "$current" != "$expected" ]]; then
    echo "check-methodology-drift.sh: hash mismatch for '$name'" >&2
    echo "  expected: $expected" >&2
    echo "  current:  $current" >&2
    hash_errors=$((hash_errors + 1))
  fi
done

if [[ $hash_errors -gt 0 ]]; then
  echo "  Regenerate with: bash scripts/check-methodology-drift.sh --regenerate" >&2
  exit 1
fi

echo "methodology drift check: OK (${#live_names[@]} files)"
exit 0
