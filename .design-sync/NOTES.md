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

## Scope decision

- Synced the **7 presentational components** only: StubBanner, ProgressBar,
  SuggestionChips, Markdown, ClarificationTurn, PromptBreakdown, StepsInspector.
- The other 14 components were excluded because they **fetch from the backend on
  mount** (TokenWidget, SessionSidebar, TablesCard, ConversationCard, DatabaseTab,
  MemoryModal, SettingsPanel, UploadCard, AppShell, AnalyseTab, ChartRender,
  CleanModal, ERDiagramPanel, TableDescriptionPanel) and cannot render standalone
  in the design tool. ChartRender also pulls in plotly.js (~9 MB bundle, over the
  5 MB upload cap).

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
- The 7-component scope is deliberate; re-adding any of the 14 backend-coupled
  components requires authoring previews with mocked data/providers (they won't
  render from props alone).
