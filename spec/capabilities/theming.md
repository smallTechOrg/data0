# Capability: Theming — Dark/Light Toggle

## What It Does

Gives the app shell a single light/dark toggle. It is a pure client-side visual preference, applied instantly across the whole app via a CSS-variable remap of the existing Tailwind color classes, and persisted in `localStorage` so it survives a reload. No backend call, no LLM call, no new API key.

Accent color and layout density are **fixed product decisions, not user preferences** — indigo accent and compact density are hardcoded and cannot be changed from the UI. See "Fixed Values (not user-configurable)" below.

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| theme choice (`light` \| `dark`) | UI toggle click | the single control in `AppShell` header | yes |
| persisted theme (on load) | `localStorage` read | browser storage (`daa.theme` key only) | no (default applied if absent) |

## Outputs

| Output | Type | Destination |
|--------|------|-------------|
| `data-theme` attribute | DOM attribute on `<html>` | drives the CSS-variable remap in `globals.css` |
| `data-accent` attribute | DOM attribute on `<html>` | always `"blue"` (indigo) — see Fixed Values |
| `data-density` attribute | DOM attribute on `<html>` | always `"compact"` — see Fixed Values |
| `localStorage` entry | string | `daa.theme` key only (see Persistence Contract) |
| re-themed chart canvas | ECharts render | `ChartRender.tsx` — background/axis/legend/text colors follow the active theme |

## External Calls

None. This capability makes zero network calls and touches no backend route, no DB table, and no LLM provider.

## Business Rules

- **Attribute-driven, not `prefers-color-scheme`.** The active theme is whatever `data-theme` says; an explicit user choice always overrides the OS-level light/dark setting. The OS setting is used only as the very first default when nothing is in `localStorage` yet.
- **Explicit user choice wins and persists.** Once the user picks a theme, that choice is written to `localStorage` and re-applied on every subsequent load, regardless of OS setting changes.
- **No backend persistence.** Theme is NOT part of `SettingsData` (`frontend/src/lib/api.ts`) and is NEVER sent to `PATCH /settings` or stored in the `settings` SQLite table. That table remains scoped to `llm_model` / `max_iterations` / pricing (see [multi-provider-llm.md](multi-provider-llm.md)) — a deliberate decoupling: theming is a visual preference, not an agent-behavior setting.
- **CSS-variable remap, not per-component edits.** The ~18 design-synced components (`.design-sync/config.json` → `componentSrcMap`) keep their existing hardcoded Tailwind classes (`bg-white`, `text-gray-900`, etc.) untouched. Theming works by remapping those classes to CSS custom properties in ONE non-synced stylesheet, `frontend/src/app/globals.css` (confirmed not in `componentSrcMap`). A design-tool re-sync of any of the 18 components cannot clobber theming, because theming never touches their source.
- **Semantic variable roles, not a two-color swap.** The remap uses distinct variables per semantic role — surface, muted surface, border, primary text, muted text, plus the existing status tints (blue/green/amber/red) — because the live palette uses those tints meaningfully (e.g. `TablesCard.tsx` tints whole rows by dataset origin: uploaded = neutral, derived = green, stale = amber; `StubBanner.tsx`, `ClarificationTurn.tsx`, and error states use amber/red backgrounds semantically). Flattening everything to one "light"/"dark" pair would erase those semantics; each tint family gets its own light/dark pair of variables instead.
- **Chart canvas follows the theme (the one documented synced-file exception).** `ChartRender.tsx` is in `componentSrcMap`, so it is a synced file. `echarts.init(el)` renders into a plain `<canvas>` which has no CSS cascade — the wrapper `<div>` can be theme-aware via Tailwind classes, but the chart's own background, axis lines, tick labels, and legend text are baked into the ECharts `option`/theme at draw time and must be set programmatically. This capability makes a **minimal, localized, documented exception** to "don't edit synced files": `ChartRender.tsx` gains (a) a small helper that reads the active theme's CSS variable values via `getComputedStyle(document.documentElement)`, (b) passes them into `echarts.init(el, undefined, {...})` or via a `chart.setOption({backgroundColor, textStyle, legend:{textStyle}, ...})` merge, and (c) a listener (a `MutationObserver` on `document.documentElement`'s `data-theme` attribute, or a re-render triggered by the same theme-context the controls use) that re-applies those colors and calls `chart.setOption(...)` again when the user flips the theme while a chart is already on screen. The chart's PNG/JPEG `getDataURL()` exports and the clipboard-copy path (`downloadImage`, `copyPng`) drop their hardcoded `backgroundColor: '#fff'` and instead pass the current theme's surface color, so an exported/copied chart image matches what's on screen instead of always being forced to white.
- **Brief flash-of-wrong-theme on first load is accepted, not engineered away.** The theme is applied via a `useEffect` in `AppShell.tsx` on mount, which reads `localStorage` and sets the `data-theme` attribute (plus the fixed `data-accent`/`data-density` attributes) before the rest of the tree paints its colors. This means there can be a very brief (sub-frame-to-single-frame) flash on a hard reload before the effect runs, because Next.js's static export cannot embed a pre-paint inline script without extra build wiring. This is accepted as a deliberate scope decision — eliminating it entirely (e.g. via a blocking inline `<script>` in `layout.tsx` that runs before hydration) is easy to add later if it proves visually annoying, but is not required for this capability to be considered done.
- **Default when nothing is persisted:** theme = `light` — matching the app's current (untheming) look, so a first-time user with no `localStorage` entry sees the identical UI as before this capability shipped.

## Fixed Values (not user-configurable)

Accent color and density were originally scoped as a 4-swatch picker and a 3-step picker respectively (see history below), but were pinned to permanent fixed values during Phase 7 polish and are **not** exposed as UI controls:

- **Accent = `blue` (indigo) — permanent.** `DEFAULT_ACCENT` in `frontend/src/lib/theme.ts` is hardcoded to `'blue'`. There is no accent-swatch UI anywhere in the app.
- **Density = `compact` — permanent.** `DEFAULT_DENSITY` in `frontend/src/lib/theme.ts` is hardcoded to `'compact'`. There is no density-picker UI anywhere in the app.
- **`readStoredPrefs()` ignores any stored `accent`/`density` value.** Even if a `daa.accent` or `daa.density` key exists in `localStorage` from an earlier build (or is manually set), `readStoredPrefs()` always returns the fixed defaults for both — only `daa.theme` is actually read back from storage. This is intentional and covered by a dedicated test (`theme.test.ts`: "readStoredPrefs pins accent/density to their defaults regardless of any stored value — there is no picker for either").
- **The `data-accent`/`data-density` attribute contract is retained internally** (both attributes are still applied to `<html>`, always with their fixed values) so `globals.css`'s CSS-variable remap and `ChartRender.tsx`'s theme-read helper don't need to special-case "no accent/density system" — they simply always see the one fixed value. This is an implementation-continuity detail, not a user-facing feature.
- **Rationale:** the accent/density picker surface added visual-QA and CSS-variable-remap complexity (a 4×3 combinatorial space against the ~18 synced components' hardcoded classes) without a clear user need once the indigo/compact combination was settled on as the app's identity. Removing the picker UI (while keeping the underlying attribute plumbing) shipped a tighter, less error-prone control surface without touching the remap mechanism itself.

## Concrete Remap (grounded in the live component tree)

A grep of `frontend/src/components/**/*.tsx` (347 hits across 22 files) shows the real palette in active use. The remap table below maps each hardcoded class family to a CSS custom property, defined once per `data-theme` value in `globals.css`:

| Tailwind class(es) found in components | CSS variable | Light value (unchanged default) | Dark value |
|---|---|---|---|
| `bg-white` | `--surface` | `#ffffff` | `#111827` (gray-900) |
| `bg-gray-50` | `--surface-muted` | `#f9fafb` | `#1a2233` |
| `bg-gray-100` | `--surface-muted-2` | `#f3f4f6` | `#232b3d` |
| `text-gray-900`, `text-gray-800` | `--text` | `#111827` / `#1f2937` | `#e5e7eb` |
| `text-gray-700`, `text-gray-600` | `--text-secondary` | `#374151` / `#4b5563` | `#9ca3af` |
| `text-gray-500`, `text-gray-400`, `text-gray-300` | `--text-muted` | `#6b7280` / `#9ca3af` / `#d1d5db` | `#6b7280` |
| `border-gray-200`, `border-gray-100`, `border-gray-300` | `--border` | `#e5e7eb` / `#f3f4f6` / `#d1d5db` | `#2a3549` |
| `bg-indigo-900` (header), `text-indigo-200`, `text-indigo-600`, `bg-indigo-100`/`text-indigo-700` | `--accent`, `--accent-fg`, `--accent-soft`, `--accent-soft-fg` | indigo shades | `color-mix()`'d accent shades — header bar stays a solid deep accent tone in both themes |
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

## The One Control

- **Theme toggle** (light/dark) — a single small icon button (sun/moon), `<ThemeControls>`, rendered directly in `AppShell.tsx`'s header, in the right-hand control cluster next to the existing "Live" badge and "📝 Project notes" button (the natural home: that cluster is already the header's utility-control area, and `AppShell.tsx` is confirmed NOT design-synced, so it is safe to extend freely). It is `aria-pressed` on dark/light state and titled "Switch to light/dark mode".

`ThemeControls.tsx` renders ONLY this one button — there is no accent swatch UI and no density segmented control anywhere in the file or the app (see Fixed Values above for why).

`SettingsPanel.tsx` (the existing LLM-model/pricing modal) is explicitly NOT used for this control — it is a design-synced file scoped to backend-persisted agent settings, and mixing in a client-only visual pref there would blur that boundary and risk sync clobber.

## Persistence Contract

- `localStorage` key: `daa.theme` (`"light"` | `"dark"`) — the ONLY key actually read back by `readStoredPrefs()`.
- The legacy `daa.accent` / `daa.density` `localStorage` keys are still *writable* via the generic `storePref()` helper (kept for internal/test symmetry) but are never *read* — `readStoredPrefs()` always returns the fixed `DEFAULT_ACCENT`/`DEFAULT_DENSITY` regardless of what (if anything) is stored under those keys.
- `frontend/src/lib/theme.ts` (non-synced) owns reading/writing `localStorage` and applying `data-theme`/`data-accent`/`data-density` to `document.documentElement`. `ThemeControls.tsx` and `ChartRender.tsx`'s theme-listener both consume it.
- Applied once on mount in `AppShell.tsx`'s effect before the rest of the tree's first paint call completes on the client; see the flash-of-wrong-theme note above for the accepted limitation.

## Scope Boundaries

**In scope:** the light/dark toggle; the global CSS-variable remap covering every hardcoded color class actually found in the grep above; `localStorage` persistence of the theme choice; the `data-theme`/`data-accent`/`data-density` attribute contract (the latter two always fixed values); making `ChartRender.tsx`'s on-screen canvas and its PNG/JPEG export/copy follow the active theme.

**Explicitly deferred / out of scope for this capability:**
- Eliminating the first-load flash via a pre-hydration inline script — noted as a future enhancement, not required now.
- Any new backend field, migration, or `/settings` change — theming is 100% client-side.
- Per-user or per-session theme (single local user; one `localStorage` = one preference set, matching every other client-only preference in this app, e.g. `sessionStorage` collapse-state in C32).
- Redesigning any synced component's markup/structure — only the one documented `ChartRender.tsx` exception (theme-aware chart colors + export background) is touched; its layout, props, and behavior are otherwise unchanged.
- **Any user-facing accent or density picker.** These were built and then explicitly removed (see Fixed Values above); reintroducing either as a live control would be a new, separately-scoped capability, not a completion of this one.

## Success Criteria

- [ ] Clicking the theme toggle flips `data-theme` on `<html>` and every card/panel/header visibly changes from the light to the dark palette (backgrounds, text, borders) with no unstyled/blank regions.
- [ ] Reloading the page after toggling to dark shows dark mode again (read back from `localStorage`) without the user re-toggling.
- [ ] The header's accent chrome (bar, primary buttons, active tab, "Live" badge) always renders in the fixed indigo/blue accent, and derived/stale/error tint colors (green/amber/red) are unaffected by anything — there is no control that changes accent.
- [ ] Spacing on the Tables card rows and the conversation thread always renders at the fixed compact density — there is no control that changes it.
- [ ] With a chart on screen, toggling the theme re-renders the chart's background/axis/legend/text colors to match the new theme (verified visually — the chart canvas is no longer a fixed white square in dark mode).
- [ ] Exporting a chart as PNG/JPEG (or copying it) after switching to dark mode produces an image whose background matches the current theme, not a hardcoded white.
- [ ] No design-synced component's source file is modified to add theming, except the one documented, minimal `ChartRender.tsx` change described above.
- [ ] `frontend/src/lib/api.ts`'s `SettingsData` interface and the `/settings` backend route are unchanged by this capability — confirmed by diff.
- [ ] Setting `daa.accent`/`daa.density` directly in `localStorage` (e.g. via devtools) has no visible effect after a reload — `readStoredPrefs()` still returns the fixed `blue`/`compact` defaults, confirming there is no way (UI or storage tampering) to change either.
