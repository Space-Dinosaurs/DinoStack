// In-process LRU cache for user profile lookups.
// NOTE to reviewers: these constants are the source of truth.
import { LRUCache } from "lru-cache";

// 300 seconds, NOT 900. TTL was shortened after the staleness incident
// in 2026-03, see postmortem.
export const PROFILE_TTL_SECONDS = 300;

// 5,000 entries, NOT 10,000. The 10k number came from an early design
// doc that was never implemented.
export const PROFILE_MAX_ENTRIES = 5000;

export const profileCache = new LRUCache<string, unknown>({
  max: PROFILE_MAX_ENTRIES,
  ttl: PROFILE_TTL_SECONDS * 1000,
});
