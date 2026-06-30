# Data Analysis Agent — Dark/Light Mode & Extended Color Palette

## Overview

This document outlines:
1. **Dark Mode** — A sophisticated dark theme for low-light environments
2. **Light Mode** — Enhanced version of current design with refinements
3. **Extended Color Palette** — Additional colors for better semantic meaning
4. **Theme Toggle** — How to switch between modes
5. **Mockups** — Visual examples of both themes

---

## Color System — Comprehensive Palette

### Light Mode

**Backgrounds**
- `bg-white` — Card backgrounds, content areas
- `bg-slate-50` — Main page background
- `bg-slate-100` — Secondary backgrounds, hover states
- `bg-slate-200` — Tertiary backgrounds, disabled states

**Text**
- `text-slate-950` — Primary text (headings, important text)
- `text-slate-900` — Body text
- `text-slate-700` — Secondary text
- `text-slate-500` — Tertiary text (labels, hints)
- `text-slate-400` — Disabled text

**Borders**
- `border-slate-300` — Strong borders (inputs, dividers)
- `border-slate-200` — Standard borders (cards)
- `border-slate-100` — Subtle borders (internal divisions)

### Dark Mode

**Backgrounds**
- `bg-slate-950` — Main page background (deepest)
- `bg-slate-900` — Primary background (panels, cards)
- `bg-slate-800` — Secondary backgrounds, hover states
- `bg-slate-700` — Tertiary backgrounds, inputs

**Text**
- `text-slate-50` — Primary text (headings, important)
- `text-slate-100` — Body text
- `text-slate-300` — Secondary text
- `text-slate-400` — Tertiary text (labels)
- `text-slate-500` — Disabled text

**Borders**
- `border-slate-600` — Strong borders
- `border-slate-700` — Standard borders
- `border-slate-800` — Subtle borders

---

## Semantic Colors (Both Themes)

### Primary Actions (Emerald)
- **Light**: `emerald-600` text, `emerald-50` bg
- **Dark**: `emerald-400` text, `emerald-950` bg
- **Usage**: New, Create, Save, Confirm actions

### Success/Positive (Emerald Green)
- **Light**: `emerald-500`
- **Dark**: `emerald-400`
- **Usage**: Success messages, active states, progress completion

### Warning/Caution (Amber)
- **Light**: `amber-500`
- **Dark**: `amber-400`
- **Usage**: Warnings, context warnings, high resource usage

### Error/Destructive (Rose)
- **Light**: `rose-600` text, `rose-50` bg
- **Dark**: `rose-400` text, `rose-950` bg
- **Usage**: Delete, destructive actions, errors

### Info/Secondary (Indigo/Blue)
- **Light**: `indigo-600` text, `indigo-50` bg
- **Dark**: `indigo-400` text, `indigo-950` bg
- **Usage**: Headers, badges, secondary actions

### Data Visualization (Extended)
- **Blue**: `blue-500` (primary data line)
- **Cyan**: `cyan-500` (secondary data)
- **Purple**: `purple-500` (tertiary data)
- **Pink**: `pink-500` (quaternary data)
- **Orange**: `orange-500` (variance/comparison)

---

## Theme Mockups

### Light Mode — Header

```
┌─────────────────────────────────────────────────────┐
│ Gradient bg: indigo-600 → blue-600                 │
│ ───────────────────────────────────────────────────  │
│  📊 Data Analysis Agent     [Analyse] [Database]   │
│  Ask questions in plain English    [●Live] [📝Notes]│
│                                                      │
│  White text on gradient, nice spacing               │
└─────────────────────────────────────────────────────┘
```

### Dark Mode — Header

```
┌─────────────────────────────────────────────────────┐
│ Solid bg: slate-900 with subtle gradient overlay   │
│ ───────────────────────────────────────────────────  │
│  📊 Data Analysis Agent     [Analyse] [Database]   │
│  Ask questions in plain English    [●Live] [📝Notes]│
│                                                      │
│  Light text on dark bg, refined shadows             │
└─────────────────────────────────────────────────────┘
```

---

## Light Mode — Sidebar

```
┌─────────────────────────────────────────────────┐
│ bg-white, border-slate-200                      │
│ ──────────────────────────────────────────────── │
│ 📋 Sessions              [Project notes]        │
│ ──────────────────────────────────────────────── │
│ [+New] [Select all] [Delete selected]           │
│ ──────────────────────────────────────────────── │
│ • Active Session    (emerald-50 bg, border)     │
│   3 turns · active                              │
│                                                 │
│ • Past Session 1    (hover: slate-50)           │
│   2 turns · rename · delete                     │
│                                                 │
│ • Past Session 2    (hover: slate-50)           │
│   1 turn · rename · delete                      │
│ ──────────────────────────────────────────────── │
│ 📊 Token usage          (indigo-100 badge)     │
│ ──────────────────────────────────────────────── │
│ Model: GEMINI-3.1-FLASH-LITE                    │
│                                                 │
│ Provider/mode: gemini (text-slate-700)          │
│ Last query: 1,234 / 567 (text-slate-900)        │
│ Today: 12,345 / 6,789 / 5 (text-slate-900)      │
│                                                 │
│ Context window (last query): 45%                │
│ ▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░ (emerald-500 bar)     │
│ ──────────────────────────────────────────────── │
│ 📁 Datasets: 3 · 📊 Rows: 15K (slate-100 bg)   │
│ ──────────────────────────────────────────────── │
│ Cost estimate                                   │
│ Last query cost: $0.002 (text-slate-700)        │
│ Today cost: $0.008 (text-slate-700)             │
│ ──────────────────────────────────────────────── │
│ [⚙️ Settings] [🔔 Notifications]                │
└─────────────────────────────────────────────────┘
```

## Dark Mode — Sidebar

```
┌─────────────────────────────────────────────────┐
│ bg-slate-900, border-slate-700                  │
│ ──────────────────────────────────────────────── │
│ 📋 Sessions              [Project notes]        │
│ ──────────────────────────────────────────────── │
│ [+New] [Select all] [Delete selected]           │
│ ──────────────────────────────────────────────── │
│ • Active Session    (emerald-950 bg, border)    │
│   3 turns · active                              │
│                                                 │
│ • Past Session 1    (hover: slate-800)          │
│   2 turns · rename · delete                     │
│                                                 │
│ • Past Session 2    (hover: slate-800)          │
│   1 turn · rename · delete                      │
│ ──────────────────────────────────────────────── │
│ 📊 Token usage          (indigo-950 badge)     │
│ ──────────────────────────────────────────────── │
│ Model: GEMINI-3.1-FLASH-LITE                    │
│                                                 │
│ Provider/mode: gemini (text-slate-400)          │
│ Last query: 1,234 / 567 (text-slate-100)        │
│ Today: 12,345 / 6,789 / 5 (text-slate-100)      │
│                                                 │
│ Context window (last query): 45%                │
│ ▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░ (emerald-400 bar)     │
│ ──────────────────────────────────────────────── │
│ 📁 Datasets: 3 · 📊 Rows: 15K (slate-800 bg)   │
│ ──────────────────────────────────────────────── │
│ Cost estimate                                   │
│ Last query cost: $0.002 (text-slate-300)        │
│ Today cost: $0.008 (text-slate-300)             │
│ ──────────────────────────────────────────────── │
│ [⚙️ Settings] [🔔 Notifications]                │
└─────────────────────────────────────────────────┘
```

---

## Light Mode — Main Content Cards

```
┌──────────────────────────────────────────────────────┐
│ 📁 Tables & Datasets                                 │
│ ──────────────────────────────────────────────────── │
│ Filter: [All] [Uploaded] [Derived] [This session]   │
│ ──────────────────────────────────────────────────── │
│ Column Headers:  Name ↕ │ Size ↕ │ Rows ↕          │
│ ┌──────────────────────────────────────────────────┐ │
│ │ ☐ Dataset 1      │ 1.2 MB │ 5.2K rows           │ │
│ │ ☑ Dataset 2      │ 856 KB │ 2.1K rows           │ │
│ │ ☐ Dataset 3      │ 2.4 MB │ 12K rows (stale)    │ │
│ └──────────────────────────────────────────────────┘ │
│ ──────────────────────────────────────────────────── │
│ [📊 Details] [🧹 Clean] [🔄 Refresh] [🗑️ Delete]    │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│ ⬆️ Upload Data                                        │
│ ──────────────────────────────────────────────────── │
│ 🎯 Drag files here or click to pick                 │
│ Supports: CSV · JSON · Excel · Parquet · TSV        │
│ Max file: 100 MB per file                           │
│ ──────────────────────────────────────────────────── │
│ [📁 Choose files]          [↗️ Connect API]          │
└──────────────────────────────────────────────────────┘
```

## Dark Mode — Main Content Cards

```
┌──────────────────────────────────────────────────────┐
│ 📁 Tables & Datasets (text-slate-50)                 │
│ ──────────────────────────────────────────────────── │
│ Filter: [All] [Uploaded] [Derived] [This session]   │
│ ──────────────────────────────────────────────────── │
│ Column Headers:  Name ↕ │ Size ↕ │ Rows ↕          │
│ ┌──────────────────────────────────────────────────┐ │
│ │ bg-slate-800, text-slate-100                     │ │
│ │ ☐ Dataset 1      │ 1.2 MB │ 5.2K rows           │ │
│ │ ☑ Dataset 2      │ 856 KB │ 2.1K rows           │ │
│ │ ☐ Dataset 3      │ 2.4 MB │ 12K rows (stale)    │ │
│ └──────────────────────────────────────────────────┘ │
│ ──────────────────────────────────────────────────── │
│ [📊 Details] [🧹 Clean] [🔄 Refresh] [🗑️ Delete]    │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│ ⬆️ Upload Data (text-slate-50)                        │
│ ──────────────────────────────────────────────────── │
│ 🎯 Drag files here or click to pick                 │
│ Supports: CSV · JSON · Excel · Parquet · TSV        │
│ Max file: 100 MB per file                           │
│ ──────────────────────────────────────────────────── │
│ [📁 Choose files]          [↗️ Connect API]          │
└──────────────────────────────────────────────────────┘
```

---

## Light Mode — Conversation Area

```
┌──────────────────────────────────────────────────────┐
│ 💬 Conversation         [↻ Clear] [📥 Export]        │
│ ──────────────────────────────────────────────────── │
│ bg-slate-50 (light background for readability)      │
│                                                      │
│ 👤 You                          2:34 PM              │
│ ┌────────────────────────────────────────────────┐  │
│ │ bg-indigo-50, border-indigo-200                │  │
│ │ text-slate-900                                  │  │
│ │ "What's the trend in Q3 sales?"                │  │
│ └────────────────────────────────────────────────┘  │
│                                                      │
│ 🤖 Assistant                    2:35 PM              │
│ ┌────────────────────────────────────────────────┐  │
│ │ bg-white, border-slate-200                     │  │
│ │ text-slate-900                                  │  │
│ │                                                 │  │
│ │ Based on the data in your Q3 sales file:       │  │
│ │                                                 │  │
│ │ 📊 [Interactive Chart]                         │  │
│ │ ╭─────────────────────────────────────────╮   │  │
│ │ │  Sales Trend                            │   │  │
│ │ │  ▲ $500K                                │   │  │
│ │ │  │     ╱╲                               │   │  │
│ │ │  │    ╱  ╲                              │   │  │
│ │ │  │   ╱    ╲╱╲                           │   │  │
│ │ │  └─────────────────────────────────     │   │  │
│ │ │  Jul  Aug  Sep                         │   │  │
│ │ ╰─────────────────────────────────────────╯   │  │
│ │                                                 │  │
│ │ **Key Findings:**                              │  │
│ │ • Growth of 23% YoY                            │  │
│ │ • Peak in August ($520K)                       │  │
│ │ • Dip in September (-15%)                      │  │
│ │                                                 │  │
│ │ This suggests seasonal summer demand.          │  │
│ └────────────────────────────────────────────────┘  │
│                                                      │
│ ✨ Next steps:                                       │
│ [💡 "Compare to Q2?"] [📊 "Show breakdown?"]        │
│ ──────────────────────────────────────────────────── │
│ [Ask a follow-up question...]  [🚀 Send]            │
└──────────────────────────────────────────────────────┘
```

## Dark Mode — Conversation Area

```
┌──────────────────────────────────────────────────────┐
│ 💬 Conversation         [↻ Clear] [📥 Export]        │
│ ──────────────────────────────────────────────────── │
│ bg-slate-900 (dark background)                       │
│                                                      │
│ 👤 You                          2:34 PM              │
│ ┌────────────────────────────────────────────────┐  │
│ │ bg-indigo-950, border-indigo-700               │  │
│ │ text-slate-50                                   │  │
│ │ "What's the trend in Q3 sales?"                │  │
│ └────────────────────────────────────────────────┘  │
│                                                      │
│ 🤖 Assistant                    2:35 PM              │
│ ┌────────────────────────────────────────────────┐  │
│ │ bg-slate-800, border-slate-700                 │  │
│ │ text-slate-50                                   │  │
│ │                                                 │  │
│ │ Based on the data in your Q3 sales file:       │  │
│ │                                                 │  │
│ │ 📊 [Interactive Chart]                         │  │
│ │ ╭─────────────────────────────────────────╮   │  │
│ │ │  Sales Trend (dark version)             │   │  │
│ │ │  ▲ $500K                                │   │  │
│ │ │  │     ╱╲                               │   │  │
│ │ │  │    ╱  ╲ (blue-400 line)              │   │  │
│ │ │  │   ╱    ╲╱╲                           │   │  │
│ │ │  └─────────────────────────────────     │   │  │
│ │ │  Jul  Aug  Sep                         │   │  │
│ │ ╰─────────────────────────────────────────╯   │  │
│ │                                                 │  │
│ │ **Key Findings:**                              │  │
│ │ • Growth of 23% YoY (emerald-400)              │  │
│ │ • Peak in August ($520K)                       │  │
│ │ • Dip in September (-15%) (rose-400)           │  │
│ │                                                 │  │
│ │ This suggests seasonal summer demand.          │  │
│ └────────────────────────────────────────────────┘  │
│                                                      │
│ ✨ Next steps:                                       │
│ [💡 "Compare to Q2?"] [📊 "Show breakdown?"]        │
│ ──────────────────────────────────────────────────── │
│ [Ask a follow-up question...]  [🚀 Send]            │
└──────────────────────────────────────────────────────┘
```

---

## Additional Design Improvements

### 1. **Cards with Depth**

**Light Mode**
```
Card: bg-white
Shadow: shadow-sm (subtle)
Border: border-slate-200
Hover: shadow, border-slate-300
```

**Dark Mode**
```
Card: bg-slate-900
Shadow: shadow-sm with darker tones
Border: border-slate-700
Hover: shadow, border-slate-600
```

### 2. **Buttons — All Variants**

**Primary (Emerald)**
- Light: `bg-emerald-500 text-white hover:bg-emerald-600`
- Dark: `bg-emerald-600 text-white hover:bg-emerald-500`

**Secondary (Slate)**
- Light: `bg-slate-200 text-slate-900 hover:bg-slate-300`
- Dark: `bg-slate-700 text-slate-100 hover:bg-slate-600`

**Ghost (Transparent)**
- Light: `bg-transparent border border-slate-300 text-slate-700 hover:bg-slate-100`
- Dark: `bg-transparent border border-slate-600 text-slate-300 hover:bg-slate-800`

**Danger (Rose)**
- Light: `bg-rose-500 text-white hover:bg-rose-600`
- Dark: `bg-rose-600 text-white hover:bg-rose-500`

### 3. **Form Inputs**

**Light Mode**
```
bg-white
border-slate-300
focus:border-indigo-500 focus:ring-indigo-500
placeholder:text-slate-400
```

**Dark Mode**
```
bg-slate-800
border-slate-600
focus:border-indigo-400 focus:ring-indigo-400
placeholder:text-slate-500
```

### 4. **Status Indicators**

- **Success**: `emerald-500` (with checkmark ✓)
- **Warning**: `amber-500` (with exclamation ⚠)
- **Error**: `rose-500` (with X ✗)
- **Info**: `indigo-500` (with info circle ℹ)
- **Loading**: `slate-400` with spinner animation

### 5. **Data Visualization Colors**

For charts and graphs in both themes:

| Purpose | Light | Dark | Hex |
|---------|-------|------|-----|
| Primary Series | `blue-500` | `blue-400` | #3B82F6 / #60A5FA |
| Secondary | `cyan-500` | `cyan-400` | #06B6D4 / #22D3EE |
| Tertiary | `purple-500` | `purple-400` | #A855F7 / #C084FC |
| Accent | `pink-500` | `pink-400` | #EC4899 / #F472B6 |
| Compare/Diff | `orange-500` | `orange-400` | #F97316 / #FB923C |

### 6. **Animations & Transitions**

- **Button hover**: `transition-all duration-200`
- **Color changes**: `transition-colors duration-150`
- **Message arrival**: `animate-slideIn duration-300`
- **Loading spinner**: `animate-spin duration-1000`
- **Active indicator pulse**: `animate-pulse duration-2000`

---

## Theme Toggle Implementation

### Layout & Behavior

**Location**: Top-right corner near "Project notes" button

```
Light Mode: ☀️ [Light] [🌙 Dark]
Dark Mode:  [☀️ Light] 🌙 [Dark]
```

**Persistence**: Save to localStorage
- Key: `dataAgentTheme`
- Values: `light` | `dark` | `system`
- Default: `system` (respects OS preference)

**CSS Implementation**
```css
/* Root element color scheme */
html.light { color-scheme: light; }
html.dark { color-scheme: dark; }

/* Tailwind: use dark: prefix */
.card {
  @apply bg-white dark:bg-slate-900;
  @apply border-slate-200 dark:border-slate-700;
}
```

---

## Summary of Changes

| Component | Light | Dark | Notes |
|-----------|-------|------|-------|
| **Background** | `bg-slate-50` | `bg-slate-950` | Refined from gray |
| **Cards** | `bg-white` | `bg-slate-900` | Better contrast |
| **Text Primary** | `text-slate-950` | `text-slate-50` | Increased contrast |
| **Text Secondary** | `text-slate-700` | `text-slate-300` | Better readability |
| **Borders** | `border-slate-200` | `border-slate-700` | Adjusted for modes |
| **Active State** | `emerald-*` | `emerald-*` | Consistent accent |
| **Primary Button** | `emerald-500` | `emerald-600` | Brightness adjusted |
| **Inputs** | `border-slate-300` | `border-slate-600` | Better visibility |
| **Shadows** | Subtle | Enhanced | Dark mode needs more depth |
| **Colors** | 4 semantic | 4 semantic + data | Expanded palette |

---

## Implementation Strategy

### Phase 1: Dark Mode Support
1. Add theme toggle button to header
2. Implement CSS dark: prefixes throughout
3. Create dark mode color variables
4. Test all components in both modes

### Phase 2: Enhanced Light Mode
1. Refine spacing and typography
2. Add subtle shadows and depth
3. Improve hover/active states
4. Better visual hierarchy

### Phase 3: Color Palette Expansion
1. Add data visualization colors
2. Extend semantic colors
3. Add gradient overlays
4. Status indicators

### Phase 4: Polish & Animation
1. Smooth transitions
2. Micro-interactions
3. Loading states
4. Error boundaries

