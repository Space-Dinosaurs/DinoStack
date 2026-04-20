# agent-methodology

## Activation preflight
Standard preflight.

## Model notes
This methodology was tuned against Claude 3.5 Sonnet. The Worker preamble
assumes that model's context window and tool-use reliability.

## Worker preamble
Workers execute tasks inside their declared tool_scope.
