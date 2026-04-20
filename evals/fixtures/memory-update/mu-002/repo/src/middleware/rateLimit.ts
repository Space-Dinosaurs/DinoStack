// Redis-backed fixed-window rate limiter. Window: 60s. Key: token hash.
// Limit: currently 100 rps per token (pending bump to 250).
import type { Request, Response, NextFunction } from "express";

export const WINDOW_SECONDS = 60;
export const LIMIT_PER_TOKEN = 100;

export function rateLimit(req: Request, res: Response, next: NextFunction) {
  // implementation elided for fixture
  next();
}
