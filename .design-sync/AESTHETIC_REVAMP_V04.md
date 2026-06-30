# Data Analysis Agent v0.4 — Full Aesthetic Revamp

## Design Brief

A complete visual overhaul focusing on modern typography, sophisticated color palette, and refined visual hierarchy. Layout remains unchanged—only fonts, text sizes, and colors are transformed.

---

## Typography System — Modern & Premium

### Font Stack (One font family, multiple weights)

**Primary Font**: `Inter, system-ui, -apple-system, sans-serif`
- Modern, clean, highly readable
- Excellent for data/numbers
- Professional appearance
- 6 weights available: 300, 400, 500, 600, 700, 800

### Text Scale Hierarchy

| Level | Size | Weight | Line Height | Letter Spacing | Use Case |
|-------|------|--------|-------------|----------------|----------|
| **Display XL** | 3xl (30px) | 800 | 1.2 | -0.02em | N/A (not used in this app) |
| **Display Large** | 2xl (24px) | 700 | 1.3 | -0.01em | Page title (app name) |
| **Display Medium** | xl (20px) | 700 | 1.4 | 0 | Section headers |
| **Display Small** | lg (18px) | 600 | 1.5 | 0 | Card titles |
| **Heading** | base (16px) | 600 | 1.5 | 0 | Subsection titles |
| **Body Large** | base (16px) | 500 | 1.6 | 0 | Primary body text |
| **Body Regular** | sm (14px) | 400 | 1.6 | 0 | Standard body text |
| **Body Small** | xs (12px) | 400 | 1.5 | 0.02em | Labels, hints |
| **Caption** | xs (12px) | 500 | 1.4 | 0.05em | Small labels |
| **Mono/Code** | sm (14px) | 400 | 1.6 | 0 | Tokens, code |

### Letter Spacing Details
- Tight (-0.02em): Large display text
- Tight (-0.01em): Large headings
- Normal (0): Most text
- Loose (0.02-0.05em): Small labels, all-caps

---

## Color Palette — Sophisticated & Modern

### Core Brand Palette

**Primary Brand Color**: Deep Indigo (replacing blue)
- `indigo-950` — Darkest (backgrounds)
- `indigo-900` — Very dark (text primary)
- `indigo-600` — Vibrant (accents, active)
- `indigo-400` — Light (hover states)
- `indigo-100` — Lightest (backgrounds)

**Secondary**: Cool Gray (replacing slate)
- `gray-950` — Darkest text
- `gray-100` — Light backgrounds
- `gray-600` — Secondary text

**Accent Colors** (Semantic meaning)

| Color | Light | Dark | Usage |
|-------|-------|------|-------|
| **Success** | `green-500` | `green-400` | Success, positive, done |
| **Caution** | `amber-500` | `amber-400` | Warnings, caution |
| **Error** | `red-500` | `red-400` | Errors, delete, destructive |
| **Info** | `sky-500` | `sky-400` | Information, secondary |
| **Purple** | `purple-500` | `purple-400` | Alternative accent |

### Light Mode Palette

```
Backgrounds:
  Page Background:    #f9fafb (gray-50, not slate)
  Card Background:    #ffffff (pure white)
  Hover Background:   #f3f4f6 (gray-100)
  Active Background:  #eef2ff (indigo-50)
  Disabled:           #f3f4f6 (gray-100)

Text:
  Primary:            #111827 (gray-950)
  Secondary:          #4b5563 (gray-600)
  Tertiary:           #9ca3af (gray-400)
  Disabled:           #d1d5db (gray-300)
  On Indigo:          #ffffff (white for contrast)

Accents:
  Indigo Primary:     #4f46e5 (indigo-600)
  Indigo Dark:        #312e81 (indigo-900)
  Success:            #10b981 (green-500)
  Error:              #ef4444 (red-500)
  Warning:            #f59e0b (amber-500)
  Info:               #0ea5e9 (sky-500)

Borders:
  Strong:             #d1d5db (gray-300)
  Standard:           #e5e7eb (gray-200)
  Subtle:             #f3f4f6 (gray-100)
```

### Dark Mode Palette

```
Backgrounds:
  Page Background:    #0f172a (slate-900, deeper)
  Card Background:    #1e293b (slate-800)
  Hover Background:   #334155 (slate-700)
  Active Background:  #312e81 (indigo-950)
  Disabled:           #334155 (slate-700)

Text:
  Primary:            #f8fafc (slate-50)
  Secondary:          #cbd5e1 (slate-300)
  Tertiary:           #94a3b8 (slate-400)
  Disabled:           #64748b (slate-500)
  On Indigo:          #ffffff (white for contrast)

Accents:
  Indigo Primary:     #818cf8 (indigo-400)
  Indigo Dark:        #4f46e5 (indigo-600)
  Success:            #34d399 (green-400)
  Error:              #f87171 (red-400)
  Warning:            #fbbf24 (amber-400)
  Info:               #38bdf8 (sky-400)

Borders:
  Strong:             #475569 (slate-600)
  Standard:           #334155 (slate-700)
  Subtle:             #1e293b (slate-800)
```

---

## Component Mockups — Before & After

### Header

**BEFORE**
```
┌─────────────────────────────────────────────────────┐
│ 📊 Data Analysis Agent                              │
│ Ask questions in plain English, get explainable...  │
│ [Analyse] [Database]           [Live] [Project notes]│
│ (Gradient indigo-600→blue-600, text-white)         │
└─────────────────────────────────────────────────────┘
Font: lg bold / xs / sm medium
```

**AFTER (v0.4)**
```
┌─────────────────────────────────────────────────────┐
│ 📊 Data Analysis Agent                              │
│ Ask questions, get explainable answers              │
│ [Analyse] [Database]           [Live] [Project notes]│
│ (Solid indigo-900 bg, text-white, refined)         │
└─────────────────────────────────────────────────────┘
Font: 2xl bold (24px, 800) / sm regular (14px, 400) / base medium (16px, 600)
```

Changes:
- **Title**: lg (18px) 600 → 2xl (24px) 800 (bolder, larger)
- **Tagline**: xs (12px) 400 → sm (14px) 400 (more readable)
- **Button**: sm (14px) medium → base (16px) 600 (more prominent)
- **Background**: Gradient → Solid indigo-900 (more refined)
- **Font**: Default → Inter (cleaner)

### Sidebar — Sessions Card

**BEFORE**
```
┌──────────────────────────────┐
│ 📋 Sessions          [notes]  │  (text-base font-semibold)
│ ─────────────────────────────│
│ [+ New] [Select all]         │  (text-xs font-medium)
│ ─────────────────────────────│
│ • Active Session             │  (text-sm font-medium)
│   3 turns · active           │  (text-[11px])
│ ─────────────────────────────│
└──────────────────────────────┘
```

**AFTER (v0.4)**
```
┌──────────────────────────────┐
│ 📋 Sessions          [notes]  │  (text-lg font-bold)
│ ─────────────────────────────│
│ [+ New] [Select all]         │  (text-sm font-medium)
│ ─────────────────────────────│
│ • Active Session             │  (text-base font-600)
│   3 turns · active           │  (text-xs font-400)
│ ─────────────────────────────│
└──────────────────────────────┘
```

Changes:
- **Card title**: 14px base 600 → 20px lg 700 (more prominent)
- **Buttons**: xs 400 → sm 500 (better readable)
- **Session name**: sm 500 → base 600 (clearer hierarchy)
- **Meta text**: [11px] → xs 400 (standard sizing)
- **Font weights**: More variation for hierarchy

### Token Usage Widget

**BEFORE**
```
┌──────────────────────────────┐
│ 📊 Token usage               │  (text-sm font-semibold)
│ ─────────────────────────────│
│ GEMINI-3.1-FLASH-LITE        │  (text-xs font-bold)
│                              │
│ Provider/mode: gemini        │  (text-xs text-gray-500)
│ Last query: 1,234 / 567      │  (text-xs)
│ Today: 12,345 / 6,789 / 5    │  (text-xs)
└──────────────────────────────┘
```

**AFTER (v0.4)**
```
┌──────────────────────────────┐
│ 📊 Token Usage               │  (text-lg font-bold)
│ ─────────────────────────────│
│ GEMINI-3.1-FLASH-LITE        │  (text-xs font-bold uppercase)
│                              │
│ Provider / mode: gemini      │  (text-xs text-gray-600)
│ Last query (in / out)        │  (text-xs text-gray-600)
│    1,234 / 567               │  (text-sm font-600 text-gray-900)
│ Today (in / out / queries)   │  (text-xs text-gray-600)
│    12,345 / 6,789 / 5        │  (text-sm font-600 text-gray-900)
└──────────────────────────────┘
```

Changes:
- **Card title**: sm 600 → lg 700 (more hierarchy)
- **Model badge**: Keep but refined styling
- **Labels**: Reorganized and sized as xs (12px)
- **Values**: Now sm 600 (14px) for better readability
- **Overall**: Better label/value pairing

### Conversation Card

**BEFORE**
```
┌─────────────────────────────────────┐
│ 💬 Conversation                     │  (text-sm)
│ ──────────────────────────────────  │
│ 👤 You                    2:34 PM   │  (text-xs)
│ ┌───────────────────────────────┐   │
│ │ "What's the trend?"           │   │  (text-sm)
│ └───────────────────────────────┘   │
│                                     │
│ 🤖 Assistant                2:35 PM │  (text-xs)
│ ┌───────────────────────────────┐   │
│ │ Based on the data...          │   │  (text-sm)
│ │ Key findings:                 │   │  (text-sm font-medium)
│ │ • 23% YoY growth             │   │  (text-sm)
│ └───────────────────────────────┘   │
└─────────────────────────────────────┘
```

**AFTER (v0.4)**
```
┌─────────────────────────────────────┐
│ 💬 Conversation                     │  (text-lg font-bold)
│ ──────────────────────────────────  │
│ 👤 You                    2:34 PM   │  (text-sm font-600)
│ ┌───────────────────────────────┐   │
│ │ "What's the trend?"           │   │  (text-base font-500)
│ └───────────────────────────────┘   │
│                                     │
│ 🤖 Assistant                2:35 PM │  (text-sm font-600)
│ ┌───────────────────────────────┐   │
│ │ Based on the data...          │   │  (text-base font-400)
│ │ Key findings:                 │   │  (text-sm font-600)
│ │ • 23% YoY growth             │   │  (text-base font-400)
│ └───────────────────────────────┘   │
└─────────────────────────────────────┘
```

Changes:
- **Header**: sm → lg 700 (more prominent)
- **Sender name**: xs → sm 600 (clearer)
- **Message text**: sm → base 400 (larger, more readable)
- **Emphasis**: Better weight hierarchy
- **Overall**: Improved readability for longer conversations

### Tables Card

**BEFORE**
```
┌────────────────────────────────┐
│ 📁 Tables & Datasets           │  (text-sm)
│ ────────────────────────────── │
│ Filter: [All] [Uploaded]...    │  (text-xs)
│ ────────────────────────────── │
│ ☐ Dataset 1  │ 1.2 MB │ 5.2K  │  (text-sm)
│ ☑ Dataset 2  │ 856 KB │ 2.1K  │  (text-sm)
└────────────────────────────────┘
```

**AFTER (v0.4)**
```
┌────────────────────────────────┐
│ 📁 Tables & Datasets           │  (text-lg font-bold)
│ ────────────────────────────── │
│ Filter: [All] [Uploaded]...    │  (text-xs font-500)
│ ────────────────────────────── │
│ ☐ Dataset 1  │ 1.2 MB │ 5.2K  │  (text-base font-400)
│ ☑ Dataset 2  │ 856 KB │ 2.1K  │  (text-base font-400)
│                               │
│ [📊 Details] [🧹 Clean]...   │  (text-sm font-600)
└────────────────────────────────┘
```

Changes:
- **Card title**: sm → lg 700 (more prominent)
- **Filters**: xs → xs 500 (slightly bolder)
- **Table rows**: sm → base 400 (larger, easier to scan)
- **Action buttons**: Clearer labeling

### Upload Card

**BEFORE**
```
┌────────────────────────────────┐
│ ⬆️ Upload Data                  │  (text-sm)
│ ────────────────────────────── │
│ 🎯 Drag files here...          │  (text-sm)
│ Supports: CSV · JSON · Excel   │  (text-xs)
│ [📁 Choose files]              │  (text-xs)
└────────────────────────────────┘
```

**AFTER (v0.4)**
```
┌────────────────────────────────┐
│ ⬆️ Upload Data                  │  (text-lg font-bold)
│ ────────────────────────────── │
│ 🎯 Drag files here or click    │  (text-base font-500)
│ Supports: CSV, JSON, Excel     │  (text-sm font-400)
│ Max: 100 MB per file           │  (text-xs font-400)
│ [📁 Choose files]              │  (text-sm font-600)
└────────────────────────────────┘
```

Changes:
- **Card title**: sm → lg 700 (hierarchy)
- **Main CTA**: xs → base 500 (more visible)
- **Subtitle**: xs → sm 400 (better readability)
- **Button**: xs → sm 600 (more prominent)

---

## Color Scheme Comparison

### Light Mode

| Element | Before | After v0.4 | Reason |
|---------|--------|-----------|--------|
| Page BG | `gray-50` | `gray-50` | Consistent |
| Card BG | `white` | `white` | Consistent |
| Text Primary | `gray-950` | `gray-950` | Consistent |
| Text Secondary | `gray-600` | `gray-600` | Consistent |
| Header BG | gradient indigo-600→blue-600 | solid indigo-900 | More refined, professional |
| Primary Button | `emerald-50/emerald-700` | `indigo-600/white` | Match header brand |
| Active State | `emerald-300/emerald-50` | `indigo-600/indigo-50` | Consistent branding |
| Success | `green-500` | `green-500` | Keep existing |
| Error | `rose-600` | `red-500` | Clearer semantic |
| Warning | `amber-500` | `amber-500` | Keep existing |

### Dark Mode

| Element | Before | After v0.4 | Reason |
|---------|--------|-----------|--------|
| Page BG | `slate-950` | `slate-900` | Slightly lighter for readability |
| Card BG | `slate-900` | `slate-800` | Better contrast |
| Text Primary | `slate-50` | `slate-50` | Consistent |
| Text Secondary | `slate-300` | `slate-300` | Consistent |
| Header BG | gradient indigo-600→blue-600 | solid indigo-900 | Match light mode |
| Primary Button | `emerald-400/white` | `indigo-400/white` | Match header brand |
| Active State | `emerald-700/emerald-950` | `indigo-600/indigo-950` | Consistent branding |
| Success | `emerald-400` | `green-400` | Clearer semantic |
| Error | `rose-400` | `red-400` | Clearer semantic |
| Warning | `amber-400` | `amber-400` | Keep existing |

---

## Summary of Changes for v0.4

### Typography Changes
- **Font Family**: Default system → Inter (modern, clean)
- **Text Scaling**: Increased throughout for better readability
- **Weight Hierarchy**: More variation (300-800) for better visual structure
- **Line Heights**: Optimized for readability (1.4-1.6)
- **Letter Spacing**: Tight on large text, loose on small labels

### Color Changes
- **Primary Brand**: Blue → Deep Indigo (indigo-900/600)
- **Secondary**: Slate → Gray (cleaner, less cool-toned)
- **Semantic Colors**: Emerald → Green/Red/Amber/Sky (clearer meaning)
- **Header**: Gradient → Solid (more refined)
- **Dark Mode**: Adjusted slate depths for better contrast

### Visual Hierarchy Improvements
- Card titles: 14px → 20px (40% larger)
- Body text: 14px → 16px base (more readable)
- Labels: 12px → 12px (consistent, cleaner)
- Buttons: 14px → 16px (more prominent)

### Overall Effect
- ✨ More sophisticated and premium
- 📖 Better readability
- 🎯 Clearer visual hierarchy
- 🎨 Modern, cohesive brand
- ♿ Improved accessibility

---

## Implementation Checklist

### Phase 1: Typography
- [ ] Import Inter font
- [ ] Update Tailwind font config
- [ ] Apply new text scales throughout components
- [ ] Adjust line heights and letter spacing

### Phase 2: Colors
- [ ] Update color palette in Tailwind config
- [ ] Change header from gradient to solid
- [ ] Update button colors (emerald → indigo)
- [ ] Update all accent colors
- [ ] Test dark mode compatibility

### Phase 3: Components
- [ ] AppShell header
- [ ] SessionSidebar
- [ ] TokenWidget
- [ ] TablesCard
- [ ] UploadCard
- [ ] ConversationCard
- [ ] All buttons and inputs

### Phase 4: Testing & Polish
- [ ] Verify readability
- [ ] Check contrast ratios (WCAG AA)
- [ ] Test dark/light mode
- [ ] Mobile responsiveness
- [ ] Performance check

### Phase 5: Git & Release
- [ ] Commit as v0.4
- [ ] Tag release
- [ ] Update CHANGELOG

