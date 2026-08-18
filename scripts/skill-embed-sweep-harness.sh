#!/usr/bin/env bash
# Purpose: Reusable harness for producing a candidate .claude/skills/
#          dinostack/SKILL.md at a target byte size, carrying detectable
#          canaries, so an operator can start a fresh session and confirm
#          whether the harness (Claude Code) injects it intact - the swept
#          measurement scripts/check-skill-embed-budget.sh's CEILING
#          constant claims to be anchored to, but never was (DS-45). Built
#          because the only prior injection observation (DS-146) was never
#          written down as anything reusable - this closes that gap without
#          itself running a sweep (see docs/
#          skill-embed-injection-sweep.md for the runbook and which steps
#          need a human-started fresh session).
#
# Public API: bash scripts/skill-embed-sweep-harness.sh candidate \
#               --target-bytes N --out PATH [--base PATH] [--sweep-id ID]
#             bash scripts/skill-embed-sweep-harness.sh install \
#               --candidate PATH [--backup-dir DIR]
#             bash scripts/skill-embed-sweep-harness.sh restore \
#               --backup PATH
#             `candidate` never writes to the real, tracked SKILL.md, nor
#             to any OTHER checkout's real, tracked SKILL.md - `--out` is
#             refused outright if it resolves to the same on-disk file as
#             this checkout's real SKILL.md (case-insensitive-filesystem,
#             symlink, and hardlink aware - see scripts/lib/
#             skill_embed_sweep.py's paths_refer_to_same_file()), or if it
#             matches the .claude/skills/dinostack/SKILL.md artifact shape
#             under any checkout. `install` and `restore` are the only two
#             subcommands that ever touch the real file, and `install`
#             always writes a timestamped backup first and prints the
#             exact restore command before doing so. `install` also
#             refuses outright if the real file it is about to back up is
#             itself already a padded DS-45 candidate (carries the head
#             canary), and `restore` refuses to report success if the
#             file it just restored still carries that canary - both
#             close the same failure from opposite ends: a backup or a
#             restore point must never itself be padded content.
#
# Upstream deps: python3 (scripts/lib/skill_embed_sweep.py, the byte-exact
#                candidate builder and the write-guard comparison helper);
#                cmp (restore verification); the already-built
#                .claude/skills/dinostack/SKILL.md as the default --base
#                (this script does not rebuild it - run `bash
#                .claude/build.sh` first if you want a fresh base).
#
# Downstream consumers: docs/skill-embed-injection-sweep.md (the
#                        operator-facing runbook); bin/tests/
#                        test_skill_embed_sweep_harness.sh.
#
# Failure modes: `candidate` exits 1 if --out resolves to the real
#                SKILL.md path (this checkout's or any other checkout's),
#                if --base is missing, or if --target-bytes is smaller
#                than the minimum viable candidate size (see
#                skill_embed_sweep.py's ValueError message). `install`
#                exits 1 if --candidate is missing, if the real SKILL.md
#                it is about to back up already carries a DS-45 sweep
#                canary (a previously-installed padded build, never a
#                trustworthy backup source), or if the backup it just
#                wrote does not `cmp` byte-identical to the real file it
#                just copied FROM (aborts before overwriting on any
#                backup-fidelity mismatch - the whole point of backing up
#                first is trustworthy, so an unverified backup must never
#                be treated as good). `restore` exits 1 if --backup is
#                missing, if the restored file does not `cmp`
#                byte-identical to the backup afterward, or if the
#                restored file still carries a DS-45 sweep canary (the
#                backup itself was padded content, so cmp-identity to it
#                proves nothing about genuineness). Idempotent: re-running
#                `candidate` with the same arguments overwrites --out with
#                an identical file (a fresh sweep_id each time unless
#                --sweep-id is pinned).
#
# Compatible with both bash and zsh invocation of the containing shell;
# avoid the variable names `status` and `path` anywhere in this file -
# both are special/read-only in zsh. Every shell expansion followed by a
# literal ':' is braced.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PY_HELPER="${SCRIPT_DIR}/lib/skill_embed_sweep.py"
REAL_SKILL_FILE="${REPO_DIR}/.claude/skills/dinostack/SKILL.md"
DEFAULT_BACKUP_DIR="${REPO_DIR}/.agentic/skill-embed-sweep/backups"
# The literal marker string skill_embed_sweep.py stamps as the first line
# of every candidate's head canary - grepping for it on a real file (not
# a candidate) is how install/restore detect "this is padded content, not
# the genuine build" (DS-45 round-2 Major 2).
CANARY_MARKER="DS-45-SWEEP-HEAD"

_require_python3() {
  if ! command -v python3 >/dev/null 2>&1; then
    echo "skill-embed-sweep-harness.sh: python3 not found on PATH" >&2
    if [ -n "${CI:-}" ]; then
      echo "  hard-failing: this check must not silently skip under CI" >&2
    fi
    exit 1
  fi
}

_require_cmp() {
  if ! command -v cmp >/dev/null 2>&1; then
    echo "skill-embed-sweep-harness.sh: cmp not found on PATH" >&2
    if [ -n "${CI:-}" ]; then
      echo "  hard-failing: this check must not silently skip under CI" >&2
    fi
    exit 1
  fi
}

_usage() {
  cat >&2 <<'EOF'
Usage:
  skill-embed-sweep-harness.sh candidate --target-bytes N --out PATH \
      [--base PATH] [--sweep-id ID]
  skill-embed-sweep-harness.sh install --candidate PATH [--backup-dir DIR]
  skill-embed-sweep-harness.sh restore --backup PATH
EOF
}

# _flag_value <subcommand-label> <flag-name> <remaining-arg-count>: prints
# nothing; call right before reading "$2" for a flag that requires a
# value, passing "$#" (the caller's remaining-argument count at that
# point in its own `case` arm, BEFORE shifting). Exits 1 with the usage
# message if the flag was the last CLI argument (no value follows) -
# without this guard, `--out` as the final argument reads "$2" under
# `set -u` and dies on "unbound variable" instead of printing usage
# (DS-45 round-2 Minor 5).
_require_flag_value() {
  local label="$1" flag="$2" remaining="$3"
  if [ "${remaining}" -lt 2 ]; then
    echo "skill-embed-sweep-harness.sh ${label}: ${flag} requires a value" >&2
    _usage
    exit 1
  fi
}

cmd_candidate() {
  _require_python3
  local target_bytes="" out="" base="${REAL_SKILL_FILE}" sweep_id=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --target-bytes)
        _require_flag_value "candidate" "--target-bytes" "$#"
        target_bytes="$2"; shift 2 ;;
      --out)
        _require_flag_value "candidate" "--out" "$#"
        out="$2"; shift 2 ;;
      --base)
        _require_flag_value "candidate" "--base" "$#"
        base="$2"; shift 2 ;;
      --sweep-id)
        _require_flag_value "candidate" "--sweep-id" "$#"
        sweep_id="$2"; shift 2 ;;
      *) echo "skill-embed-sweep-harness.sh candidate: unknown arg $1" >&2; exit 1 ;;
    esac
  done
  if [ -z "${target_bytes}" ] || [ -z "${out}" ]; then
    echo "skill-embed-sweep-harness.sh candidate: --target-bytes and --out are required" >&2
    _usage
    exit 1
  fi
  if [ ! -f "${base}" ]; then
    echo "skill-embed-sweep-harness.sh candidate: base file not found: ${base}" >&2
    echo "  Run 'bash .claude/build.sh' first if you want a freshly built base." >&2
    exit 1
  fi

  # Hard refusal: --out must never resolve to the real, tracked SKILL.md
  # of THIS checkout, nor to the real, tracked SKILL.md of ANY OTHER
  # checkout (this machine routinely has many live git worktrees, each
  # with its own real SKILL.md at the same relative path). Delegates to
  # Python's os.path.realpath + os.stat rather than a shell string
  # comparison: a case-insensitive-but-preserving filesystem (macOS/APFS,
  # the primary development platform here) resolves two differently-cased
  # path strings to the same file on disk, which a plain string-equality
  # guard cannot detect (DS-45 round-2 Critical). Checked, and refused if
  # matched, BEFORE any directory is created for --out - a refused
  # invocation must not have side effects (DS-45 round-2 Minor 3).
  if ! python3 "${PY_HELPER}" check-out-refusal --out "${out}" --real "${REAL_SKILL_FILE}"; then
    echo "  candidate never writes to a real, tracked SKILL.md - use the" >&2
    echo "  separate 'install' subcommand if you deliberately want to" >&2
    echo "  install a padded build for a live injection test." >&2
    exit 1
  fi

  mkdir -p "$(dirname "${out}")"

  local py_args=(--base "${base}" --target-bytes "${target_bytes}" --out "${out}")
  if [ -n "${sweep_id}" ]; then
    py_args+=(--sweep-id "${sweep_id}")
  fi
  python3 "${PY_HELPER}" "${py_args[@]}"
  echo "candidate written: ${out}"
}

cmd_install() {
  _require_cmp
  local candidate="" backup_dir="${DEFAULT_BACKUP_DIR}"
  while [ $# -gt 0 ]; do
    case "$1" in
      --candidate)
        _require_flag_value "install" "--candidate" "$#"
        candidate="$2"; shift 2 ;;
      --backup-dir)
        _require_flag_value "install" "--backup-dir" "$#"
        backup_dir="$2"; shift 2 ;;
      *) echo "skill-embed-sweep-harness.sh install: unknown arg $1" >&2; exit 1 ;;
    esac
  done
  if [ -z "${candidate}" ]; then
    echo "skill-embed-sweep-harness.sh install: --candidate is required" >&2
    _usage
    exit 1
  fi
  if [ ! -f "${candidate}" ]; then
    echo "skill-embed-sweep-harness.sh install: candidate not found: ${candidate}" >&2
    exit 1
  fi
  if [ ! -f "${REAL_SKILL_FILE}" ]; then
    echo "skill-embed-sweep-harness.sh install: real SKILL.md not found:" >&2
    echo "  ${REAL_SKILL_FILE}" >&2
    echo "  refusing to install over a missing file - run 'bash .claude/build.sh' first." >&2
    exit 1
  fi

  # Refuse to back up (and then overwrite) an already-padded real file: a
  # backup of padded content is not a usable restore point, and running
  # `install` a second time (e.g. the runbook's "repeat with a different
  # --target-bytes" loop) without restoring in between would otherwise
  # silently capture padding as the backup and leave it there through a
  # later `restore` (DS-45 round-2 Major 2).
  if grep -q "${CANARY_MARKER}" "${REAL_SKILL_FILE}" 2>/dev/null; then
    echo "skill-embed-sweep-harness.sh install: the real SKILL.md at" >&2
    echo "  ${REAL_SKILL_FILE}" >&2
    echo "  already carries a DS-45 sweep canary - it is a previously" >&2
    echo "  installed padded candidate, not the genuine build. Restore it" >&2
    echo "  first (see the restore command printed by the prior install)," >&2
    echo "  then re-run install. Refusing before backing up: a backup of" >&2
    echo "  padded content is not a usable restore point." >&2
    exit 1
  fi

  mkdir -p "${backup_dir}"
  local ts
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  local backup_path="${backup_dir}/SKILL.md.${ts}.bak"

  cp "${REAL_SKILL_FILE}" "${backup_path}"
  if ! cmp -s "${REAL_SKILL_FILE}" "${backup_path}"; then
    echo "skill-embed-sweep-harness.sh install: backup write did not verify" >&2
    echo "  byte-identical to the real file - aborting before install." >&2
    echo "  Nothing was overwritten." >&2
    exit 1
  fi

  cp "${candidate}" "${REAL_SKILL_FILE}"

  echo "installed: ${candidate} -> ${REAL_SKILL_FILE}"
  echo "backup:    ${backup_path}"
  echo ""
  echo "To restore the real file:"
  echo "  bash scripts/skill-embed-sweep-harness.sh restore --backup ${backup_path}"
}

cmd_restore() {
  _require_cmp
  local backup=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --backup)
        _require_flag_value "restore" "--backup" "$#"
        backup="$2"; shift 2 ;;
      *) echo "skill-embed-sweep-harness.sh restore: unknown arg $1" >&2; exit 1 ;;
    esac
  done
  if [ -z "${backup}" ]; then
    echo "skill-embed-sweep-harness.sh restore: --backup is required" >&2
    _usage
    exit 1
  fi
  if [ ! -f "${backup}" ]; then
    echo "skill-embed-sweep-harness.sh restore: backup not found: ${backup}" >&2
    exit 1
  fi

  cp "${backup}" "${REAL_SKILL_FILE}"

  if ! cmp -s "${REAL_SKILL_FILE}" "${backup}"; then
    echo "skill-embed-sweep-harness.sh restore: restored file does NOT" >&2
    echo "  verify byte-identical to the backup. Do not trust the real" >&2
    echo "  file's current state - investigate before re-installing." >&2
    exit 1
  fi

  # Byte-identity to the backup only proves the copy succeeded - it says
  # nothing about whether the backup itself was genuine. If the restored
  # file still carries the sweep canary, the backup was padded content
  # (the same failure Major 2 closes from the install side), and
  # reporting success here would be the same false-positive read from the
  # other end (DS-45 round-2 Major 2).
  if grep -q "${CANARY_MARKER}" "${REAL_SKILL_FILE}" 2>/dev/null; then
    echo "skill-embed-sweep-harness.sh restore: the restored file still" >&2
    echo "  carries a DS-45 sweep canary - the backup itself was a padded" >&2
    echo "  candidate, not the genuine build. This backup is not a safe" >&2
    echo "  restore point; do not trust the real file's current state." >&2
    exit 1
  fi

  echo "restored: ${backup} -> ${REAL_SKILL_FILE} (verified byte-identical via cmp)"
  echo ""
  echo "Second, independently-sourced check (recommended): confirm the"
  echo "restored file already matches the last COMMITTED build - run this"
  echo "BEFORE regenerating anything, since a rebuild would overwrite"
  echo "evidence of a bad restore before you could observe it:"
  echo "  git status --short -- .claude/skills/dinostack/SKILL.md"
  echo "A clean status here means the restored file is already"
  echo "byte-identical to what is committed; there is no need to also run"
  echo "'bash scripts/build-all.sh' for this confirmation."
}

main() {
  if [ $# -lt 1 ]; then
    _usage
    exit 1
  fi
  local sub="$1"
  shift
  case "${sub}" in
    candidate) cmd_candidate "$@" ;;
    install) cmd_install "$@" ;;
    restore) cmd_restore "$@" ;;
    -h|--help) _usage; exit 0 ;;
    *) echo "skill-embed-sweep-harness.sh: unknown subcommand: ${sub}" >&2; _usage; exit 1 ;;
  esac
}

main "$@"
