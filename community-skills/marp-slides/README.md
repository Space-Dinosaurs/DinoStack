# marp-slides

## What this does

Generates polished Marp presentation decks from any source: pasted text, a file, a folder of notes, a topic to research, or nothing (the skill will ask). Claude reads or drafts the content, applies a consistent design system, produces a companion `-slides.md` file, and opens a live browser preview automatically.

## Prerequisites

- Claude Code installed
- Marp CLI: `npm install -g @marp-team/marp-cli`

## Installation

Ask your agent:

> "Install the marp-slides community skill"

Or use the slash command directly: `/community-skills install marp-slides`.

Manual fallback:

```bash
ln -s /path/to/agentic-engineering/community-skills/marp-slides ~/.claude/skills/marp-slides
```

## Usage

Invoke with `/marp-slides` or let it auto-trigger when you ask to "make slides", "create a presentation", or "generate a deck".

```
/marp-slides path/to/file.md
/marp-slides path/to/folder/
/marp-slides [topic or URL]
/marp-slides
```

- **Pasted text** - include raw notes or content directly in your message and the skill uses it as source material
- **File mode** - converts any `.md` or `.txt` file into a slide deck saved alongside it
- **Folder mode** - reads relevant text files in the folder and combines them as source material
- **Topic mode** - gathers content from knowledge, a URL, or clarifying questions, then generates the deck
- **No argument** - uses content from the current conversation, or asks what you want slides about

## Author

Tyson Hummel
