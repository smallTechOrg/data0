'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  api,
  ApiError,
  priorityPatch,
  type DashboardCreateResponse,
  type DashboardData,
  type DashboardRecord,
  type DashboardSummary,
  type DashboardWidget,
} from '@/lib/api'
import { toLayoutPayload } from '@/lib/dashboardLayout'
import { CreateDashboardCard } from './CreateDashboardCard'
import { DashboardCanvas, type SaveState } from './DashboardCanvas'
import { SavedDashboards } from './SavedDashboards'

const LAST_OPEN_KEY = 'dashboard:lastOpenId'

function readLastOpen(): string | null {
  try {
    return window.sessionStorage.getItem(LAST_OPEN_KEY)
  } catch {
    return null
  }
}

function writeLastOpen(id: string | null): void {
  try {
    if (id) window.sessionStorage.setItem(LAST_OPEN_KEY, id)
    else window.sessionStorage.removeItem(LAST_OPEN_KEY)
  } catch {
    /* storage unavailable — the convenience is optional */
  }
}

function describe(e: unknown): string {
  return e instanceof ApiError ? e.message : "Couldn't reach the server — is the server running?"
}

/**
 * Dashboard tab (C40, Phase 15): create / saved list / canvas orchestration.
 * Stays mounted across tab switches (hidden), so an open dashboard and an
 * in-flight build survive a trip to another tab.
 */
export function DashboardTab() {
  const [items, setItems] = useState<DashboardSummary[]>([])
  const [listLoading, setListLoading] = useState(true)
  const [listError, setListError] = useState<string | null>(null)
  const [record, setRecord] = useState<DashboardRecord | null>(null)
  const [data, setData] = useState<DashboardData | null>(null)
  const [dataError, setDataError] = useState<string | null>(null)
  const [opening, setOpening] = useState(false)
  const [openError, setOpenError] = useState<string | null>(null)
  const [saveState, setSaveState] = useState<SaveState>('idle')
  const [saveMessage, setSaveMessage] = useState<string | null>(null)
  const [building, setBuilding] = useState(false)

  // Last layout the server confirmed — the revert target on a failed save.
  const savedWidgets = useRef<DashboardWidget[] | null>(null)
  // Monotonic token: only the newest save/open may touch state.
  const saveSeq = useRef(0)
  const openSeq = useRef(0)
  const pending = useRef<DashboardWidget[] | null>(null)

  const refreshList = useCallback(async () => {
    try {
      const list = await api.listDashboards()
      setItems(list)
      setListError(null)
      return list
    } catch (e) {
      setListError(describe(e))
      return null
    } finally {
      setListLoading(false)
    }
  }, [])

  const open = useCallback(async (id: string) => {
    const seq = ++openSeq.current
    setOpening(true)
    setOpenError(null)
    setData(null)
    setDataError(null)
    setSaveState('idle')
    try {
      const rec = await api.getDashboard(id)
      if (seq !== openSeq.current) return
      setRecord(rec)
      savedWidgets.current = rec.spec.widgets
      writeLastOpen(id)
      try {
        const d = await api.getDashboardData(id)
        if (seq === openSeq.current) setData(d)
      } catch (e) {
        if (seq === openSeq.current) setDataError(`Couldn't load widget data. ${describe(e)}`)
      }
    } catch (e) {
      if (seq === openSeq.current) {
        setRecord(null)
        setOpenError(describe(e))
        if (e instanceof ApiError && e.status === 404) writeLastOpen(null)
      }
    } finally {
      if (seq === openSeq.current) setOpening(false)
    }
  }, [])

  // On mount: load the list and re-open the last dashboard (else the newest).
  useEffect(() => {
    void (async () => {
      const list = await refreshList()
      if (!list || list.length === 0) return
      const last = readLastOpen()
      const target = list.find(d => d.id === last) ?? list[0]
      void open(target.id)
    })()
  }, [refreshList, open])

  const onBuilt = useCallback(
    (result: DashboardCreateResponse) => {
      openSeq.current += 1
      setOpening(false)
      setOpenError(null)
      setRecord(result.dashboard)
      setData(result.data)
      setDataError(null)
      setSaveState('idle')
      savedWidgets.current = result.dashboard.spec.widgets
      writeLastOpen(result.dashboard.id)
      void refreshList()
    },
    [refreshList],
  )

  const persist = useCallback(
    async (id: string, widgets: DashboardWidget[]) => {
      const seq = ++saveSeq.current
      pending.current = widgets
      setSaveState('saving')
      setSaveMessage(null)
      try {
        const updated = await api.patchDashboard(id, { layout: toLayoutPayload(widgets) })
        if (seq !== saveSeq.current) return
        savedWidgets.current = updated.spec.widgets
        pending.current = null
        setRecord(prev => (prev && prev.id === updated.id ? { ...prev, ...updated } : prev))
        setSaveState('saved')
        void refreshList()
      } catch (e) {
        if (seq !== saveSeq.current) return
        // Revert to the last saved layout; keep `pending` so Retry can resend.
        const back = savedWidgets.current
        if (back) {
          setRecord(prev =>
            prev && prev.id === id ? { ...prev, spec: { ...prev.spec, widgets: back } } : prev,
          )
        }
        setSaveMessage(describe(e))
        setSaveState('error')
      }
    },
    [refreshList],
  )

  const onLayoutChange = useCallback(
    (widgets: DashboardWidget[]) => {
      if (!record) return
      setRecord({ ...record, spec: { ...record.spec, widgets } }) // optimistic
      void persist(record.id, widgets)
    },
    [record, persist],
  )

  const onRetrySave = useCallback(() => {
    if (!record || !pending.current) return
    const widgets = pending.current
    setRecord({ ...record, spec: { ...record.spec, widgets } })
    void persist(record.id, widgets)
  }, [record, persist])

  const onRename = useCallback(
    async (title: string) => {
      if (!record) return
      const updated = await api.patchDashboard(record.id, { title })
      setRecord(prev => (prev && prev.id === updated.id ? { ...prev, ...updated } : prev))
      void refreshList()
    },
    [record, refreshList],
  )

  // Throws on failure: the panel stays open with the error and the draft order.
  const onSavePriority = useCallback(
    async (order: string[], rearrange: boolean) => {
      if (!record) return
      saveSeq.current += 1 // an in-flight layout save must not overwrite this result
      const updated = await api.patchDashboard(record.id, priorityPatch(order, rearrange))
      savedWidgets.current = updated.spec.widgets
      pending.current = null
      setRecord(prev => (prev && prev.id === updated.id ? { ...prev, ...updated } : prev))
      setSaveState('idle')
      void refreshList()
    },
    [record, refreshList],
  )

  const onDelete = useCallback(
    async (id: string) => {
      try {
        await api.deleteDashboard(id)
      } catch (e) {
        setListError(describe(e))
        return
      }
      if (record?.id === id) {
        openSeq.current += 1
        setRecord(null)
        setData(null)
        setSaveState('idle')
        writeLastOpen(null)
      }
      const list = await refreshList()
      if (record?.id === id && list && list.length > 0) void open(list[0].id)
    },
    [record, refreshList, open],
  )

  return (
    <div className="dash-layout">
      <div className="space-y-4">
        <CreateDashboardCard onBuilt={onBuilt} onBuildingChange={setBuilding} />
        <SavedDashboards
          items={items}
          loading={listLoading}
          error={listError}
          activeId={record?.id ?? null}
          onOpen={id => void open(id)}
          onDelete={onDelete}
        />
      </div>

      <div className="min-w-0">
        {openError && (
          <p role="alert" className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {openError}
          </p>
        )}
        {record ? (
          <DashboardCanvas
            record={record}
            data={data}
            dataError={dataError}
            saveState={saveState}
            saveMessage={saveMessage}
            onLayoutChange={onLayoutChange}
            onRetrySave={onRetrySave}
            onRename={onRename}
            onSavePriority={onSavePriority}
          />
        ) : building || opening ? (
          <div
            role="status"
            className="rounded-lg border border-dashed border-gray-300 bg-white px-6 py-16 text-center text-sm text-gray-500"
          >
            {building ? 'Designing your dashboard…' : 'Opening dashboard…'}
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-gray-300 bg-white px-6 py-16 text-center text-sm text-gray-500">
            Pick a dataset, describe the dashboard you want, press Build.
          </div>
        )}
      </div>
    </div>
  )
}
