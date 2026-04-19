# webhook-service

agentic-engineering: opt-in

## Stack
- Node.js 20, Express 4.x
- Stripe, GitHub, Slack webhook receivers

## Conventions
- Each webhook type has its own module under src/webhooks/.
- Incoming payloads are validated before any downstream call.
- Error surface uses a typed hierarchy rooted at WebhookError.
