# Data Analysis Agent — UI components

React components from the **Data Analysis Agent** web app (a local tool: upload
data, ask questions in plain English, get explainable answers). This library is
the **prop-driven, presentational** surface of the app: the original presentational
components plus `…View` primitives extracted from the data-bound components (their
containers keep the fetching; the `…View`s hold the markup and take data via props).

## Setup / wrapping

- **No provider or theme wrapper is required.** Every component renders standalone
  from its props. Import and render directly.
- All components are React client components — render in a browser/client context.
- Each component's API is its `<Name>.d.ts` (`<Name>Props`). Read it before
  composing — props are the only configuration surface. The `…View` components are
  pure: pass them data + `on*` callbacks.

## Styling idiom — Tailwind utility classes (with one caveat)

Components are styled with **Tailwind CSS utility classes** baked into their markup.
The shipped `styles.css` carries the **compiled subset of Tailwind these components
use** — NOT a full Tailwind build.

- Components render fully styled out of the box.
- **Caveat for your own layout glue:** an arbitrary Tailwind class you invent may
  not exist in the shipped CSS and can render unstyled. Prefer **inline `style={{…}}`**
  for your own wrappers, or reuse the components' class vocabulary: `flex`,
  `items-center`, `justify-between`, `gap-*`, `rounded-md`/`rounded-full`, `border`,
  `px-*`/`py-*`, `text-xs`/`text-sm`, `font-medium`/`font-semibold`, and the gray /
  blue / amber / green / rose palette.

## Where the truth lives

- Component APIs: `components/<group>/<Name>/<Name>.d.ts`.
- Styles: `styles.css` and its `@import` closure (`_ds_bundle.css`).
- Per-component usage: `components/<group>/<Name>/<Name>.prompt.md`.

## Components

**Answer / conversation:**
- `Markdown` — renders an answer's markdown (GFM tables/lists).
- `ConversationTurnView` — a full Q&A turn: question, markdown answer, steps,
  suggestion chips, token breakdown. (Charts are stubbed in this bundle — pass a
  turn without `charts`; chart rendering needs the live app's plotly.)
- `SuggestionChips` — follow-up chips. `ClarificationTurn` — amber "agent asks".
- `StepsInspector` / `PromptBreakdown` — collapsible widgets (render collapsed).
- `ProgressBar` — live agent progress. `StubBanner` — offline-mode banner.

**Data / sidebar panels (extracted `…View`s — pass data via props):**
- `TokenWidgetView` — token-usage + cost panel.
- `SessionSidebarView` — conversation session list.
- `TablesCardView` — datasets/tables list with filters + actions.
- `TableDescriptionPanelView` — one dataset's schema, keys, notes, preview.
- `ERDiagramPanel` — ER diagram of datasets with inferred FK edges.
- `UploadCard` — file drop zone.

**Modals (`…View`s — render with `open`/data props):**
- `MemoryModalView`, `SettingsPanelView`, `CleanModalView`.

## One idiomatic build snippet

```tsx
import { ConversationTurnView, SuggestionChips } from 'agent-frontend'

function AnswerPanel({ turn }) {
  return (
    <div style={{ maxWidth: 720, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <ConversationTurnView turn={turn} expanded collapsible
        onToggle={() => {}} onResubmitClarification={() => {}} busy={false} />
    </div>
  )
}
```
