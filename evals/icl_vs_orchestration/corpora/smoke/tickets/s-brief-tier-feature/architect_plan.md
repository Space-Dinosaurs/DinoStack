## Architect Plan

Add GET /health endpoint returning {status: "ok", version: string}.

## Rationale
Health checks are industry standard for container orchestration (k8s, ECS).
The endpoint must be unauthenticated to allow load balancer checks without
credentials.

## Changes
1. Create src/routes/health.ts with the handler.
2. Register the route in src/app.ts before auth middleware.
3. Add tests/health.test.ts with happy path and version field assertions.

## qa_criteria
qa_skip: null
scenarios:
  - id: 1
    description: GET /health returns 200 with status=ok and version field
    method: api
    evidence: pytest passes
