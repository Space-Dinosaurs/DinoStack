#!/usr/bin/env python3
"""Purpose: Resolve and validate ds-lane's saved harness runtime and backend events.
Public API: Internal resolve, saved, events, and owns commands used by ds-lane.
Upstream deps: Python stdlib, ps; native Claude transcripts and Codex rollouts.
Downstream consumers: bin/ds-lane, bin/tests/test_ds_lane.sh.
Failure modes: Refuses unknown identity, policy, resources and process ownership.
Performance: Reads the selected transcript and current lane log; no model calls.
"""

import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


def refuse(message):
    raise ValueError(message)


def records(path, strict=False):
    with open(path, encoding="utf-8") as stream:
        for line in stream:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                if strict:
                    refuse("malformed runtime context: " + str(path))
                continue
            if isinstance(value, dict):
                yield value


def directory(value):
    path = Path(value).resolve(strict=True)
    if not path.is_dir():
        refuse("config/cwd is not a directory: " + str(path))
    return str(path)


def executable(value, harness):
    value = value or shutil.which(harness)
    if not value:
        refuse(harness + " CLI not found (set DS_LANE_" + harness.upper() + "_BIN, or put " + harness + " on PATH)")
    path = Path(value).resolve(strict=True)
    if not path.is_file() or not os.access(path, os.X_OK):
        refuse(harness + " CLI not executable at " + str(path))
    return str(path)


def selection():
    env = os.environ
    codex = bool(env.get("CODEX_THREAD_ID"))
    claude = bool(env.get("CLAUDE_CODE_SESSION_ID")) or env.get("CLAUDECODE") == "1"
    if codex and claude:
        refuse("conflicting native Codex and Claude identities")
    native = "codex" if codex else "claude" if claude else ""
    signals = [v for v in (native, env.get("AE_ADAPTER"), env.get("DS_LANE_HARNESS")) if v]
    if not signals:
        refuse("cannot determine invoking harness; explicitly bind DS_LANE_HARNESS=claude|codex")
    if any(v not in ("claude", "codex") for v in signals):
        refuse("unsupported invoking harness: " + ", ".join(signals))
    if len(set(signals)) != 1:
        refuse("conflicting invoking harness bindings: " + ", ".join(signals))
    return signals[0], bool(native)


def codex_policy(context, runtime_cwd=None):
    if not isinstance(context, dict) or set(context) != {"cwd", "approval_policy", "sandbox_policy"}:
        refuse("Codex context requires exactly cwd, approval_policy, sandbox_policy")
    approval = context["approval_policy"]
    if not isinstance(approval, str) or approval not in ("never", "on-request", "on-failure", "untrusted"):
        refuse("unsupported Codex approval_policy")
    cwd = context["cwd"]
    if not isinstance(cwd, str) or not os.path.isabs(cwd):
        refuse("Codex context cwd must be absolute")
    cwd = directory(cwd)
    runtime_cwd = directory(runtime_cwd or cwd)
    policy = context["sandbox_policy"]
    if not isinstance(policy, dict):
        refuse("unsupported Codex sandbox_policy")
    kind = policy.get("type")
    overrides = ['approval_policy="never"']
    if kind in ("danger-full-access", "read-only"):
        if set(policy) != {"type"}:
            refuse("unsupported Codex sandbox_policy fields")
    elif kind == "workspace-write":
        fields = {"type", "writable_roots", "network_access", "exclude_tmpdir_env_var", "exclude_slash_tmp"}
        if set(policy) != fields:
            refuse("unsupported/incomplete Codex workspace-write policy")
        roots = policy["writable_roots"]
        if not isinstance(roots, list) or any(not isinstance(r, str) or not os.path.isabs(r) for r in roots):
            refuse("Codex writable_roots must be absolute paths")
        roots = [directory(r) for r in roots]
        scope = [cwd, *roots]
        if not any(os.path.commonpath([runtime_cwd, root]) == root for root in scope):
            refuse("Codex runtime cwd differs from original context cwd and is outside original writable scope")
        # Codex also grants its cwd implicitly; preserve that original root on cwd changes.
        if runtime_cwd != cwd and cwd not in roots:
            roots.append(cwd)
        for key in ("network_access", "exclude_tmpdir_env_var", "exclude_slash_tmp"):
            if type(policy[key]) is not bool:
                refuse("Codex " + key + " must be boolean")
            overrides.append("sandbox_workspace_write." + key + "=" + json.dumps(policy[key]))
        overrides.append("sandbox_workspace_write.writable_roots=" + json.dumps(roots))
    else:
        refuse("unsupported Codex sandbox policy: " + str(kind))
    overrides.append("sandbox_mode=" + json.dumps(kind))
    return {"cwd": cwd, "approval_policy": approval, "sandbox_policy": policy, "overrides": overrides}


def claude_mode(config, native):
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    mode = ""
    if native:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", sid):
            refuse("cannot determine the conductor's permission mode: native Claude session id missing/invalid")
        paths = glob.glob(str(Path(config) / "projects" / "*" / (sid + ".jsonl")))
        if len(paths) != 1:
            refuse("cannot determine the conductor's permission mode: native transcript missing/ambiguous")
        events = list(records(paths[0]))
        modes = [e.get("permissionMode") for e in events if e.get("type") == "permission-mode"]
        if not modes:
            modes = [e.get("permissionMode") for e in events if e.get("type") == "user" and e.get("permissionMode")]
        mode = modes[-1] if modes else ""
        explicit = os.environ.get("DS_LANE_PERMISSION_MODE")
        if explicit and explicit != mode:
            refuse("DS_LANE_PERMISSION_MODE conflicts with native Claude permission mode")
    else:
        mode = os.environ.get("DS_LANE_PERMISSION_MODE", "")
    if mode not in ("default", "acceptEdits", "plan", "dontAsk", "bypassPermissions", "auto"):
        refuse(
            "cannot determine the conductor's permission mode; set DS_LANE_PERMISSION_MODE for an explicitly bound marker-less caller"
        )
    return mode


def resolve():
    harness, native = selection()
    env = os.environ
    if not hasattr(os, "setsid"):
        refuse("POSIX setsid unavailable; native Windows lane detachment is unsupported")
    config = directory(
        env.get("CODEX_HOME" if harness == "codex" else "CLAUDE_CONFIG_DIR")
        or str(Path.home() / (".codex" if harness == "codex" else ".claude"))
    )
    override = env.get("DS_LANE_" + harness.upper() + "_BIN")
    if harness == "claude" and not override:
        override = shutil.which("claude") or env.get("CLAUDE_CODE_EXECPATH")
    result = {
        "harness": harness,
        "executable": executable(override, harness),
        "config_dir": config,
        "runtime_cwd": directory(os.getcwd()),
    }
    if harness == "claude":
        result.update(permission_mode=claude_mode(config, native), bg_ceiling=env.get("DS_LANE_BG_CEILING_MS", "0"))
        if result["bg_ceiling"] != "default" and not re.fullmatch(r"[0-9]+", result["bg_ceiling"]):
            refuse("invalid DS_LANE_BG_CEILING_MS")
    else:
        if native:
            sid = env["CODEX_THREAD_ID"]
            if not re.fullmatch(r"[A-Za-z0-9_-]+", sid):
                refuse("invalid native Codex thread id")
            matches = []
            for base in ("sessions", "archived_sessions"):
                matches.extend(Path(config, base).rglob("*" + sid + ".jsonl"))
            if len(matches) != 1:
                refuse("native Codex rollout missing/ambiguous for exact thread " + sid)
            events = list(records(matches[0], strict=True))
            ids = [
                e.get("payload", {}).get("id")
                for e in events
                if e.get("type") == "session_meta" and isinstance(e.get("payload"), dict)
            ]
            if ids != [sid]:
                refuse("native Codex rollout session identity mismatch")
            contexts = [e.get("payload") for e in events if e.get("type") == "turn_context"]
            if not contexts or not isinstance(contexts[-1], dict):
                refuse("native Codex latest turn_context missing/malformed")
            context = {k: contexts[-1].get(k) for k in ("cwd", "approval_policy", "sandbox_policy")}
        else:
            path = env.get("DS_LANE_CODEX_CONTEXT_FILE", "")
            if not os.path.isabs(path):
                refuse("marker-less Codex requires absolute DS_LANE_CODEX_CONTEXT_FILE")
            with open(path, encoding="utf-8") as stream:
                context = json.load(stream)
        policy = codex_policy(context, result["runtime_cwd"])
        result["codex_context"] = json.dumps(policy, separators=(",", ":"))
    return result


def metadata(path):
    result = {}
    with open(path, encoding="utf-8") as stream:
        for line in stream:
            key, sep, value = line.rstrip("\n").partition("=")
            if sep:
                result[key] = value
    return result


def harness_of(meta):
    harness = meta.get("harness")
    if not harness and meta.get("claude_bin") and not meta.get("codex_context"):
        if meta.get("executable") and meta["executable"] != meta["claude_bin"]:
            refuse("contradictory legacy executable metadata")
        return "claude"
    if (
        harness not in ("codex", "claude")
        or (harness == "codex" and meta.get("claude_bin"))
        or (harness == "claude" and meta.get("codex_context"))
    ):
        refuse("unknown/contradictory lane harness metadata")
    if (
        harness == "claude"
        and meta.get("executable")
        and meta.get("claude_bin")
        and meta["executable"] != meta["claude_bin"]
    ):
        refuse("contradictory Claude executable metadata")
    return harness


def saved(path):
    meta = metadata(path)
    harness = harness_of(meta)
    result = {
        k: meta.get(k, "")
        for k in (
            "harness",
            "executable",
            "config_dir",
            "runtime_cwd",
            "permission_mode",
            "bg_ceiling",
            "codex_context",
        )
    }
    result["harness"] = harness
    if not meta.get("harness"):
        result["executable"] = meta["claude_bin"]
        config = os.environ.get("DS_LANE_LEGACY_CLAUDE_CONFIG_DIR")
        if not config or not os.path.isabs(config):
            refuse("legacy Claude resume requires DS_LANE_LEGACY_CLAUDE_CONFIG_DIR and captured init permissionMode")
        result["config_dir"] = config
        inits = [
            e
            for e in records(str(Path(path).with_suffix(".jsonl")))
            if e.get("type") == "system" and e.get("subtype") == "init" and e.get("parent_tool_use_id") is None
        ]
        init = inits[-1] if inits else {}
        sid = init.get("session_id")
        if (
            not isinstance(sid, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", sid)
            or (meta.get("session_id") and meta["session_id"] != sid)
            or not init.get("permissionMode")
            or not init.get("cwd")
        ):
            refuse("legacy Claude recovery requires coherent top-level init session/mode/cwd")
        result["permission_mode"] = init["permissionMode"]
        result["runtime_cwd"] = init["cwd"]
        result["bg_ceiling"] = "0"
    if not result["executable"] or not os.path.isabs(result["executable"]):
        refuse("saved executable is missing/not absolute")
    resolved = executable(result["executable"], harness)
    if meta.get("harness") and resolved != result["executable"]:
        refuse("saved executable path no longer resolves to original runtime")
    result["executable"] = resolved
    if not result["config_dir"] or not result["runtime_cwd"]:
        refuse("saved original config/cwd missing")
    result["config_dir"] = directory(result["config_dir"])
    result["runtime_cwd"] = directory(result["runtime_cwd"])
    if harness == "claude":
        if result["permission_mode"] not in ("default", "acceptEdits", "plan", "dontAsk", "bypassPermissions", "auto"):
            refuse("saved Claude permission mode missing/unsupported")
        if result["bg_ceiling"] != "default" and not re.fullmatch(r"[0-9]+", result["bg_ceiling"]):
            refuse("saved Claude background ceiling missing/invalid")
    else:
        context = json.loads(result["codex_context"])
        policy = codex_policy(
            {k: context.get(k) for k in ("cwd", "approval_policy", "sandbox_policy")}, result["runtime_cwd"]
        )
        if context != policy:
            refuse("saved Codex context/overrides inconsistent")
    return result


def events(path, mode):
    meta = metadata(path)
    harness = harness_of(meta)
    log = Path(path).with_suffix(".jsonl")
    values = list(records(log)) if log.exists() else []
    offset = int(meta.get("marker_offset", "0"))
    current = []
    if log.exists():
        with open(log, encoding="utf-8") as stream:
            for line in list(stream)[offset:]:
                try:
                    value = json.loads(line)
                    if isinstance(value, dict):
                        current.append(value)
                except json.JSONDecodeError:
                    pass

    def text(e):
        if harness == "codex":
            item = e.get("item", {})
            if not isinstance(item, dict) or not isinstance(item.get("text", ""), str):
                return ""
            return (
                item.get("text", "")
                if e.get("type") == "item.completed" and item.get("type") == "agent_message"
                else ""
            )
        if e.get("type") == "assistant" and e.get("parent_tool_use_id") is None:
            message = e.get("message", {})
            content = message.get("content", []) if isinstance(message, dict) else []
            if not isinstance(content, list):
                return ""
            return "\n".join(
                c["text"]
                for c in content
                if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str)
            )
        return ""

    def fatal(e):
        return (
            (e.get("type") in ("turn.failed", "error"))
            if harness == "codex"
            else (
                e.get("type") == "result"
                and e.get("parent_tool_use_id") is None
                and (e.get("is_error") is True or str(e.get("subtype", "")).startswith("error"))
            )
        )

    if mode == "fatal":
        print("1" if any(fatal(e) for e in current) else "0")
    elif mode == "marker":
        if any(fatal(e) for e in current):
            return
        marker = ""
        for e in current:
            for line in text(e).splitlines():
                line = line.lstrip(" \t*#>`")
                if line.startswith("LANE-DONE"):
                    marker = "done"
                elif line.startswith("LANE-BLOCKED"):
                    marker = "blocked"
        if marker:
            print(marker)
    elif mode == "session":
        sessions = [
            e.get("thread_id") if harness == "codex" else e.get("session_id")
            for e in values
            if (
                e.get("type") == "thread.started"
                if harness == "codex"
                else e.get("type") == "system" and e.get("subtype") == "init" and e.get("parent_tool_use_id") is None
            )
        ]
        if sessions and isinstance(sessions[-1], str):
            print(sessions[-1])
    elif mode == "texts":
        for e in values:
            if text(e):
                print(json.dumps(text(e)))
    elif mode == "result":
        terminal = [
            e
            for e in values
            if e.get("type") in (("turn.completed", "turn.failed", "error") if harness == "codex" else ("result",))
            and (harness == "codex" or e.get("parent_tool_use_id") is None)
        ]
        if terminal:
            print(json.dumps(terminal[-1]))
    elif mode == "harness":
        print(harness)


def owns(path, pid):
    meta = metadata(path)
    harness = harness_of(meta)
    binary = meta.get("executable") or meta.get("claude_bin")
    if not binary or not pid.isdigit() or meta.get("pid") != pid or not meta.get("pid_start"):
        return False
    try:
        os.kill(int(pid), 0)
        start = subprocess.check_output(["ps", "-p", pid, "-o", "lstart="], text=True)
        if re.sub(" +", " ", start).rstrip("\n") != meta["pid_start"]:
            return False
        args = subprocess.check_output(["ps", "-p", pid, "-o", "args="], text=True).strip()
        suffix = " exec" if harness == "codex" else " -p"
        shape = binary + suffix
        if args.startswith(shape + " ") or args == shape:
            return True
        with open(binary, "rb") as stream:
            shebang = stream.readline(4096).decode().strip()
        if not shebang.startswith("#!"):
            return False
        interpreter = shlex.split(shebang[2:])
        if not interpreter:
            return False
        if Path(interpreter[0]).name == "env":
            interpreter = interpreter[1:]
        if not interpreter or interpreter[0].startswith("-"):
            return False
        resolved = shutil.which(interpreter[0]) or interpreter[0]
        prefixes = {interpreter[0], resolved, str(Path(resolved).resolve()), Path(interpreter[0]).name}
        # Framework Python re-execs its app binary on macOS.
        physical = Path(resolved).resolve()
        app = physical.parent.parent / "Resources/Python.app/Contents/MacOS/Python"
        if physical.name.startswith("python") and "Python.framework" in physical.parts and app.is_file():
            prefixes.add(str(app.resolve()))
        extra = " ".join(interpreter[1:])
        return any(args.startswith(p + (" " + extra if extra else "") + " " + shape + " ") for p in prefixes)
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return False


def main():
    command, *args = sys.argv[1:]
    if command == "identity":
        print(selection()[0])
    elif command in ("resolve", "saved"):
        result = resolve() if command == "resolve" else saved(args[0])
        if any("\n" in str(v) or "\r" in str(v) for v in result.values()):
            refuse("runtime metadata contains a newline")
        print(json.dumps(result, separators=(",", ":")))
    elif command == "events":
        events(*args)
    elif command == "owns":
        sys.exit(0 if owns(*args) else 1)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, TypeError, KeyError) as error:
        print("ds-lane: " + str(error), file=sys.stderr)
        sys.exit(1)
