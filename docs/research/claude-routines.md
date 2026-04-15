# Claude Routines

**Source:** https://youtu.be/j3aXJNu9804 (Nick Saraev - "Claude Routines Just Dropped, And It's Perfect")
**Date Researched:** 2026-04-14
**Category:** agentic-frameworks

---

## Summary

Anthropic has launched Claude Routines, a feature that turns Claude into a full-fledged automation platform. Routines let users schedule Claude runs, trigger them via webhooks, or call them via API, with natural-language instructions replacing the drag-and-drop node graphs of tools like n8n and Make.com. The feature effectively closes the loop on agentic workflows by running the "logic middle" of any automation as a cloud-hosted Claude session rather than a hand-built node graph.

## Key Points

- **What it is:** Routines are cloud-hosted Claude Code sessions that can be triggered three ways - on a schedule (hourly/daily/custom), from an incoming webhook, or from an API call. Each routine runs in a standardized cloud container (not on the user's machine).
- **Natural-language automation:** Instead of wiring drag-and-drop nodes, you describe what Claude should do in each session as a prompt (like a skill / SOP). Connectors (Gmail, Slack, GitHub, etc.) are attached once and referenced from the prompt.
- **Head-on competitor to n8n / Make.com:** Saraev frames routines as a "1-to-1 overlap" with no-code automation platforms. The old model was event -> n8n node graph -> output. The new model is event -> natural language prompt -> output.
- **UX:** Accessed at `claude.ai/code/routines`. Routines show in a grid view and a calendar view with scheduled run times. Creating a new routine requires: name, description/prompt, repository, model (e.g., Opus 4.6 1M), environment, trigger, and connectors.
- **Tight coupling with Claude Code:** Routines reuse the same skill/connector/managed-session infrastructure as Claude Code, so anything you can build as a Claude Code skill you can essentially deploy as a routine.
- **Porting existing n8n flows:** Saraev demonstrates copying an n8n workflow as JSON and pasting it into Claude Code with a "routine generator" skill that converts the node graph into a natural-language routine automatically.

## Details

### Example 1 - Daily mailbox summary + drafts
A scheduled routine (set for 5:10 AM) that:
1. Pulls unread Gmail messages via the Gmail connector.
2. For each unread, checks prior conversation context with that contact.
3. Drafts replies based on the user's context and style.
4. Sends a summary with the drafts to Slack via the Slack connector.

The user wakes up to a Slack DM containing a high-level summary plus already-drafted replies sitting in Gmail drafts. Saraev shows real output including a polite decline and an acceptance draft for a podcast invitation.

### Example 2 - Transcript-to-proposal via API trigger
A routine set to fire on an API call. A Claude Code instance sends a curl request with a Fireflies.ai meeting transcript as the payload. The routine:
1. Receives the transcript.
2. Invokes another managed-session AI agent (Saraev's "proposal generator") to build the proposal.
3. Uses Slack to deliver it.

Key point: "managed sessions" let routines call other Claude agents as subagents in siloed containers for security/safety. Saraev notes the original proposal generator took him 2.5-3 hours to build in a traditional no-code tool; now it's a routine that's written in minutes.

### Example 3 - Porting an n8n Hacker News scraper
Saraev copies an n8n workflow (as JSON) into a Claude Code window running his routine-generator skill. The skill reads the node graph and auto-creates a routine that fetches Hacker News stories from the Algolia API, extracts hits, formats them as markdown, and commits the report. He then modifies the routine on the fly ("send me a Slack message with the scrape after it's done") without touching any nodes - a 3-second edit vs. a laborious n8n modification.

### The "middle problem" this solves
Old automation: `event -> n8n node graph (credentials, auth, field mapping, branching logic) -> output platform`. The middle (node graph) was where most human effort went. Routines replace the middle with a natural-language prompt while keeping the same event sources and output destinations. Saraev considers this the final piece that makes Claude a direct replacement for n8n.

### Authoring guidance
- Be more precise in routine prompts than in interactive skills. Routines run hands-off, so there's no opportunity to steer mid-run. Decrease the surface area for screw-ups by being explicit.
- There's no apparent length limit on the description, so err toward more context.
- Attach connectors once (Gmail, Slack, GitHub, etc.) via `Claude Code settings -> Connectors`, then reference them in prompts.
- For API-triggered routines you get a curl snippet you can paste into any agent to fire the routine.

### Practical agency use cases Saraev is deploying
- Replace proposal generators with routines.
- Post-sales-call webhook: receive a Fireflies transcript -> routine -> drafts immediate follow-up email + workflow diagram for perceived quality.
- Signature detection webhook: when a proposal is signed -> routine -> send onboarding email + calendar invite + thank-you message.

## Takeaways / Why It Matters

- **Routines are the credible n8n killer.** Previous Claude features overlapped with no-code tools; routines match the full event-trigger-to-output loop and the scheduling primitive, so there's no longer a feature gap.
- **Natural language replaces node graphs for most back-office automation.** Anything that doesn't require a human in the loop - proposals, email triage, transcript processing, CRM updates, monitoring - is now a prompt plus two connectors.
- **Skills compose into routines cleanly.** If you already have skills working in interactive Claude Code, converting them into routines is mostly about tightening the prompt for unattended execution and choosing a trigger.
- **Token cost vs. compute cost tradeoff.** Saraev notes routines are token-heavy and thus pricier than running a pure compute node graph for high-volume flows. The value prop is build speed and natural-language iteration, not raw per-run cost. Don't blindly port every existing n8n workflow; use routines for new automations or ones where iteration speed matters.
- **Managed sessions enable multi-agent orchestration.** Routines can call other managed agents as subagents in isolated containers, which is the primitive needed for non-trivial agentic pipelines (e.g., transcript -> proposal-generator agent -> Slack).

## Sources

- YouTube: https://youtu.be/j3aXJNu9804 (Nick Saraev, "Claude Routines Just Dropped, And It's Perfect", 2026-04-14, 18m07s)
- Claude Routines UI: `claude.ai/code/routines` (referenced in video)
