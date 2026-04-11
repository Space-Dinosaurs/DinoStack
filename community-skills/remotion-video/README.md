# remotion-video

## What this does

Generates animated MP4 video presentations using Remotion. Give it a file, a folder of notes, pasted text, or a topic description and it produces a polished 35-second video with 7 animated slides: title, overview, up to 4 key point slides, and a takeaway. Optionally reads a `brand.json` manifest to apply company colors, fonts, logo, and footer automatically.

## Prerequisites

- Node.js 18+
- `npx` available on the PATH

## Installation

Ask your agent:

> "Install the remotion-video community skill"

Or use the slash command directly: `/community-skills install remotion-video`.

Manual fallback:

```bash
ln -s /path/to/agentic-engineering/community-skills/remotion-video ~/.claude/skills/remotion-video
```

## Usage

```
/remotion-video path/to/file.md
/remotion-video path/to/folder/
/remotion-video [topic description]
/remotion-video
```

Pass a file, folder, or topic. If no argument is given, the skill uses content from the current conversation or asks what you want the video to be about.

First use initializes `~/remotion-slides/` and runs `npm install` - this takes approximately 1 minute. Subsequent uses only regenerate the component and re-render, which takes 30-90 seconds.

The output MP4 is saved alongside the source file (if one was given) with the same base name (e.g., `my-doc.md` -> `my-doc.mp4`), or to the current working directory for topic/pasted-text input.

## Brand / theme

Drop a `brand.json` in your project directory (or at `~/.claude/brand/brand.json` for a global default) and the skill will apply your colors, fonts, logo, and footer automatically. See `references/brand-schema.md` for the full schema.

## Author

Tyson Hummel
