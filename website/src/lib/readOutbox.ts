/** Reads the gateway has not confirmed yet (`mc-read-outbox`: slot -> newest time), kept across a reload.
 * Each counts as read until a `stored` echo or a row's `last_read_ts` covers it, and each new socket resends it. */
import { safeGetItem, safeSetItem } from '../utils/safeStorage'
import { newerTs } from './slotReadRelay'
import { readCovers } from '../store/dashboard/unread'

export const READ_OUTBOX_KEY = 'mc-read-outbox'

/** Far above any real number of unconfirmed reads; past it the oldest go. */
export const READ_OUTBOX_MAX = 500

const load = (): Record<string, string> => {
  try {
    const raw = JSON.parse(safeGetItem(READ_OUTBOX_KEY) ?? '{}') as unknown
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {}
    const out: Record<string, string> = {}
    for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
      if (typeof v === 'string' && Number.isFinite(Date.parse(v))) out[k] = v
    }
    return out
  } catch { return {} }
}

/** Load, change and store under one Web Lock all windows share, so no window writes between another's load and
 * store; without Web Locks (jsdom) it runs at once, which one window's synchronous step already makes atomic. */
const update = (change: (entries: Record<string, string>) => boolean): void => {
  const run = () => {
    const entries = load()
    if (!change(entries)) return
    let kept = Object.entries(entries)
    if (kept.length > READ_OUTBOX_MAX) kept = kept.sort(([, a], [, b]) => Date.parse(a) - Date.parse(b)).slice(-READ_OUTBOX_MAX)
    safeSetItem(READ_OUTBOX_KEY, JSON.stringify(Object.fromEntries(kept)))
  }
  const locks = typeof navigator === 'undefined' ? undefined : navigator.locks
  if (typeof locks?.request === 'function') void locks.request(READ_OUTBOX_KEY, run)
  else run()
}

export function queueRead(slot: string, readTs: string | undefined): void {
  if (!slot || !readTs || !Number.isFinite(Date.parse(readTs))) return
  update((entries) => {
    const next = newerTs(entries[slot], readTs)
    if (next === entries[slot]) return false
    entries[slot] = next as string
    return true
  })
}

export function ackRead(slot: string, storedTs: string | undefined): void {
  update((entries) => entries[slot] !== undefined && readCovers(storedTs, entries[slot]) && delete entries[slot])
}

export const queuedReads = (): Record<string, string> => load()

/** Send every kept read once through *send*; a new socket calls this as it opens. */
export function resendKeptReads(send: (slot: string, readTs: string) => void): void {
  for (const [slot, readTs] of Object.entries(load())) send(slot, readTs)
}
