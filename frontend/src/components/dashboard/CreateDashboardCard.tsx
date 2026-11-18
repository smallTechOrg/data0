'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, type DashboardCreateResponse, type DatasetSummary } from '@/lib/api'
import { UploadCard } from '@/components/analyse/UploadCard'

const MAX_COMMAND = 1000

/** Create card: dataset select + "or upload a file" + command + Build (C40). */
export function CreateDashboardCard({
  onBuilt,
  onBuildingChange,
}: {
  onBuilt: (result: DashboardCreateResponse) => void
  onBuildingChange?: (building: boolean) => void
}) {
  const [datasets, setDatasets] = useState<DatasetSummary[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [datasetId, setDatasetId] = useState('')
  const [command, setCommand] = useState('')
  const [building, setBuilding] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const knownIds = useRef<string[]>([])

  const refresh = useCallback(async (autoSelectNew: boolean) => {
    try {
      const list = await api.listDatasets()
      setLoadError(null)
      const newOnes = autoSelectNew ? list.filter(d => !knownIds.current.includes(d.id)) : []
      knownIds.current = list.map(d => d.id)
      setDatasets(list)
      setDatasetId(prev => {
        if (newOnes.length > 0) return newOnes[0].id
        if (prev && list.some(d => d.id === prev)) return prev
        return list[0]?.id ?? ''
      })
    } catch {
      setLoadError("Couldn't load datasets — is the server running?")
      setDatasets(prev => prev ?? [])
    }
  }, [])

  useEffect(() => {
    void refresh(false)
  }, [refresh])

  const trimmed = command.trim()
  const canBuild = !building && !!datasetId && trimmed.length > 0 && trimmed.length <= MAX_COMMAND

  const build = async () => {
    if (!canBuild) return
    setBuilding(true)
    onBuildingChange?.(true)
    setError(null)
    try {
      const result = await api.createDashboard(datasetId, { command: trimmed })
      onBuilt(result)
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Couldn't reach the server — is the server running?",
      )
    } finally {
      setBuilding(false)
      onBuildingChange?.(false)
    }
  }

  const noDatasets = datasets !== null && datasets.length === 0

  return (
    <section
      className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
      aria-labelledby="dash-create-h"
    >
      <h2 id="dash-create-h" className="text-sm font-semibold text-gray-800">
        Create a dashboard
      </h2>

      <label htmlFor="dash-dataset" className="mt-3 block text-xs font-medium text-gray-600">
        Data
      </label>
      <select
        id="dash-dataset"
        value={datasetId}
        disabled={building || !datasets || noDatasets}
        onChange={e => setDatasetId(e.target.value)}
        className="mt-1 w-full rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-800 disabled:opacity-60"
      >
        {datasets === null && <option value="">Loading datasets…</option>}
        {noDatasets && <option value="">No datasets yet</option>}
        {datasets?.map(d => (
          <option key={d.id} value={d.id}>
            {d.filename} · {d.row_count}×{d.col_count}
          </option>
        ))}
      </select>
      {noDatasets && <p className="mt-1 text-xs text-gray-500">Upload a file to get started.</p>}
      {loadError && (
        <p role="alert" className="mt-1 text-xs text-red-700">
          {loadError}
        </p>
      )}

      <details className="mt-2">
        <summary className="cursor-pointer text-xs font-medium text-indigo-700">
          or upload a file
        </summary>
        <div className="mt-2">
          <UploadCard onUploaded={() => void refresh(true)} />
        </div>
      </details>

      <label htmlFor="dash-command" className="mt-3 block text-xs font-medium text-gray-600">
        What should the dashboard show?
      </label>
      <textarea
        id="dash-command"
        value={command}
        rows={4}
        maxLength={MAX_COMMAND}
        disabled={building}
        placeholder="e.g. Show revenue by region, a monthly trend and my top 10 customers"
        onChange={e => setCommand(e.target.value)}
        onKeyDown={e => {
          if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault()
            void build()
          }
        }}
        className="mt-1 w-full resize-y rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-800 disabled:opacity-60"
      />
      <div className="text-right text-[11px] text-gray-400">
        {command.length}/{MAX_COMMAND}
      </div>

      <button
        type="button"
        onClick={() => void build()}
        disabled={!canBuild}
        className="mt-1 w-full rounded-md bg-indigo-700 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-800 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {building ? 'Building…' : 'Build dashboard'}
      </button>

      {building && (
        <p role="status" className="mt-2 flex items-center gap-2 text-xs text-gray-600">
          <span
            aria-hidden="true"
            className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-indigo-300 border-t-indigo-700"
          />
          Profiling your data and designing the dashboard… (usually 5–20 s)
        </p>
      )}
      {error && (
        <p
          role="alert"
          className="mt-2 rounded-md border border-red-200 bg-red-50 px-2 py-1.5 text-xs text-red-700"
        >
          {error}
        </p>
      )}
    </section>
  )
}
