# Marp Style Guide

## Standard Front Matter

Every Marp deck must start with this front matter block. Copy it exactly - the CSS classes below depend on it.

```yaml
---
marp: true
theme: default
paginate: true
style: |
  section {
    font-family: 'Helvetica Neue', Arial, sans-serif;
  }
  section.lead {
    display: flex;
    flex-direction: column;
    justify-content: center;
    text-align: center;
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    color: white;
  }
  section.lead h1 {
    font-size: 2.5em;
    margin-bottom: 0.2em;
  }
  section.lead p {
    font-size: 1.2em;
    opacity: 0.85;
  }
  section.highlight {
    background: #f8f9fa;
  }
  .columns {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1.5em;
  }
  .columns-3 {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 1em;
  }
  .card {
    background: white;
    border-radius: 12px;
    padding: 1.2em;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    border-left: 4px solid #0f3460;
  }
  .stat {
    font-size: 2.5em;
    font-weight: bold;
    color: #0f3460;
  }
  .label {
    font-size: 0.9em;
    color: #666;
    margin-top: 0.2em;
  }
  .callout {
    background: #e8f4f8;
    border-left: 4px solid #0f3460;
    padding: 0.8em 1.2em;
    border-radius: 0 8px 8px 0;
    margin: 0.5em 0;
  }
  blockquote {
    border-left: 4px solid #0f3460;
    padding-left: 1em;
    color: #555;
    font-style: italic;
  }
---
```

## Slide Classes

### `lead` - Title and closing slides
Dark gradient background, centered white text. Use for the first and last slides.

```markdown
<!-- _class: lead -->

# Big Title Here

Subtitle or tagline
```

### `highlight` - Data or comparison slides
Light gray background. Use when a slide has cards, tables, or dense visual content.

```markdown
<!-- _class: highlight -->

## Comparison Title

[cards or table here]
```

### Default - Content slides
White background, left-aligned. Use for most content slides.

## Visual Components

### Two-column layout
```html
<div class="columns">
<div>

**Left column content**
- Point one
- Point two

</div>
<div>

**Right column content**
- Point three
- Point four

</div>
</div>
```

### Three-column layout
```html
<div class="columns-3">
<div class="card">Column 1</div>
<div class="card">Column 2</div>
<div class="card">Column 3</div>
</div>
```

### Stat cards
```html
<div class="columns">
<div class="card">
<div class="stat">42%</div>
<div class="label">Description of metric</div>
</div>
<div class="card">
<div class="stat">$1.2M</div>
<div class="label">Another metric</div>
</div>
</div>
```

### Callout box
```html
<div class="callout">
Key insight or important note goes here.
</div>
```

### Tables
Standard Markdown tables work well for comparisons:
```markdown
| Feature | Tool A | Tool B |
|---|---|---|
| Price | Free | $20/mo |
| Export | PDF, PPTX | PDF only |
```

## Content Guidelines

- **5-8 slides total.** If you need more, you're putting too much on each slide.
- **One idea per slide.** The slide title should name the idea.
- **15-second rule.** If you can't read a slide in 15 seconds, cut text.
- **Visual elements earn their place.** Use cards/columns when they aid comparison or scanning. Use plain bullets when the content is sequential or narrative.
- **No orphan slides.** Every slide should connect to the one before and after it.
