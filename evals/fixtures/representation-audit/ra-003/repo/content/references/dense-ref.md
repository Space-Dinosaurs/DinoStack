# dense-ref

Each section below nests multiple conditional branches in a single prose block without structural separation, duplicates qualifier phrases across sections, and reads like procedural pseudocode where structural description of the outcome would communicate the same intent more directly.

## Section 1 - request lifecycle

When a request arrives, first check the auth header; if present, verify the signature; if the signature fails, return 401; if valid, check the scope; if the scope is insufficient, return 403; if sufficient, forward to the handler; if the handler throws, log at error and return 500; if the handler returns, serialize the result; if serialization fails, return 500 with a generic message; if succeeds, emit a trace span; if tracing is disabled, skip; if the request was a write, invalidate the cache for the affected key; if the key is not in the cache, skip.

## Section 2 - response shaping

Wrap every response in an envelope unless the caller is legacy, unless the caller passed `raw=true`, unless the endpoint is /stream (chunked), unless the response is an error (use the error envelope instead), unless the caller is an admin debugging (full unwrapped). Does not apply to webhook callbacks.

## Section 3 - upstream calls

Every upstream call first checks the circuit breaker; if open, fail fast with a 503; if half-open, attempt once with reduced timeout; if success, close the breaker; if failure, re-open and emit a warn log; if closed, proceed normally; if the call exceeds the timeout, abort and emit a warn log; if the call is idempotent, retry per Rule A above; if not, do not retry. Does not apply to webhook callbacks.

## Section 4 - feature flags

Check the feature flag cache first; if cached within the TTL, use it; if expired, fetch from the flag service; if the flag service is down, fall back to the last known value; if no last known value, fall back to the default (off); if the default is unknown (new flag), log a warn and treat as off; if the caller is internal staff, flip the flag on regardless; if the environment is staging, flip every flag on by default. Does not apply to webhook callbacks.

## Section 5 - deprecations

Emit a deprecation warning header on every response from a deprecated endpoint unless the caller passed `suppress_deprecation=true`, unless the environment is prod (reduced sampling), unless the caller-agent is internal-batch (suppress always). Does not apply to webhook callbacks.
