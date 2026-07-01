# Capability: Theming — Dark/Light + Accent + Density

## What It Does

Gives the app shell a light/dark toggle, an accent-color picker, and a density (spacing) setting. All three are pure client-side visual preferences, applied instantly across the whole app via a CSS-variable remap of the existing Tailwind color classes, and persisted in `localStorage` so they survive a reload. No backend call, no LLM call, no new API key.

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| theme choice (`light` \| `dark`) | UI toggle click | new controls in `AppShell` header | yes |
| accent choice (`blue` \| `purple` \| `green` \| `orange`) | UI picker click | new controls in `AppShell` header | yes |
| density choice (`compact` \| `comfortable` \| `spacious`) | UI picker click | new controls in `AppShell` header | yes |
| persisted preference (on load) | `localStorage` read | browser storage | no (defaults applied if absent) |

## Outputs

| Output | Type | Destination |
|--------|------|-------------|
| `data-theme` attribute | DOM attribute on `<html>` | drives the CSS-variable remap in `globals.css` |
| `data-accent` attribute | DOM attribute on `<html>` | selects the accent hue used by `color-mix()` |
| `data-density` attribute | DOM attribute on `<html>` | selects the spacing-scale CSS variables |
| `localStorage` entries | string | `daa.theme`, `daa.accent`, `daa.density` keys |
| re-themed chart canvas | ECharts render | `ChartRender.tsx` — background/axis/legend/text colors follow the active theme |

## External Calls

None. This capability makes zero network calls and touches no backend route, no DB table, and no LLM provider.

## Business Rules

- **Attribute-driven, not `prefers-color-scheme`.** The active theme is whatever `data-theme` says; an explicit user choice always overrides the OS-level light/dark setting. The OS setting is used only as the very first default when nothing is in `localStorage` yet.
- **Explicit user choice wins and persists.** Once the user picks a theme/accent/density, that choice is written to `localStorage` and re-applied on every subsequent load, regardless of OS setting changes.
- **No backend persistence.** Theme/accent/density are NOT part of `SettingsData` (`frontend/src/lib/api.ts`) and are NEVER sent to `PATCH /settings` or stored in the `settings` SQLite table. That table remains scoped to `llm_model` / `max_iterations` / pricing (see [multi-provider-llm.md](multi-provider-llm.md)) — a deliberate decoupling: theming is a visual preference, not an agent-behavior setting.
- **CSS-variable remap, not per-component edits.** The ~18 design-synced components (`.design-sync/config.json` → `componentSrcMap`) keep their existing hardcoded Tailwind classes (`bg-white`, `text-gray-900`, etc.) untouched. Theming works by remapping those classes to CSS custom properties in ONE non-synced stylesheet, `frontend/src/app/globals.css` (confirmed not in `componentSrcMap`). A design-tool re-sync of any of the 18 components cannot clobber theming, because theming never touches their source.
- **Semantic variable roles, not a two-color swap.** The remap uses distinct variables per semantic role — surface, muted surface, border, primary text, muted text, plus the existing status tints (blue/green/amber/red) — because the live palette uses those tints meaningfully (e.g. `TablesCard.tsx` tints whole rows by dataset origin: uploaded = neutral, derived = green, stale = amber; `StubBanner.tsx`, `ClarificationTurn.tsx`, and error states use amber/red backgrounds semantically). Flattening everything to one "light"/"dark" pair would erase those semantics; each tint family gets its own light/dark pair of variables instead.
- **Accent is decorative only.** The accent picker recolors indigo/blue brand chrome (header bar, primary buttons, active tab, "Live" badge) via `color-mix()` against the chosen hue; it does not touch the green/amber/red status-semantic colors used for derived/stale/error states.
- **Density scales spacing only.** Compact/Comfortable/Spacious scale a small set of spacing custom properties (padding/gap on cards, rows, and the conversation thread); it does not change font sizes, colors, or layout structure.
- **Chart canvas follows the theme (the one documented synced-file exception).** `ChartRender.tsx` is in `componentSrcMap`, so it is a synced file. `echarts.init(el)` renders into a plain `<canvas>` which has no CSS cascade — the wrapper `<div>` can be theme-aware via Tailwind classes, but the chart's own background, axis lines, tick labels, and legend text are baked into the ECharts `option`/theme at draw time and must be set programmatically. This capability makes a **minimal, localized, documented exception** to "don't edit synced files": `ChartRender.tsx` gains (a) a small helper that reads the active theme's CSS variable values via `getComputedStyle(document.documElement)`, (b) passes them into `echarts.init(el, undefined, {...})` or via a `chart.setOption({backgroundColor, textStyle, legend:{textStyle}, ...})` merge, and (c) a listener (a `MutationObserver` on `document.documentElement`'s `data-theme` attribute, or a re-render triggered by the same theme-context the controls use) that re-applies those colors and calls `chart.setOption(...)` again when the user flips the theme while a chart is already on screen. The chart's PNG/JPEG `getDataURL()` exports and the clipboard-copy path (`downloadImage`, `copyPng`) drop their hardcoded `backgroundColor: '#fff'` and instead pass the current theme's surface color, so an exported/copied chart image matches what's on screen instead of always being forced to white.
- **Brief flash-of-wrong-theme on first load is accepted, not engineered away.** The theme is applied via a `useEffect` in a small client-side theme-provider/hook on mount, which reads `localStorage` and sets the `data-theme`/`data-accent`/`data-density` attributes before the rest of the tree paints its colors. This means there can be a very brief (sub-frame-to-single-frame) flash on a hard reload before the effect runs, because Next.js's static export cannot embed a pre-paint inline script without extra build wiring. This is accepted as a deliberate scope decision — eliminating it entirely (e.g. via a blocking inline `<script>` in `layout.tsx` that runs before hydration) is easy to add later if it proves visually annoying, but is not required for this capability to be considered done.
- **Defaults when nothing is persisted:** theme = `light`, accent = `blue`, density = `comfortable` — matching the app's current (untheming) look exactly, so a first-time user with no `localStorage` entry sees the identical UI as before this capability shipped.

## Concrete Remap (grounded in the live component tree)

A grep of `frontend/src/components/**/*.tsx` (347 hits across 22 files, this conversation) shows the real palette in active use. The remap table below maps each hardcoded class family to a CSS custom property, defined once per `data-theme` value in `globals.css`:

| Tailwind class(es) found in components | CSS variable | Light value (unchanged default) | Dark value |
|---|---|---|---|
| `bg-white` | `--surface` | `#ffffff` | `#111827` (gray-900) |
| `bg-gray-50` | `--surface-muted` | `#f9fafb` | `#1a2233` |
| `bg-gray-100` | `--surface-muted-2` | `#f3f4f6` | `#232b3d` |
| `text-gray-900`, `text-gray-800` | `--text` | `#111827` / `#1f2937` | `#e5e7eb` |
| `text-gray-700`, `text-gray-600` | `--text-secondary` | `#374151` / `#4b5563` | `#9ca3af` |
| `text-gray-500`, `text-gray-400`, `text-gray-300` | `--text-muted` | `#6b7280` / `#9ca3af` / `#d1d5db` | `#6b7280` |
| `border-gray-200`, `border-gray-100`, `border-gray-300` | `--border` | `#e5e7eb` / `#f3f4f6` / `#d1d5db` | `#2a3549` |
| `bg-indigo-900` (header), `text-indigo-200`, `text-indigo-600`, `bg-indigo-100`/`text-indigo-700` | `--accent`, `--accent-fg`, `--accent-soft`, `--accent-soft-fg` | indigo shades | `color-mix()`'d accent shades (see Accent below) — header bar stays a solid deep accent tone in both themes |
| `bg-blue-*`/`text-blue-*`/`border-blue-*` (buttons, links, "Selected"/"Live" chips, suggestion chips) | same `--accent*` family as above | blue shades | accent-mixed, slightly desaturated for dark |
| `bg-green-*`/`text-green-*`/`border-green-*` (derived-dataset tint, success states) | `--tint-success`, `--tint-success-fg`, `--tint-success-border` | green-50/100/700 | dark-mode green (desaturated, darker surface) |
| `bg-amber-*`/`text-amber-*`/`border-amber-*` (stale-dataset tint, clarification turns, stub banner, warnings) | `--tint-warning`, `--tint-warning-fg`, `--tint-warning-border` | amber-50/100/700/800/900 | dark-mode amber |
| `bg-red-*`/`text-red-*`/`border-red-*` (errors, delete-confirm, failed runs) | `--tint-danger`, `--tint-danger-fg`, `--tint-danger-border` | red-50/100/700 | dark-mode red |
| `bg-yellow-*` (StubBanner only) | `--tint-stub`, `--tint-stub-fg` | yellow-100/200/900 | dark-mode yellow |
| `bg-gray-900`/`text-gray-100` (code blocks in `Markdown.tsx`, `StepsInspector.tsx`) | `--code-surface`, `--code-text` | near-black / near-white (already dark-styled in light mode — a deliberate always-dark code block) | unchanged — code blocks stay dark in both themes for contrast |
| `bg-black` (modal overlays, `MemoryModal.tsx`/`SettingsPanel.tsx`/`CleanModal.tsx`) | `--overlay` | `rgb(0 0 0 / 0.4)` | `rgb(0 0 0 / 0.6)` |

The remap is implemented as CSS selectors that match Tailwind's generated utility classes and override their declaration with a `var(--*)`, e.g.:

```css
[data-theme] .bg-white { background-color: var(--surface); }
[data-theme] .bg-gray-50 { background-color: var(--surface-muted); }
[data-theme] .text-gray-900 { color: var(--text); }
[data-theme] .border-gray-200 { border-color: var(--border); }
[data-theme] .bg-amber-50 { background-color: var(--tint-warning); }
/* ...one rule per class family in the table above */
```

No `!important` is required in practice (Tailwind v4 utility specificity is low and these selectors are written to match or exceed it), but a `!important` fallback per rule is an acceptable escape hatch if a specific class collides with a more specific component override — call sites should be checked visually at build time, not assumed.

## The Three Controls

- **Theme toggle** (light/dark) — a small icon button (sun/moon) rendered directly in `AppShell.tsx`'s header, in the right-hand control cluster next to the existing "Live" badge and "📝 Project notes" button (the natural home: that cluster is already the header's utility-control area, and `AppShell.tsx` is confirmed NOT design-synced, so it is safe to extend freely).
- **Accent picker** — four small color swatches (blue/purple/green/orange) in a `<div role="radiogroup">`, rendered next to the theme toggle in the same header cluster.
- **Density picker** — a 3-option segmented control (Compact/Comfortable/Spacious) in the same cluster.

All three controls live in **one new small non-synced component**, `frontend/src/components/ThemeControls.tsx`, rendered by `AppShell.tsx` (not inlined directly in `AppShell.tsx`, to keep the header's JSX from ballooning, but still non-synced and owned entirely by this capability). `SettingsPanel.tsx` (the existing LLM-model/pricing modal) is explicitly NOT used for these controls — it is a design-synced file scoped to backend-persisted agent settings, and mixing in client-only visual prefs there would blur that boundary and risk sync clobber.

## Persistence Contract

- `localStorage` keys: `daa.theme` (`"light"` | `"dark"`), `daa.accent` (`"blue"` | `"purple"` | `"green"` | `"orange"`), `daa.density` (`"compact"` | `"comfortable"` | `"spacious"`).
- A small client-side hook/module (`frontend/src/lib/theme.ts`, new, non-synced) owns reading/writing these keys and applying `data-theme`/`data-accent`/`data-density` to `document.documentElement`. `ThemeControls.tsx` and `ChartRender.tsx`'s theme-listener both consume it.
- Applied once on mount (in `AppShell.tsx` or a thin provider it renders) before the rest of the tree's first paint call completes on the client; see the flash-of-wrong-theme note above for the accepted limitation.

## Scope Boundaries

**In scope:** the light/dark toggle, the 4-color accent picker, the 3-step density picker; the global CSS-variable remap covering every hardcoded color class actually found in the grep above; `localStorage` persistence; the `data-theme`/`data-accent`/`data-density` attribute contract; making `ChartRender.tsx`'s on-screen canvas and its PNG/JPEG export/copy follow the active theme.

**Explicitly deferred / out of scope for this capability:**
- Eliminating the first-load flash via a pre-hydration inline script — noted as a future enhancement, not required now.
- Any new backend field, migration, or `/settings` change — theming is 100% client-side.
- Per-user or per-session theme (single local user; one `localStorage` = one preference set, matching every other client-only preference in this app, e.g. `sessionStorage` collapse-state in C32).
- Redesigning any synced component's markup/structure — only the one documented `ChartRender.tsx` exception (theme-aware chart colors + export background) is touched; its layout, props, and behavior are otherwise unchanged.
- A live design-tool "theme" concept beyond this one flat light/dark + 4 accents + 3 densities — no custom color picker beyond the 4 preset swatches.

## Success Criteria

- [ ] Clicking the theme toggle flips `data-theme` on `<html>` and every card/panel/header visibly changes from the light to the dark palette (backgrounds, text, borders) with no unstyled/blank regions.
- [ ] Reloading the page after toggling to dark shows dark mode again (read back from `localStorage`) without the user re-toggling.
- [ ] Changing the accent recolors the header bar, primary buttons, and active-tab/Live-badge chrome, while derived/stale/error tint colors (green/amber/red) are visibly unaffected.
- [ ] Changing density visibly changes spacing (padding/gaps) on at least the Tables card rows and the conversation thread, without changing font size or breaking layout.
- [ ] With a chart on screen, toggling the theme re-renders the chart's background/axis/legend/text colors to match the new theme (verified visually — the chart canvas is no longer a fixed white square in dark mode).
- [ ] Exporting a chart as PNG/JPEG (or copying it) after switching to dark mode produces an image whose background matches the current theme, not a hardcoded white.
- [ ] No design-synced component's source file is modified to add theming, except the one documented, minimal `ChartRender.tsx` change described above.
- [ ] `frontend/src/lib/api.ts`'s `SettingsData` interface and the `/settings` backend route are unchanged by this capability — confirmed by diff.
