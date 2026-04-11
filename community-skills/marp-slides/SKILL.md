---
name: "marp-slides"
description: >
  Use when the user asks to create a slide deck or presentation from any source - pasted text, a file, a folder, a topic description, or nothing yet. Triggers on /marp-slides or phrases like "make slides", "create a presentation", or "generate a deck".
---

# Marp Slides Skill

Generate polished Marp presentation decks from any source material.

## When to use

Use this skill when the user asks to create a slide deck, presentation, or Marp deck - from an existing file, pasted content, a folder of notes, a topic to research, or when they haven't decided yet.

Do NOT trigger for Remotion, video, or MP4 export requests. Those require a separate video rendering workflow.

## What it does

This skill follows a four-step flow: determine mode, optionally research the topic, generate a Marp `.md` deck using the style guide, then open a live preview automatically.

## Prerequisites

Before generating slides, verify Marp CLI is available:

```bash
which marp
```

If not found, install it:

```bash
npm install -g @marp-team/marp-cli
```

## Instructions

### Step 1 - Determine input mode

Identify which of the following applies, in order:

1. **Pasted text** - the user included raw content in their message. Use it directly as source material. Skip to Step 3.
2. **File path** - the argument is a path to an existing file (`.md`, `.txt`, or similar). Read the file and use its content as source material. Skip to Step 3.
3. **Folder path** - the argument is a path to a directory. Read the relevant text files in that folder and treat their combined content as source material. Skip to Step 3.
   - File types: `.md`, `.markdown`, `.txt` only.
   - Recursion: top-level only - do not descend into subdirectories.
   - Ordering: alphabetical by filename.
   - Size cap: if combined content exceeds ~50KB, select the most relevant files rather than including everything (prefer files that best match the user's stated topic if one was given).
   - Skip hidden files (dotfiles). Skip `LICENSE` and `CHANGELOG.md` unless they are the topic itself.
4. **Topic description** - the argument is a topic, URL, or natural-language description with no associated file. Proceed to Step 2.
5. **No argument** - check if source material or a relevant document was produced earlier in the current conversation and use that. If nothing is available, ask the user what they want slides about and offer the input options above.

Note: if the source file happens to follow a structured research-doc format (H1 title, `## Summary`, `## Key Points`, `**Source:**`, etc.), parse those sections to guide slide structure. That structure is convenient but not required.

### Step 2 - Gather content (topic mode only)

The user gave a topic with no accompanying source material. Gather enough context to produce a solid deck using one or more of these approaches:

- For well-known topics, draft from general knowledge.
- For URLs or YouTube links, fetch or summarize the content.
- For niche or ambiguous topics, ask the user 1-2 targeted clarifying questions before drafting.

There is no requirement to save a research document. Proceed directly to Step 3 once you have sufficient content.

### Step 2.5 - Load brand

Resolve a brand manifest using the following chain (first match wins):

1. Look for `brand.json` in the current working directory. If not found, walk up parent directories toward the git root, checking each for `brand.json` or `.brand/brand.json`.
2. Check `~/.claude/brand/brand.json` as a global default.
3. If no manifest is found, proceed with built-in defaults.

The manifest schema is documented in `~/.claude/skills/marp-slides/references/brand-schema.md`.

After resolving, print exactly one line:

- Manifest found, all fields present: `Brand: Acme Corp (from ./brand.json)`
- Manifest found, some fields missing: `Brand: Acme Corp (from ./brand.json, defaults for: accent, fonts)`
- No manifest found: `Brand: none (using default style guide)`

List only the top-level fields that are absent or empty (colors, fonts, logo, logoLight, footer). Do not list individual sub-keys.

### Step 3 - Generate the Marp deck

Read the reference file at `~/.claude/skills/marp-slides/references/marp-style-guide.md` for the design system and CSS conventions.

**When a brand manifest was resolved in Step 2.5**, build the `style` block in the Marp front matter from the manifest instead of copying it verbatim from the style guide. Apply the following mappings:

```css
section {
  background: <colors.bg>;
  color: <colors.fg>;
  font-family: '<fonts.body>', sans-serif;
}
h1, h2, h3 {
  color: <colors.primary>;
  font-family: '<fonts.heading>', sans-serif;
}
section.lead {
  background: <colors.bg>;  /* or a gradient derived from it */
  color: <colors.fg>;
}
.card {
  border-left-color: <colors.primary>;
}
.callout {
  border-left-color: <colors.primary>;
}
.stat {
  color: <colors.primary>;
}
blockquote {
  border-left-color: <colors.primary>;
}
.label, caption, figcaption {
  color: <colors.muted>;
}
```

Omit any mapping whose source field is absent; fall back to the value from the style guide for that property only. The generated `<style>` block must be valid CSS.

**Logo injection:** if the manifest provides `logo` (or `logoLight` for `lead` slides with dark backgrounds), inject it as a small top-right persistent element on every slide using an HTML `<img>` tag positioned absolutely. The path to use is the resolved absolute path of the logo file (it does not need copying for Marp - Marp resolves local paths directly).

Example HTML to inject once after the front matter (applies to all slides):

```html
<style scoped></style>
<div style="position:fixed;top:16px;right:24px;z-index:100;">
  <img src="<resolved-logo-path>" style="height:36px;width:auto;" />
</div>
```

Position: top-right. Height: 36px. Do not cover content.

**Footer:** if the manifest provides `footer`, add `footer: "<footer text>"` to the Marp front matter.

Create a Marp `.md` file following these rules:

**File location and naming:**
- If the input was a file, save as `[basename]-slides.md` in the same directory as that file. Example: `notes/quantum-computing.md` -> `notes/quantum-computing-slides.md`
- If the input was a folder, save as `[folder-name]-slides.md` inside that folder.
- If the input was pasted text or a topic description, save as `[slugified-topic]-slides.md` in the current working directory, or ask the user where to save if the right location is unclear.

**Content structure:**
- **Slide 1:** Title slide using `<!-- _class: lead -->` with the topic name and a one-line subtitle
- **Slide 2:** Summary/overview - the "what and why" in 3-5 bullet points
- **Slides 3-6:** Key points from the research, one concept per slide. Use visual elements (cards, columns, tables, stat callouts) where the content benefits from it. Don't force visuals where plain bullets work better.
- **Final slide:** Takeaways or "why it matters" - the so-what, using the lead class

**Design principles:**
- Prefer clarity over decoration. Every visual element should serve comprehension.
- Use the CSS classes and HTML components from the style guide - don't invent new ones unless needed.
- Keep text per slide to what you can read in 15 seconds. If it's more, split the slide.
- Use `<!-- _class: highlight -->` for data-heavy or comparison slides.
- Tables are great for comparisons. Cards/columns are great for stats or parallel concepts.
- Include speaker-note-style context in HTML comments where the slide content is compressed from richer source material.

**Technical requirements:**
- Front matter must include `marp: true`, `theme: default`, `paginate: true`, and the full `style` block from the style guide.
- Use `---` to separate slides.
- HTML is allowed and expected for visual elements (div columns, cards, etc.).
- Keep the total deck to 5-8 slides. Brevity is the point.

### Step 4 - Preview

After saving the file, automatically run:

```bash
marp --preview [file]
```

This opens a live preview in the browser. Other export commands the user can run manually if needed:

```
PDF:   marp --pdf [file]
PPTX:  marp --pptx [file]
HTML:  marp [file]
```

## Examples

```
/marp-slides notes/meeting-notes.md          (file path)
/marp-slides ~/projects/my-research-folder/  (folder path)
/marp-slides quantum computing basics        (topic - drafts from knowledge)
/marp-slides https://youtu.be/some-video-id  (URL - fetches and summarizes)
/marp-slides                                 (no arg - skill asks what you want)

# With pasted content:
/marp-slides
[paste your notes or text directly into the message]
```
