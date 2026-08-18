#!/usr/bin/env bash
# Purpose: Reusable harness for producing a candidate .claude/skills/
#          dinostack/SKILL.md at a target byte size, carrying detectable
#          canaries, so an operator can start a fresh session and confirm
#          whether the harness (Claude Code) injects it intact - the swept
#          measurement scripts/check-skill-embed-budget.sh's CEILING
#          constant claims to be anchored to, but never was (DS-45). Built
#          because the only prior injection observation (DS-146) was never
#          written down as anything reusable - this closes that gap without
#          itself running a sweep (see docs/technical/
#          skill-embed-injection-sweep.md for the runbook and which steps
#          need a human-started fresh session).
#
# Public API: bash scripts/skill-embed-sweep-harness.sh candidate \
#               --target-bytes N --out PATH [--base PATH] [--sweep-id ID]
#             bash scripts/skill-embed-sweep-harness.sh install \
#               --candidate PATH [--backup-dir DIR]
#             bash scripts/skill-embed-sweep-harness.sh restore \
#               --backup PATH
#             `candidate` never writes to the real, tracked SKILL.md -
#             `--out` is refused outright if it resolves to that path.
#             `install` and `restore` are the only two subcommands that
#             ever touch the real file, and `install` always writes a
#             timestamped backup first and prints the exact restore
#             command before doing so.
#
# Upstream deps: python3 (scripts/lib/skill_embed_sweep.py, the byte-exact
#                candidate builder); cmp (restore verification); the
#                already-built .claude/skills/dinostack/SKILL.md as the
#                default --base (this script does not rebuild it - run
#                `bash .claude/build.sh` first if you want a fresh base).
#
# Downstream consumers: docs/skill-embed-injection-sweep.md (the
#                        operator-facing runbook); bin/tests/
#                        test_skill_embed_sweep_harness.sh.
#
# Failure modes: `candidate` exits 1 if --out resolves to the real SKILL.md
#                path, if --base is missing, or if --target-bytes is
#                smaller than the minimum viable candidate size (see
#                skill_embed_sweep.py's ValueError message). `install`
#                exits 1 if --candidate is missing, or if the backup it
#                just wrote does not `cmp` byte-identical to the real file
#                it just copied FROM (aborts before overwriting on any
#                backup-fidelity mismatch - the whole point of backing up
#                first is trustworthy, so an unverified backup must never
#                be treated as good). `restore` exits 1 if --backup is
#                missing, or if the restored file does not `cmp`
#                byte-identical to the backup afterward. Idempotent:
#                re-running `candidate` with the same arguments overwrites
#                --out with an identical file (a fresh sweep_id each time
#                unless --sweep-id is pinned).
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

# _realpath <path>: portable-enough absolute-path resolution (macOS/BSD has
# no `realpath` guarantee and GNU readlink -f differs from BSD readlink);
# python3 is already a hard dependency of this script, so use it rather
# than adding a second platform-conditional shell branch.
_realpath() {
  python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "$1"
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

cmd_candidate() {
  _require_python3
  local target_bytes="" out="" base="${REAL_SKILL_FILE}" sweep_id=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --target-bytes) target_bytes="$2"; shift 2 ;;
      --out) out="$2"; shift 2 ;;
      --base) base="$2"; shift 2 ;;
      --sweep-id) sweep_id="$2"; shift 2 ;;
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

  # Hard refusal: --out must never resolve to the real, tracked SKILL.md.
  # candidate() must never overwrite it as a side effect of a dry run.
  local out_dir
  out_dir="$(dirname "${out}")"
  mkdir -p "${out_dir}"
  local out_real real_skill_real
  out_real="$(_realpath "${out}" 2>/dev/null || true)"
  # A not-yet-existing --out has no realpath to compare on some pythons'
  # os.path.realpath behavior across platforms it still resolves (does not
  # require the target to exist), but guard defensively anyway.
  if [ -z "${out_real}" ]; then
    out_real="$(_realpath "${out_dir}")/$(basename "${out}")"
  fi
  real_skill_real="$(_realpath "${REAL_SKILL_FILE}" 2>/dev/null || echo "${REAL_SKILL_FILE}")"
  if [ "${out_real}" = "${real_skill_real}" ]; then
    echo "skill-embed-sweep-harness.sh candidate: --out resolves to the" >&2
    echo "  real, tracked SKILL.md (${REAL_SKILL_FILE})." >&2
    echo "  candidate never writes there - use the separate 'install'" >&2
    echo "  subcommand if you deliberately want to install a padded build" >&2
    echo "  for a live injection test." >&2
    exit 1
  fi

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
      --candidate) candidate="$2"; shift 2 ;;
      --backup-dir) backup_dir="$2"; shift 2 ;;
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
      --backup) backup="$2"; shift 2 ;;
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

  echo "restored: ${backup} -> ${REAL_SKILL_FILE} (verified byte-identical via cmp)"
  echo ""
  echo "Independent second check (recommended): confirm the restored file"
  echo "also matches the last COMMITTED build, not just the backup:"
  echo "  bash scripts/build-all.sh && git status --short -- .claude/skills/dinostack/SKILL.md"
  echo "A clean 'git status --short' on that path means the restored file"
  echo "matches what a fresh build (and what main) would produce."
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
