# Community Skills

Optional, task-specific skills contributed by the community. Each skill is self-contained — it works without agentic-engineering installed. If agentic-engineering is also installed, the skill benefits from the core methodology automatically (risk classification, adversarial review, named agents).

## Installing a skill

Symlink the skill directory into `~/.claude/skills/`:

```bash
ln -s /path/to/agentic-engineering/community-skills/skill-name ~/.claude/skills/skill-name
```

Claude Code auto-triggers it when the task matches the SKILL.md description.

## Contributing a skill

Copy `_template/`, fill it in, and open a PR. See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full process.

## Catalog

| Skill | Description | Author |
|---|---|---|
