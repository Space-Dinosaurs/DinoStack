# Brand Manifest Schema

Place a `brand.json` file in your project directory (or at `~/.claude/brand/brand.json` for a global default) to apply your company's colors, fonts, logo, and footer to generated videos automatically.

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
| `colors.primary` | string (hex) | Main brand color. Used for headings, accent borders, bullet markers. |
| `colors.accent` | string (hex) | Secondary color. Used for highlights. If absent, the skill may derive one or fall back to the built-in default. |
| `colors.bg` | string (hex) | Slide background color. |
| `colors.fg` | string (hex) | Primary text color. |
| `colors.muted` | string (hex) | Secondary/muted text color (captions, source lines). |
| `fonts.heading` | string | Font family for headings. Must be available on the render machine or loaded via CSS. |
| `fonts.body` | string | Font family for body text. |
| `logo` | string (path) | Path to a logo file - default version (suitable for light or dark backgrounds). |
| `logoLight` | string (path) | Path to a logo optimized for dark backgrounds. Used on dark slides (intro/outro). If absent, `logo` is used instead. |
| `footer` | string | Footer text injected on every slide. |

## Rules

**All asset paths are relative to the manifest file itself, not to the current working directory.** This makes brand kits portable - zip the directory containing `brand.json` and its assets and share it; the paths stay correct.

**All fields are optional.** Any missing field falls back to the skill's built-in defaults. You can provide just `colors.primary` if that is all you need.

**Logo behavior:** if only `logo` is provided, it is used everywhere. If only `logoLight` is provided, it is used everywhere. The skill copies resolved logo files into `~/remotion-slides/public/` before rendering and references them via `staticFile()`.

## Resolution chain

The skill resolves the manifest in this order - first match wins:

1. `./brand.json` in the current working directory, or walk up parent directories toward the git root checking for `brand.json` or `.brand/brand.json` in each.
2. `~/.claude/brand/brand.json` (global default).
3. No manifest found - fall back to built-in defaults.

## Announcement

Before generating, the skill prints one line summarizing the resolved brand:

```
Brand: Acme Corp (from ./brand.json)
Brand: Acme Corp (from ./brand.json, defaults for: accent, fonts)
Brand: none (using default style guide)
```
