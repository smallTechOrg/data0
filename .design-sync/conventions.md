# Data Analysis Agent — UI components

These are React components extracted from the **Data Analysis Agent** web app
(a local tool: upload data, ask questions in plain English, get explainable
answers). This sync covers the **presentational** subset — components that render
from props alone. The app's data-bound components (upload, tables, sessions,
conversation, token usage, database tab) are intentionally **not** included
because they fetch from the app's backend on mount.

## Setup / wrapping

- **No provider or theme wrapper is required.** Every component here renders
  standalone from its props. Import and render directly.
- All components are React client components — render them in a browser/client
  context, not as server-only output.
- Each component's API is its `<Name>.d.ts` (the `<Name>Props` interface). Read
  it before composing — props are the only configuration surface.

## Styling idiom — Tailwind utility classes (with one caveat)

The components are styled with **Tailwind CSS utility classes** baked into their
markup. The shipped `styles.css` carries the **compiled subset of Tailwind that
these components actually use** — it is NOT a full Tailwind build.

- The components render fully styled out of the box (colors, spacing, borders,
  rounded corners) — you do not configure Tailwind to use them.
- **Caveat for your own layout glue:** an arbitrary Tailwind class you invent
  (e.g. `bg-purple-500`) may not exist in the shipped CSS, so it can render
  unstyled. Prefer **inline `style={{…}}`** for your own wrapper layout, or reuse
  the class vocabulary the components already use. Common families present
  (used by these components): `flex`, `items-center`, `justify-between`, `gap-*`,
  `rounded-md`/`rounded-full`, `border`, `px-*`/`py-*`/`mt-*`/`mb-*`,
  `text-xs`/`text-sm`, `font-medium`/`font-semibold`, and the gray / blue /
  amber / green palette (`text-gray-*`, `bg-gray-50`, `bg-blue-50`,
  `text-blue-700`, `bg-amber-50`, `text-amber-900`).

## Where the truth lives

- Component APIs: `components/<group>/<Name>/<Name>.d.ts`.
- Styles: `styles.css` and its `@import` closure (`_ds_bundle.css`).
- Per-component usage: `components/<group>/<Name>/<Name>.prompt.md`.

## Component summary

- **StubBanner** — yellow offline-mode banner (`provider="stub"`).
- **ProgressBar** — live agent progress (`label`, `iteration`, `max`); pass
  `iteration={null}` for an indeterminate state.
- **SuggestionChips** — clickable follow-up chips (`suggestions: string[]`,
  `onPick`).
- **Markdown** — renders a markdown string (`children`) with GFM tables/lists.
- **ClarificationTurn** — amber "agent is asking" turn (`clarificationQuestion`,
  `onResubmit`).
- **PromptBreakdown** / **StepsInspector** — collapsible widgets; they render
  collapsed by default and expand on click.

## One idiomatic build snippet

```tsx
import { Markdown, SuggestionChips } from 'agent-frontend'

function AnswerBlock({ answer, followups }: { answer: string; followups: string[] }) {
  return (
    <div style={{ maxWidth: 640, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Markdown>{answer}</Markdown>
      <SuggestionChips suggestions={followups} onPick={(q) => console.log(q)} />
    </div>
  )
}
```
