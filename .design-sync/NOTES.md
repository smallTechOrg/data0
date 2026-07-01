# Design-sync notes — data-analysis-agent

Repo-specific gotchas for future syncs.

## Shape / build

- This repo is a **Next.js app, not a component library** (`frontend/package.json`
  is `"private": true` with no `module`/`main`/`exports` entry). The converter
  therefore runs in **synth-entry mode** off `src/components`.
- A hand-written entry `frontend/.ds-entry.tsx` re-exports the scoped components
  so esbuild can bundle them into `window.DAA.*`. It is gitignored and NOT used by
  the Next app build. **If you re-scope, update both `.ds-entry.tsx` and
  `cfg.componentSrcMap`** (they must list the same components).
- `cfg.cssEntry` points at the **compiled app CSS** (`out/_next/static/css/<hash>.css`)
  so Tailwind utility classes are present. **The hash changes on every
  `next build`** — re-run `cd frontend && pnpm build` and update `cssEntry` to the
  new hash before re-syncing. (See Re-sync risks.)
- Build command: `node .ds-sync/package-build.mjs --config .design-sync/config.json
  --node-modules ./frontend/node_modules --entry ./frontend/.ds-entry.tsx --out ./ds-bundle`

## Scope decision (now 18 components)

- Original 7 presentational: StubBanner, ProgressBar, SuggestionChips, Markdown,
  ClarificationTurn, PromptBreakdown, StepsInspector.
- **Refactor (container/View split, committed to the app):** the data-bound
  components were split into a fetching container + a pure `<Name>View`. The Views
  are synced: TokenWidgetView, SessionSidebarView, TablesCardView,
  TableDescriptionPanelView, MemoryModalView, SettingsPanelView, CleanModalView,
  ConversationTurnView (extracted from ConversationCard). To re-sync these you need
  the View exports present — the split lives in the same source files.
- Already prop-driven, synced as-is: ERDiagramPanel, UploadCard.
- **Excluded:** AppShell / AnalyseTab / DatabaseTab (page-shell orchestration, not
  primitives). ChartRender now ships real ECharts — see Charts section.

## Charts — ECharts (migrated from Plotly)

- Charts were migrated from Plotly to **ECharts** (commit `36300f1`). The agent
  emits an ECharts `option` JSON via the sandbox `echart(...)` helper; `ChartRender`
  renders it with tree-shaken `echarts/core`.
- Tree-shaken ECharts is ~0.64 MB (vs Plotly's 9 MB bundled), so `ChartRender` and
  `ConversationTurnView` ship **real, working charts** in the design tool — no stub.
- The earlier plotly/jspdf stub (`.ds-bundle-tsconfig.json` + `.ds-stubs/`) was
  **removed**; `cfg.tsconfig` points back at the app `tsconfig.json`.
- `cssEntry` hash is `out/_next/static/css/cbefbef90cc26728.css` (rebuilt 2026-07-01 after adding the `dark:` variant + theming pass below; refresh on next rebuild).

## Known render warns

- `[FONT_MISSING] "Inter"` — the app loads Inter from an external CDN
  (`https://rsms.me/inter/inter.css` in `globals.css`), so no `@font-face` ships.
  Accepted the **system-font substitute** (the DS pane renders in system fonts).
  To fix faithfully: download Inter woff2 into the repo and wire `cfg.extraFonts`.

## Collapsible components

- PromptBreakdown and StepsInspector are collapsible and render **collapsed by
  default**. Their preview cards show only the collapsed toggle — the expanded
  bars/step-trace require a click, which a static capture can't do. Graded `good`
  as the honest default state; not a defect.

## Re-sync risks

- **`cssEntry` hash staleness** — the biggest one. A new `next build` changes the
  CSS filename; the old hash 404s and components ship unstyled. Always rebuild the
  frontend and refresh `cfg.cssEntry` first.
- **Inter font** is CDN-loaded and never bundled — previews will keep showing
  `[FONT_MISSING]` until someone wires `cfg.extraFonts`.
- The 18-component scope is deliberate (7 original + 9 View-split + ERDiagramPanel + UploadCard). Re-adding the 3 excluded page-shell components requires rethinking the sync surface.
- **globals.css**: `@theme` custom-var block was removed (2026-07-01); CSS output hash is stable (`e218add1...`). Standard Tailwind v4 palette applies via `@import "tailwindcss"`.

## Dark mode (2026-07-01)

- `globals.css` now declares `@custom-variant dark (&:where([data-theme="dark"], [data-theme="dark"] *));`
  — `dark:` classes activate when any ancestor (or the element itself) carries
  `data-theme="dark"`, not via `prefers-color-scheme`. No theme provider/wrapper
  needed; this is purely attribute-driven, consistent with the "no provider
  required" promise in `conventions.md`.
- All 18 synced components got a `dark:` pass (light surfaces → dark grays,
  pastel accent backgrounds → deep-shade equivalents; solid ≥400 accent
  fills/badges, focus rings, and intentionally-fixed-dark surfaces like code
  blocks were left unchanged — they already read fine on a dark page).
- **Known gap:** `ChartRender`'s ECharts canvas paints its own background
  (white) regardless of `data-theme` — only the surrounding wrapper got
  `dark:` classes. Theming the chart itself needs an ECharts `theme`/`option`
  switch keyed off `data-theme`, not just CSS — out of scope for this pass.
- This is a component **capability**, not a wired-up app feature — nothing in
  the real app currently sets `data-theme="dark"` on `<html>`/a parent (no
  toggle exists yet in `SettingsPanel`).

## Build-step override (2026-07-01)

- `.design-sync/overrides/css.mjs` forks `.ds-sync/lib/css.mjs` (see
  `cfg.libOverrides` in `config.json`) to post-process `_ds_bundle.css` after
  every build: strips the redundant `--tw-space-y-reverse:0` redeclaration
  Tailwind v4 puts inside every `:where(.space-y-*)` rule (registers it once
  under `:root` instead) and appends `/* @kind other */` after
  `--tw-border-style`, `--animate-spin`, `--animate-pulse`,
  `--default-transition-duration`, `--default-transition-timing-function` —
  Tailwind v4 internals the claude.ai/design token classifier flagged as
  unclassifiable. Needed every re-sync since `cfg.cssEntry` appends the
  *whole* compiled app CSS verbatim, so these always reappear after a rebuild.
