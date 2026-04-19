import type { Request, Response } from "express";
import { WebhookError } from "../errors/WebhookError";

// All webhook traffic enters through this dispatcher. Per-provider modules
// under src/webhooks/ register their handler here; no provider module is
// mounted directly on the Express app.
type Handler = (req: Request, res: Response) => Promise<void>;
const handlers = new Map<string, Handler>();

export function register(provider: string, handler: Handler): void {
  handlers.set(provider, handler);
}

export async function routeWebhook(req: Request, res: Response): Promise<void> {
  const provider = String(req.params.provider || "");
  const handler = handlers.get(provider);
  if (!handler) {
    throw new WebhookError(`no handler registered for provider: ${provider}`);
  }
  await handler(req, res);
}
