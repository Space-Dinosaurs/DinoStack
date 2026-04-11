---
name: "remotion-video"
description: >
  Use when the user asks to create an animated video or MP4 presentation from any source - a file, pasted text, a folder, or a topic description. Triggers on /remotion-video or phrases like "animate these slides", "video presentation", or "make an MP4 from this".
---

## When to use

Trigger on `/remotion-video`, on phrases like "video presentation", "animated slides", "make an MP4", or when the user explicitly asks for Remotion output. Does NOT trigger for static Marp/PDF/PPTX slide requests.

## What it does

Checks for an existing Remotion project at `~/remotion-slides/`; if not found, initializes one non-interactively; extracts or drafts structured slide data from the provided input; resolves any brand/theme manifest; fills in the ResearchSlides component template with the actual content and theme; renders an MP4; and saves it next to the source file or in the current working directory.

## Instructions

### Step 1 - Identify source and extract slide data

Identify which of the following applies, in order:

1. **Pasted text** - the user included raw content in their message. Use it as source material.
2. **File path** - the argument is a path to an existing file. Read the file.
3. **Folder path** - the argument is a path to a directory. Read the relevant text files in that folder and treat their combined content as source material.
   - File types: `.md`, `.markdown`, `.txt` only.
   - Recursion: top-level only - do not descend into subdirectories.
   - Ordering: alphabetical by filename.
   - Size cap: if combined content exceeds ~50KB, select the most relevant files rather than including everything (prefer files that best match the user's stated topic if one was given).
   - Skip hidden files (dotfiles). Skip `LICENSE` and `CHANGELOG.md` unless they are the topic itself.
4. **Topic description** - a natural-language topic with no file. Draft the slide data directly from general knowledge (or ask 1-2 clarifying questions if the topic is ambiguous).
5. **No argument** - use the most recent source material or document produced in the current conversation. If nothing is available, ask the user what they want the video to be about and offer the input options above.

Once you have source material, extract the following fields to populate `slideData`:

- `title`: the main subject or H1 heading if present
- `subtitle`: a one-line framing of the topic
- `summary`: 3-5 bullet points summarizing the core content
- `keyPoints`: up to 4 entries, each with a `heading` and `body` (2-3 sentences or key facts)
- `takeaway`: 1-2 sentences on the key conclusion or "why it matters"
- `source`: the origin of the material (URL, filename, or `""` if none)

**Fast path:** if the source file follows a structured format with `## Summary`, `## Key Points`, `## Details`, `## Takeaways`, and a `**Source:**` line, parse those sections directly. Otherwise, extract the fields from whatever structure or prose is present. For a bare topic with no source, draft all fields from knowledge.

### Step 2 - Check and initialize Remotion project

Run:
```bash
ls ~/remotion-slides/package.json 2>/dev/null && echo EXISTS || echo MISSING
```

If MISSING, initialize the project non-interactively:
```bash
mkdir -p ~/remotion-slides/src ~/remotion-slides/out ~/remotion-slides/public
cd ~/remotion-slides
npm init -y
npm install remotion @remotion/cli @remotion/transitions react react-dom
```

Then copy the static template files into the project:
```bash
cp ~/.claude/skills/remotion-video/templates/index.ts ~/remotion-slides/src/index.ts
cp ~/.claude/skills/remotion-video/templates/Root.tsx ~/remotion-slides/src/Root.tsx
```

Note: `ResearchSlides.tsx` is NOT copied from the template - it is generated fresh in Step 3.

If the project already EXISTS, skip initialization. The `index.ts` and `Root.tsx` files are already in place.

### Step 2.5 - Load brand

Resolve a brand manifest using the following chain (first match wins):

1. Look for `brand.json` in the current working directory. If not found, walk up parent directories toward the git root, checking each for `brand.json` or `.brand/brand.json`.
2. Check `~/.claude/brand/brand.json` as a global default.
3. If no manifest is found, proceed with built-in defaults.

The manifest schema is documented in `~/.claude/skills/remotion-video/references/brand-schema.md`.

After resolving, print exactly one line:

- Manifest found, all fields present: `Brand: Acme Corp (from ./brand.json)`
- Manifest found, some fields missing: `Brand: Acme Corp (from ./brand.json, defaults for: accent, fonts)`
- No manifest found: `Brand: none (using default style guide)`

List only the top-level fields that are absent or empty (colors, fonts, logo, logoLight, footer). Do not list individual sub-keys.

**Asset copy:** if the manifest includes `logo` or `logoLight` paths, those paths are relative to the manifest file. Copy each asset into `~/remotion-slides/public/` so Remotion can reference it via `staticFile()`. Preserve the original filename. Example:

```bash
cp /path/to/brand/assets/logo.svg ~/remotion-slides/public/logo.svg
```

Build a `theme` object from the resolved manifest to pass alongside `slideData` in Step 3. Shape:

```typescript
interface Theme {
  colors?: {
    primary?: string;
    accent?: string;
    bg?: string;
    fg?: string;
    muted?: string;
  };
  fonts?: {
    heading?: string;
    body?: string;
  };
  logo?: string;       // filename only, relative to public/ (e.g. "logo.svg")
  logoLight?: string;  // filename only, relative to public/
  footer?: string;
}
```

If no manifest is found, pass `theme: {}`.

### Step 3 - Fill in ResearchSlides.tsx

Read the template at `~/.claude/skills/remotion-video/templates/ResearchSlides.tsx`. This file has a clearly marked `const slideData` block containing placeholder strings and a `theme` prop interface. Replace the entire `slideData` object with the actual parsed content from Step 1. Also embed the resolved `theme` object from Step 2.5 as `defaultProps` on the `ResearchSlides` composition (see template for the exact pattern). Keep all other code in the file unchanged. Write the result to `~/remotion-slides/src/ResearchSlides.tsx`.

The `slideData` object must conform exactly to this TypeScript interface (defined in the template):
```typescript
interface KeyPoint {
  heading: string;
  body: string;
}
interface SlideData {
  title: string;
  subtitle: string;
  summary: string[];      // 3-5 items
  keyPoints: KeyPoint[];  // 1-4 items
  takeaway: string;
  source: string;
}
```

### Step 4 - Render

```bash
cd ~/remotion-slides && npx remotion render src/index.ts ResearchSlides out/slides.mp4 --overwrite
```

If this is the first render, it may take 30-90 seconds. Wait for it to complete.

### Step 5 - Copy output

Derive the output path as follows:

- If the input was a file, save next to it with the same base name: `notes/my-topic.md` -> `notes/my-topic.mp4`
- If the input was a folder, save inside that folder as `[folder-name].mp4`
- If the input was pasted text or a topic, save to the current working directory as `[slugified-topic].mp4`, or ask the user where to save if unclear

```bash
cp ~/remotion-slides/out/slides.mp4 /derived/output/path.mp4
```

Report the output path to the user.
