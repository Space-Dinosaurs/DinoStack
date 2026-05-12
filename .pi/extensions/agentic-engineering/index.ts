/**
 * Native Pi extension for agentic-engineering.
 *
 * Adds the two lifecycle behaviors that hook-capable adapters provide:
 * - before_agent_start: inject a short risk/methodology reminder
 * - session_shutdown: run the shared stop-context writer best-effort
 */

import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const extensionDir = dirname(fileURLToPath(import.meta.url));
const repoDir = resolve(extensionDir, "../../..");
const stopContextScript = join(repoDir, "hooks", "stop-context.js");

function sessionIdFromContext(ctx: any): string | null {
  try {
    const sessionFile = ctx?.sessionManager?.getSessionFile?.();
    if (typeof sessionFile !== "string" || sessionFile.length === 0) return null;
    const base = sessionFile.split(/[\\/]/).pop() ?? "";
    return base.replace(/\.jsonl?$/i, "") || null;
  } catch {
    return null;
  }
}

export default function agenticEngineeringPiExtension(pi: ExtensionAPI) {
  pi.on("before_agent_start", async (event) => {
    const prompt = String(event.prompt ?? "").toLowerCase();
    const looksLikeEngineering = /\b(code|implement|fix|debug|test|refactor|review|design|build|feature|bug|adapter|ci|deploy|api|component)\b/.test(prompt);
    if (!looksLikeEngineering) return;

    return {
      message: {
        customType: "agentic-engineering-reminder",
        content:
          "Agentic-engineering reminder: run activation preflight from the agentic-engineering skill before engineering work. Classify risk, use the right specialist/delegation pattern, preserve user changes, and verify before claiming completion.",
        display: true,
      },
    };
  });

  pi.on("session_shutdown", async (_event, ctx) => {
    if (!existsSync(stopContextScript)) return;
    const cwd = process.cwd();
    const payload = {
      cwd,
      session_id: sessionIdFromContext(ctx),
      transcript: [],
    };

    spawnSync(process.execPath, [stopContextScript], {
      input: JSON.stringify(payload),
      encoding: "utf8",
      stdio: ["pipe", "ignore", "ignore"],
      timeout: 5000,
    });
  });
}
