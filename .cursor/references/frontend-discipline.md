<!--
Purpose: Defines the FE-discipline rule set for the agentic engineering
         methodology. Engineers apply these rules when a diff touches FE files;
         Skeptics cite these sections when raising FE-discipline findings.

Public API: Referenced by section number from content/agents/engineer.md and
            from the FE-discipline findings table in
            content/references/skeptic-protocol.md.

Upstream deps: None (standalone reference document).

Downstream consumers: content/agents/engineer.md (## Front-end discipline),
                      content/references/skeptic-protocol.md
                      (### FE-discipline findings)

Failure modes: If sections are renumbered or removed, Skeptic finding citations
               become invalid. Section headings are cross-referenced by name -
               rename carefully and update all citation sites.

Performance: N/A - methodology document consumed by LLMs at spawn time.
-->
# Front-End Discipline Reference

Rules applied when a diff touches files matching the FE-glob defined in
`content/agents/engineer.md`. Skeptic findings MUST cite both the file:line and
the section below that the finding maps to; findings missing either citation are
invalid.

---

## 1. Semantic HTML

Use native HTML elements that carry the correct semantics for their role.
Heading levels (`h1`-`h6`) must reflect document hierarchy, not visual size.
Landmark regions (`header`, `nav`, `main`, `footer`, `aside`) should frame the
page structure. Interactive triggers use `<button>` for actions that do not
navigate, and `<a href>` for navigation to a URL.

**Violation example:**
```tsx
// Wrong - div with click handler has no semantics, role, or keyboard support
<div onClick={handleSubmit}>Submit</div>

// Correct
<button onClick={handleSubmit}>Submit</button>
```

---

## 2. ARIA

ARIA is an escape hatch for cases where native HTML semantics are insufficient.
Do not add ARIA attributes to elements that already carry the needed role
natively - the redundancy creates noise for assistive technology and is often
wrong. `role="presentation"` must never appear on focusable elements because it
removes all keyboard and AT interaction from the element.

**Violation example:**
```tsx
// Wrong - button already has role=button; aria-label is also redundant here
<button role="button" aria-label="Click">Click</button>

// Wrong - removes AT semantics from a focusable element
<a href="/about" role="presentation">About</a>

// Correct
<button onClick={handler}>Click</button>
```

---

## 3. Keyboard support

Every interactive element must be reachable and operable by keyboard alone.
Non-native-interactive elements that receive `onClick` must also carry
`tabIndex={0}` (or equivalent) and an `onKeyDown` handler that triggers the
action on Enter/Space. The focus indicator must be visible; removing the
browser default outline without a replacement is a violation.

**Violation examples:**
```tsx
// Wrong - not keyboard-reachable and no key handler
<div onClick={toggle}>Toggle panel</div>

// Correct
<div
  role="button"
  tabIndex={0}
  onClick={toggle}
  onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && toggle()}
>
  Toggle panel
</div>
```

```css
/* Wrong - removes focus ring with no replacement */
* { outline: none; }

/* Correct - replace, don't remove */
*:focus-visible { outline: 2px solid var(--color-focus-ring); }
```

---

## 4. Focus management

When a modal, drawer, dialog, or popover-style overlay opens, focus must move
into it and be trapped there - Tab and Shift-Tab must not reach elements behind
the overlay while it is open. When the overlay closes, focus must return to the
element that triggered it.

**Violation example:**
```tsx
// Wrong - modal renders but Tab still cycles through the background page
function Modal({ onClose }) {
  return (
    <div className="modal">
      <button onClick={onClose}>Close</button>
      <input placeholder="Name" />
    </div>
  );
  // Missing: focus trap (e.g. focus-trap-react, aria-modal, or manual management)
  // Missing: restore focus to trigger element on close
}
```

---

## 5. Reduced motion

Any CSS animation, transition, or scroll effect must be guarded by the
`prefers-reduced-motion: reduce` media query so users who have requested reduced
motion are not exposed to motion that can cause discomfort or vestibular
disruption. JavaScript-driven animations must read the media query value before
running.

**Violation examples:**
```css
/* Wrong - no reduced-motion guard */
.card:hover {
  transform: translateY(-4px);
  transition: transform 0.3s ease;
}

/* Correct */
.card:hover {
  transform: translateY(-4px);
  transition: transform 0.3s ease;
}
@media (prefers-reduced-motion: reduce) {
  .card:hover { transform: none; transition: none; }
}
```

```tsx
// Wrong - parallax with no motion check
<div style={{ transform: `translateY(${scrollY * 0.5}px)` }}>Hero</div>

// Correct
const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
<div style={{ transform: prefersReduced ? 'none' : `translateY(${scrollY * 0.5}px)` }}>
  Hero
</div>
```

---

## 6. Design tokens

In a codebase where a token system is detected (see heuristics below), do not
hardcode color, spacing, or font values when an equivalent token exists. Use the
token instead. This keeps the UI consistent and makes theme changes tractable.

**Token-system detection heuristics (any one triggers "token system present"):**

- **(a)** `tailwind.config.{ts,js,mjs,cjs}` exists at the repo root AND contains
  a `theme.extend` block with `colors` or `spacing`.
- **(b)** Any CSS file (per FE-glob) contains `:root` with at least two
  `--`-prefixed custom properties that are used elsewhere in the codebase.
- **(c)** A `tokens.{ts,js,json}` or `design-tokens.{ts,js,json}` file at the
  repo root.
- **(d)** A `theme.{ts,js}` or `themes/` directory exporting an object literal.

The Skeptic finding `hardcoded-token-instead-of-design-token` MUST cite which
heuristic ((a), (b), (c), or (d)) triggered detection. A finding that omits the
heuristic citation is invalid.

**Violation example:**
```tsx
// Wrong - hardcoded hex in a Tailwind codebase that defines colors.primary
<div style={{ color: '#3b82f6', padding: '16px' }}>Content</div>

// Correct (Tailwind token)
<div className="text-primary p-4">Content</div>
```

---

## 7. Responsive patterns

Do not use fixed-width containers without a responsive override when the surface
is expected to work across multiple breakpoints. Fixed widths silently break
layouts on narrow viewports and are almost always unintentional on surfaces that
are otherwise responsive.

**Violation example:**
```tsx
// Wrong - fixed width with no responsive variant on a multi-breakpoint surface
<div className="w-[500px]">Sidebar</div>

// Correct
<div className="w-full sm:w-[500px]">Sidebar</div>
// or use a responsive utility class appropriate for the design
```
