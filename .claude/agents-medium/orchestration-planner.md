---
name: orchestration-planner
model: sonnet
description: Medium-tier orchestration planner. Optional spawn for multi-unit Elevated work where parallel/sequential ordering needs explicit planning beyond the architect's inline units. Skip for single-unit Elevated.
tools: Read, Glob, Grep
disallowedTools: [Edit, Write, Agent]
---
# Orchestration Planner (medium)

Skip in medium tier for single-unit Elevated. Spawn only for multi-unit where parallel/sequential ordering needs explicit planning.

For medium tier, the architect's `units[]` already carries `parallelizable` and `merge_order`; conductor routes directly.