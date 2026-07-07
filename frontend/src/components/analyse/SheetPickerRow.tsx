'use client'

import type { SheetImportResult, SheetInfo } from '@/lib/api'

/**
 * Sheet picker (C38, Phase 12) — the inline checklist rendered inside an
 * UploadCard staged row when a `.xlsx`/`.xls` upload returns the
 * `type:"multi_sheet"` inspect variant.
 *
 * Mirrors the C36 pick-tables checklist pattern (ConnectDatabaseCard): one
 * checkbox row per server-enumerated sheet (name + rows×cols), non-empty
 * sheets pre-checked by the parent, empty sheets disabled with an "empty"
 * tag, and an "Import N sheet(s)" commit button. Per-sheet results render
 * inline in place of the plain label:
 *  - `ok`        → green ✓ imported (rows × cols)
 *  - `duplicate` → the existing "Use existing / Upload anyway" resolver,
 *                  retrying just that sheet with `force:true`
 *  - `error`     → red inline message; the sheet stays checked so a retry
 *                  via the Import button re-attempts it
 *
 * PURE / presentational: all state (selections, results, in-flight flags)
 * lives in UploadCard's staged queue and arrives via props.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** One sheet's selection + import state, owned by UploadCard's staged queue. */
export interface SheetSelection {
  info: SheetInfo
  /** Whether the sheet is ticked for import (empty sheets are never checked). */
  checked: boolean
  /** True while an /upload/sheets call covering this sheet is in flight. */
  importing: boolean
  /** The per-sheet outcome of the last import attempt, if any. */
  result: SheetImportResult | null
  /** "Use existing" was clicked on a duplicate — resolved without importing. */
  dismissed: boolean
}

/** True when the sheet still needs an import attempt (drives the button count). */
export function isSheetImportable(s: SheetSelection): boolean {
  return s.checked && !s.info.empty && s.result?.status !== 'ok' && !s.dismissed
}

export interface SheetPickerRowProps {
  /** The staged workbook's filename (for aria labels only). */
  workbookName: string
  sheets: SheetSelection[]
  /** True while any /upload/sheets call for this row is in flight. */
  importing: boolean
  /** The staging token expired (404 `staging_expired`) — offer a re-stage. */
  stagingExpired: boolean
  /** Whole-call error message (network / unexpected), or undefined. */
  errorMsg?: string
  onToggleSheet: (sheetName: string) => void
  /** Import every currently-importable sheet. */
  onImport: () => void
  /** Re-upload the original file to obtain a fresh staging token. */
  onRestage: () => void
  /** Duplicate resolver: keep the existing dataset (dismiss). */
  onUseExisting: (sheetName: string) => void
  /** Duplicate resolver: re-import just this sheet with force=true. */
  onForceSheet: (sheetName: string) => void
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function SheetPickerRow({
  workbookName,
  sheets,
  importing,
  stagingExpired,
  errorMsg,
  onToggleSheet,
  onImport,
  onRestage,
  onUseExisting,
  onForceSheet,
}: SheetPickerRowProps) {
  // Staging expired — the server-side stash is gone (15-min TTL / restart).
  // Message + re-stage prompt per spec/ui.md; the File object is still staged
  // client-side, so re-staging is one click (no re-drop needed).
  if (stagingExpired) {
    return (
      <div
        role="alert"
        className="mt-2 flex flex-wrap items-center justify-between gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800"
      >
        <span>
          Sheet picker expired — staged workbooks are kept for 15 minutes. Re-stage the
          file to pick sheets again.
        </span>
        <button
          type="button"
          onClick={onRestage}
          className="shrink-0 rounded border border-amber-300 bg-white px-2 py-0.5 font-medium text-amber-800 hover:bg-amber-100"
        >
          Re-stage file
        </button>
      </div>
    )
  }

  const importableCount = sheets.filter(isSheetImportable).length

  return (
    <div className="mt-2">
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-gray-500">
        {sheets.length} sheet{sheets.length === 1 ? '' : 's'} found — select which to
        import
      </p>

      <ul
        role="list"
        aria-label={`Sheets in ${workbookName}`}
        className="max-h-48 space-y-1 overflow-y-auto rounded-md border border-gray-200 bg-white p-2"
      >
        {sheets.map(s => (
          <li key={s.info.sheet_name}>
            <SheetRow
              sheet={s}
              importing={importing}
              onToggle={() => onToggleSheet(s.info.sheet_name)}
              onUseExisting={() => onUseExisting(s.info.sheet_name)}
              onForce={() => onForceSheet(s.info.sheet_name)}
            />
          </li>
        ))}
      </ul>

      {errorMsg && (
        <p
          role="alert"
          className="mt-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700"
        >
          {errorMsg}
        </p>
      )}

      <div className="mt-2">
        <button
          type="button"
          onClick={onImport}
          disabled={importing || importableCount === 0}
          className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {importing && <Spinner />}
          {importing
            ? 'Importing…'
            : `Import ${importableCount} sheet${importableCount === 1 ? '' : 's'}`}
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// One sheet row
// ---------------------------------------------------------------------------

function SheetRow({
  sheet,
  importing,
  onToggle,
  onUseExisting,
  onForce,
}: {
  sheet: SheetSelection
  importing: boolean
  onToggle: () => void
  onUseExisting: () => void
  onForce: () => void
}) {
  const { info, result, dismissed } = sheet

  // Imported — terminal success state for this sheet.
  if (result?.status === 'ok') {
    const d = result.dataset
    return (
      <p role="status" className="flex items-center gap-2 rounded px-1.5 py-1 text-xs text-green-700">
        <span aria-hidden="true">&#10003;</span>
        <span className="font-medium">{info.sheet_name}</span>
        <span>
          imported{d ? ` · ${d.row_count} rows × ${d.col_count} cols` : ''}
        </span>
      </p>
    )
  }

  // Duplicate dismissed via "Use existing" — terminal, nothing imported.
  if (dismissed) {
    return (
      <p role="status" className="flex items-center gap-2 rounded px-1.5 py-1 text-xs text-gray-500">
        <span aria-hidden="true">&#10003;</span>
        <span className="font-medium">{info.sheet_name}</span>
        <span>using existing dataset</span>
      </p>
    )
  }

  // Duplicate — the existing "Use existing / Upload anyway" resolver, per sheet.
  if (result?.status === 'duplicate') {
    return (
      <div className="flex flex-wrap items-center gap-2 rounded px-1.5 py-1 text-xs">
        <span className="font-medium text-gray-700">{info.sheet_name}</span>
        <span className="text-amber-700">
          Duplicate{result.existing_filename ? ` of ${result.existing_filename}` : ''}
        </span>
        <button
          type="button"
          onClick={onUseExisting}
          disabled={importing}
          className="rounded border border-gray-300 bg-white px-2 py-0.5 font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Use existing
        </button>
        <button
          type="button"
          onClick={onForce}
          disabled={importing}
          className="rounded border border-amber-300 bg-amber-50 px-2 py-0.5 font-medium text-amber-800 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Upload anyway
        </button>
      </div>
    )
  }

  // Default: checkbox row (with an inline error from the last attempt, if any).
  // Empty sheets are listed but disabled with an "empty" tag — never silently
  // missing (spec/capabilities/multi-sheet-excel.md).
  return (
    <div className="rounded px-1.5 py-1 text-xs hover:bg-gray-50">
      <label
        className={`flex items-center gap-2 ${
          info.empty ? 'cursor-not-allowed text-gray-400' : 'text-gray-700'
        }`}
      >
        <input
          type="checkbox"
          checked={sheet.checked}
          disabled={info.empty || importing}
          onChange={onToggle}
        />
        <span className="font-medium">{info.sheet_name}</span>
        {info.empty ? (
          <span className="rounded border border-gray-200 bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-gray-500">
            empty
          </span>
        ) : (
          <span className="text-gray-400 tabular-nums">
            {info.row_count.toLocaleString()} rows × {info.col_count} cols
          </span>
        )}
        {sheet.importing && (
          <span className="inline-flex items-center gap-1.5 text-blue-600">
            <Spinner /> Importing…
          </span>
        )}
      </label>
      {result?.status === 'error' && (
        <p role="alert" className="mt-0.5 pl-6 text-red-600">
          &#10007; {result.message ?? 'Import failed'}
        </p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Spinner
// ---------------------------------------------------------------------------

function Spinner() {
  return (
    <span
      aria-hidden="true"
      className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"
    />
  )
}
