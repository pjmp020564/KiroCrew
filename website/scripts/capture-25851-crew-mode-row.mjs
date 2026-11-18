/**
 * Screenshot harness for the simplified Conductor mode marks.
 *
 * Runs the REAL built SPA (website/dist) behind the shared in-process static
 * server and answers every /api/** call from fixtures via Playwright route
 * interception -- gateway-free, no kiro-cli, no dashboard auth. The root row
 * carries the `crew_mode_root` stamp the gateway writes, so the row and composer
 * render from the same state they read live.
 *
 * Frames (1280x800, 2x), one per theme:
 *   <prefix>-<theme>.png        the Conductor mode Sessions row
 *   <prefix>-<theme>-full.png   the full chat and composer
 *   <prefix>-dark-tip.png      the focused composer bolt and its name
 *   <prefix>-dark-mobile.png   the narrow chat composer
 *   <prefix>-dark-drawer.png   the narrow Sessions drawer
 *
 * Usage (in website/): node scripts/capture-25851-crew-mode-row.mjs <outDir> <prefix>
 */
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { serveDist } from './lib/serve-dist.mjs'
import { logPageProblems, stubDashboardApi, json } from './lib/stub-dashboard-api.mjs'

const OUT = resolve(process.argv[2] || '../temp-screenshots/25851')
const PREFIX = process.argv[3] || 'after'
mkdirSync(OUT, { recursive: true })

const ROOT = 'chat-root'
const T0 = '2026-10-28T08:00:00Z'
const row = (key, title, extra = {}) => ({
  key, title, messages: 2, running: false, agent: 'kirocrew', agent_kind: 'template', mode: '', origin: 'user',
  memory_mode: 'persistent', created: T0, last_ts: T0, folder_id: '', workspace: 'default', ...extra,
})
const slots = [
  row(ROOT, 'Write three haiku about the sea, trees and rain', { agent: 'kirocrew-conductor', crew_mode_root: true, last_ts: '2026-10-28T08:12:00Z' }),
  row('chat-w1', 'Rain haiku', { agent: 'kirocrew-worker', crew_root: ROOT, created_by: ROOT, last_ts: '2026-10-28T08:11:00Z' }),
  row('chat-w2', 'Tree haiku', { agent: 'kirocrew-worker', crew_root: ROOT, created_by: ROOT, last_ts: '2026-10-28T08:09:00Z' }),
  row('chat-plain', 'Plan the release notes', { last_ts: '2026-10-28T07:50:00Z' }),
]
const CATALOG = {
  agents: ['kirocrew', 'kirocrew-conductor', 'kirocrew-worker'].map(name => ({ name, selection_kind: 'template', kiro_agent: '', workspace: 'default', memory_store: 'default', source: 'builtin' })),
  default_agent: 'kirocrew', crew_mode_agent: 'kirocrew-conductor', conductor_agents: ['kirocrew-conductor'],
}
const WORKERS = {
  root: ROOT,
  workers: [
    { key: 'chat-w1', title: 'Rain haiku', agent: 'kirocrew-worker', status: 'idle', group: 'done', last_activity: '2026-10-28T08:11:00Z', created_by: ROOT, dispatched_by: ROOT },
    { key: 'chat-w2', title: 'Tree haiku', agent: 'kirocrew-worker', status: 'idle', group: 'done', last_activity: '2026-10-28T08:09:00Z', created_by: ROOT, dispatched_by: ROOT },
  ],
}

const extra = async (path, route) => {
  if (path === '/api/agents/catalog') { await json(route, CATALOG); return true }
  if (path === `/api/chat/slots/${ROOT}/crew-workers`) { await json(route, WORKERS); return true }
  if (path === `/api/chat/slots/${ROOT}/crew-timeline`) { await json(route, { root: ROOT, lanes: [], gaps: [] }); return true }
  if (path === `/api/chat/slots/${ROOT}`) {
    await json(route, {
      messages: [
        { role: 'user', content: 'Write three haiku about the sea, trees and rain.', ts: '2026-10-28T08:01:00Z' },
        { role: 'assistant', content: 'The crew finished all three haiku.', ts: '2026-10-28T08:12:00Z' },
      ],
      has_more: false,
      total: 2,
    })
    return true
  }
  if (path.startsWith('/api/chat/slots/') && !path.slice('/api/chat/slots/'.length).includes('/')) {
    await json(route, { messages: [], has_more: false, total: 0 }); return true
  }
  if (path === '/api/sessions') { await json(route, { sessions: [], has_more: false }); return true }
  if (path === '/api/chat/pins') { await json(route, { pins: [] }); return true }
  return false
}

let failures = 0
const assert = (ok, label) => { console.log(`ASSERT ${ok ? 'ok  ' : 'FAIL'}: ${label}`); if (!ok) failures++ }

async function main() {
  const { srv, base } = await serveDist()
  const { LD_LIBRARY_PATH: _mise, ...env } = process.env
  const browser = await chromium.launch({ env })
  for (const theme of ['dark', 'light']) {
    const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 2 })
    const page = await context.newPage()
    logPageProblems(page)
    await stubDashboardApi(page, {
      slots,
      theme,
      localStorageEntries: {
        'mc-active-slot-chat': ROOT,
        'mc-lang': 'en',
        'kc-locked-controls': '[]',
      },
      extra,
    })
    await page.goto(`${base}/chat?sid=${ROOT}`, { waitUntil: 'domcontentloaded' })
    const card = page.locator('[data-crew-root="true"]').first()
    await card.waitFor({ timeout: 20_000 })
    await page.waitForTimeout(1000)
    const mark = card.getByTestId('conductor-mode-title-mark')
    const composerMark = page.getByTestId('crew-mode-composer-chip')
    const badge = await card.getByTestId('crew-ghost-badge').count()
    const modeText = await card.getByText('Conductor mode', { exact: true }).count()
    const titleWidth = await card.locator('[data-session-title]').first().evaluate(el => el.getBoundingClientRect().width)
    console.log(`${PREFIX}/${theme}: badge=${badge} mode-text=${modeText} title-width=${titleWidth.toFixed(1)}px`)
    if (PREFIX === 'after') {
      assert(badge === 0, `${theme}: no ghost badge before the title`)
      assert(modeText === 0, `${theme}: no repeated Conductor mode text`)
      assert((await mark.count()) === 1, `${theme}: one bolt before the title`)
      assert((await mark.evaluate(el => el.parentElement?.hasAttribute('data-session-title'))) === true, `${theme}: bolt is inside the title line`)
      assert((await composerMark.textContent()) === '', `${theme}: composer mark is only a bolt`)
    }
    // The row and the rows around it: the whole session-list width, a little above and below.
    const box = await card.boundingBox()
    const x = Math.max(0, box.x - 12)
    const y = Math.max(0, box.y - 40)
    await page.screenshot({ path: `${OUT}/${PREFIX}-${theme}.png`, clip: { x, y, width: box.width + 24, height: box.height + 140 } })
    await page.screenshot({ path: `${OUT}/${PREFIX}-${theme}-full.png` })
    if (theme === 'dark') {
      await composerMark.focus()
      const tip = page.getByRole('tooltip')
      await tip.waitFor({ timeout: 5_000 })
      assert((await tip.textContent()) === 'Conductor mode is on for this chat', 'dark: focused composer bolt names the mode')
      await page.screenshot({ path: `${OUT}/${PREFIX}-dark-tip.png` })
    }
    await context.close()

    if (theme === 'dark') {
      const mobileContext = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 })
      const mobile = await mobileContext.newPage()
      logPageProblems(mobile)
      await stubDashboardApi(mobile, {
        slots,
        theme,
        localStorageEntries: {
          'mc-active-slot-chat': ROOT,
          'mc-lang': 'en',
          'kc-locked-controls': '[]',
        },
        extra,
      })
      await mobile.goto(`${base}/chat?sid=${ROOT}`, { waitUntil: 'domcontentloaded' })
      await mobile.getByTestId('crew-mode-composer-chip').waitFor({ timeout: 20_000 })
      await mobile.waitForTimeout(800)
      await mobile.screenshot({ path: `${OUT}/${PREFIX}-dark-mobile.png` })
      await mobile.getByTestId('mobile-topbar-sessions-toggle').click()
      await mobile.locator('[data-crew-root="true"]').first().waitFor({ timeout: 10_000 })
      await mobile.screenshot({ path: `${OUT}/${PREFIX}-dark-drawer.png` })
      await mobileContext.close()
    }
  }
  await browser.close()
  srv.close()
  console.log(failures ? `FAILED: ${failures} assertion(s)` : 'all assertions passed')
  process.exit(failures ? 1 : 0)
}

main().catch(e => { console.error(e); process.exit(2) })
