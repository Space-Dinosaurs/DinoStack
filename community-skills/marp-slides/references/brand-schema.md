# Brand Manifest Schema

Place a `brand.json` file in your project directory (or at `~/.claude/brand/brand.json` for a global default) to apply your company's colors, fonts, logo, and footer to generated decks automatically.

## Schema

```json
{
  "name": "Acme Corp",
  "colors": {
    "primary": "#0b5cff",
    "accent": "#ff6b00",
    "bg": "#0a0a0a",
    "fg": "#ffffff",
    "muted": "#9ca3af"
  },
  "fonts": {
    "heading": "Inter",
    "body": "Inter"
  },
  "logo": "assets/logo.svg",
  "logoLight": "assets/logo-light.svg",
  "footer": "Confidential - Acme Corp 2026"
}
```

## Field reference

| Field | Type | Description |
|---|---|---|
| `name` | string | Company or brand name. Used in the brand announcement line. |
| `colors.primary` | string (hex) | Main brand color. Applied to headings, accent borders, `.card` borders, `.callout` borders, `.stat` text, `blockquote` borders. |
| `colors.accent` | string (hex) | Secondary color. Applied to highlights. If absent, the skill may derive one or fall back to the built-in default. |
| `colors.bg` | string (hex) | Slide background (`section` background). |
| `colors.fg` | string (hex) | Primary text color (`section` color). |
| `colors.muted` | string (hex) | Secondary/muted text color (`.label`, captions). |
| `fonts.heading` | string | Font family for `h1`-`h3`. Must be available on the render machine or loadable via Google Fonts. |
| `fonts.body` | string | Font family for body text (`section` font-family). |
| `logo` | string (path) | Path to a logo file - default version (suitable for light backgrounds). |
| `logoLight` | string (path) | Path to a logo optimized for dark backgrounds. Used on `lead` slides. If absent, `logo` is used instead. |
| `footer` | string | Footer text injected on every slide via Marp's `footer:` directive. |

## Rules

**All asset paths are relative to the manifest file itself, not to the current working directory.** This makes brand kits portable - zip the directory containing `brand.json` and its assets and share it; the paths stay correct.

**All fields are optional.** Any missing field falls back to the skill's built-in defaults (defined in `references/marp-style-guide.md`). You can provide just `colors.primary` if that is all you need.

**Logo behavior:** if only `logo` is provided, it is used everywhere. If only `logoLight` is provided, it is used everywhere. Logo is injected into every slide as a small top-right element via a persistent HTML overlay; it does not cover content.

## CSS variables mapped from manifest

When a manifest is present, the generated Marp `<style>` block defines these mappings:

| Manifest field | CSS target |
|---|---|
| `colors.bg` | `section { background }` |
| `colors.fg` | `section { color }` |
| `colors.primary` | `h1, h2, h3`, `.stat`, `.card` border, `.callout` border, `blockquote` border |
| `colors.accent` | highlight elements |
| `colors.muted` | `.label`, captions (`color`) |
| `fonts.heading` | `h1, h2, h3 { font-family }` |
| `fonts.body` | `section { font-family }` |

## Resolution chain

The skill resolves the manifest in this order - first match wins:

1. `./brand.json` in the current working directory, or walk up parent directories toward the git root checking for `brand.json` or `.brand/brand.json` in each.
2. `~/.claude/brand/brand.json` (global default).
3. No manifest found - fall back to built-in defaults from `references/marp-style-guide.md`.

## Announcement

Before generating, the skill prints one line summarizing the resolved brand:

```
Brand: Acme Corp (from ./brand.json)
Brand: Acme Corp (from ./brand.json, defaults for: accent, fonts)
Brand: none (using default style guide)
```
