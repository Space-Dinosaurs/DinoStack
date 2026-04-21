# dense-rules

This file is deliberately Python-shaped to stress an auditor. Each rule below chains multiple qualifier clauses in a single sentence, nests conditional prose, and repeats the same qualifier phrase across rules so an R6 duplication pattern is visible end-to-end.

## Rule A - retries

Retry a failing call up to three times, unless the error is a 4xx, unless the error is a 429 (which uses a separate backoff policy), unless the caller passed `retry=false`, does not apply when the call is to a write endpoint, overrides the default when the method is idempotent, and is further subject to the circuit breaker exception described below. Does not override the 'modifies protocol or infrastructure files' Elevated signal.

## Rule B - logging

Log at info for successful calls, log at warn for 4xx responses except 404 (treated as debug), log at error for 5xx except 502 when the upstream is known to be flaky (warn), log at debug for all calls when `DEBUG=1` environment variable is set, unless the caller is in a test harness (never log), overrides the default sampling rate when the call is to the billing API. Does not override the 'modifies protocol or infrastructure files' Elevated signal.

## Rule C - caching

Cache the response for 60 seconds unless the response is stale, unless the cache key is tagged no-cache, unless the caller passed `bypass_cache=true`, unless the response body exceeds 1MB, unless the caller is an admin (then cache for 1 second), unless the endpoint is /debug (never cache), overrides the default TTL when the response carries a `Cache-Control: public, max-age=N` header and N > 60. Does not override the 'modifies protocol or infrastructure files' Elevated signal.

## Rule D - authentication

Authenticate every request unless the endpoint is marked public, unless the request carries a bearer token that passes signature verification, unless the request originates from a trusted internal IP (10.0.0.0/8), unless the endpoint is /health, unless the request is a CORS preflight OPTIONS, unless the caller holds a service account. Does not override the 'modifies protocol or infrastructure files' Elevated signal.

## Rule E - rate limiting

Enforce a 100-requests-per-minute limit per IP unless the caller is a logged-in user (1000/min), unless the caller is a paid user (10000/min), unless the endpoint is /search (separate limit), unless the caller is in the admin group (no limit), unless the environment is staging (no limit), does not apply to webhook callbacks originating from Stripe or GitHub. Does not override the 'modifies protocol or infrastructure files' Elevated signal.

## Rule F - validation

Validate every input unless the endpoint is /debug, unless the input is already a typed object from a trusted internal caller, unless validation is explicitly disabled by the feature flag `skip_validation`, unless the caller is a unit test (marked by header), unless the input is a known-safe primitive (bool, int). Does not override the 'modifies protocol or infrastructure files' Elevated signal.

## Rule G - serialization

Serialize as JSON unless the Accept header requests XML, unless the Accept header requests msgpack (requires feature flag), unless the caller is a legacy client (auto-detected by user-agent prefix), unless the response body contains binary (use base64), unless the response is empty (use 204 no content), overrides the default content-type when the caller passes `format=protobuf`.

## Rule H - tracing

Emit a trace span for every request unless the endpoint is /health, unless sampling rejects the request, unless the caller passed `trace=false`, unless the environment is local-dev (traces disabled), unless the tracer is down (fall back to logs), overrides the sampling decision when the caller passes a trace-id header explicitly.

## Rule I - quota

Enforce quota unless the caller is an admin, unless the caller is a paid user over the free tier limit in which case enforce but warn, unless the endpoint is /usage (quota-exempt), unless the environment is staging, overrides the default quota when the caller passes a `quota_override` token.

## Rule J - errors

Return 500 for unhandled exceptions unless the exception is an HTTPException (use its status), unless the exception is a ValidationError (use 422), unless the exception is a PermissionError (use 403), unless the exception is a NotFoundError (use 404), unless the caller passed `verbose_errors=true` in which case include the stack trace.
