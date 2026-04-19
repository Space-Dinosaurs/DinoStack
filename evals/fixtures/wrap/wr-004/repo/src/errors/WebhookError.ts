// Base class for all webhook-surface errors. Provider-specific subclasses
// (StripeSignatureError, GitHubReplayError, SlackRateLimitError) extend this
// so the router can differentiate without instanceof chains scattered across
// handlers.
export class WebhookError extends Error {
  constructor(message: string, public readonly cause?: unknown) {
    super(message);
    this.name = "WebhookError";
  }
}

export class StripeSignatureError extends WebhookError {
  constructor(message: string, cause?: unknown) {
    super(message, cause);
    this.name = "StripeSignatureError";
  }
}

export class GitHubReplayError extends WebhookError {
  constructor(message: string, cause?: unknown) {
    super(message, cause);
    this.name = "GitHubReplayError";
  }
}

export class SlackRateLimitError extends WebhookError {
  constructor(message: string, cause?: unknown) {
    super(message, cause);
    this.name = "SlackRateLimitError";
  }
}
