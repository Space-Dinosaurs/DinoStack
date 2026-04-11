# Community Skills

Optional, task-specific skills contributed by the community. Each skill is self-contained — it works without agentic-engineering installed. If agentic-engineering is also installed, the skill benefits from the core methodology automatically (risk classification, adversarial review, named agents).

## Installing a skill

The easiest way is to ask your agent:

> "Install the <skill-name> community skill"

The agent uses `/community-skills install <skill-name>` to symlink the skill into `~/.claude/skills/`. You can also list available skills with `/community-skills list` or browse them during the initial `bash .claude/install.sh` run.

Manual fallback:

```bash
ln -s /path/to/agentic-engineering/community-skills/skill-name ~/.claude/skills/skill-name
```

Claude Code auto-triggers the skill when the task matches the SKILL.md description.

## Contributing a skill

Copy `_template/`, fill it in, and open a PR. See [CONTRIBUTING.md](../CONTRIBUTING.md#contributing-a-community-skill) for the full process and the [formatting standards](../CONTRIBUTING.md#formatting-standards) every community skill must follow.

## Catalog

| Skill | Description | Author |
|---|---|---|
| marp-slides | Generate polished Marp slide decks from research documents or topics | @tysonhummel |
| remotion-video | Generate animated MP4 video presentations from any source using Remotion | @tysonhummel |
