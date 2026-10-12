/**
 * The full chat page applies the opt-in top-down layout (Settings > Chat >
 * `topDownLayout`) at desktop width only. On a phone the thumb reach and the
 * on-screen keyboard sit at the bottom, so the page keeps the bottom composer
 * even with the setting on. ChatPane.topDownDock.test.tsx pins the same gate
 * for a split pane; this file mounts the page itself.
 *
 * The marker is the composer dock root (`data-testid="composer-dock-root"`),
 * the box the page's `topDown` decision positions. In the top-down layout it
 * is anchored to the top (no `bottom-0`, an inline `top`) and carries the
 * top-overlay attribute that tells the transcript to clear it at the top. In
 * the bottom layout it is pinned with `bottom-0`, has no inline `top`, and
 * carries no top-overlay attribute.
 *
 * The harness is the one ChatPage.mobileSingleTopbar.test.tsx uses: the heavy
 * children are stubbed, `useIsMobile` reads a hoisted flag, and the real
 * `loadChatConfig` reads the setting from localStorage.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, act, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Provider } from 'react-redux'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { createTestStore } from './helpers'
import { ThemeProvider } from '../hooks/useTheme'
import { sseSlots, sseConnected } from '../store/dashboardSlice'
import { setActiveSlot } from '../store/chatSlice'
import { TOP_OVERLAY_ATTR, TOP_OVERLAY_GROWS } from '../pages/chat/browserLiveClearance'

vi.mock('framer-motion', async (importOriginal) => {
  const actual = await importOriginal<typeof import('framer-motion')>()
  return {
    ...actual,
    animate: () => ({ stop: () => {} }),
  }
})
vi.mock('react-virtuoso', () => ({ Virtuoso: () => null }))
vi.mock('../components/ChatInput', () => ({ default: () => null }))
vi.mock('../components/WelcomeView', () => ({ default: () => null }))
vi.mock('../components/MarkdownPanel', () => ({ default: () => null }))
vi.mock('../components/MarkdownRenderer', () => ({ default: () => null }))
vi.mock('../components/TypewriterText', () => ({ default: () => null }))
vi.mock('../components/AgentDropdownList', () => ({ default: () => null }))
vi.mock('../components/ModelDropdownList', () => ({ default: () => null }))
vi.mock('../components/InfoTip', () => ({ default: () => null }))
vi.mock('../components/SegmentedControl', () => ({ default: () => null }))
vi.mock('../pages/chat/CollapsibleToolGroup', () => ({ default: () => null }))
vi.mock('../pages/chat/ActivityViewer', () => ({ default: () => null }))
vi.mock('../pages/chat/SessionColorPicker', () => ({ default: () => null }))
vi.mock('../pages/chat', () => ({ ChatFooter: () => null, AssistantMessage: () => null, McpInfoButton: () => null }))
vi.mock('../pages/ChatSidebar', () => ({
  default: () => <div data-testid="sidebar-stub" />,
  SIDEBAR_MIN: 200,
  SIDEBAR_MAX: 500,
}))
vi.mock('../hooks/usePanelState', () => ({ usePanelState: () => ({ isOpen: false, openPanel: vi.fn(), closePanel: vi.fn() }), useDiffPanel: () => ({ isOpen: false, filePath: '', original: '', modified: '', openDiff: vi.fn(), closeDiff: vi.fn() }) }))
vi.mock('../hooks/useBranding', () => ({ useBranding: () => ({ botName: 'Test', avatar: '' }) }))
vi.mock('../hooks/useAgents', () => ({ useAgents: () => ({ agents: [], defaultAgent: null }) }))
vi.mock('../hooks/useFilteredDropdown', () => ({ useFilteredDropdown: () => ({ filtered: [], query: '', setQuery: vi.fn(), selectedIndex: 0, setSelectedIndex: vi.fn(), onKeyDown: vi.fn() }) }))
vi.mock('../hooks/useVoiceInput', () => ({ useVoiceInput: () => ({ recording: false, transcribing: false, toggle: vi.fn() }), voiceInputSupported: false }))
const viewport = vi.hoisted(() => ({ isMobile: false }))
vi.mock('../hooks/useIsMobile', () => ({ useIsMobile: () => viewport.isMobile }))
vi.mock('../api/client', () => ({
  api: Object.fromEntries(
    ['sessions', 'chatSlotDetail', 'createChatSlot', 'deleteChatSlot', 'resumeChatSlot',
      'deleteSession', 'agentDetail', 'approveChatSlot', 'chatSlotAgent', 'chatSlotModel',
      'chatSlotWorkspace', 'models', 'planFromChat', 'renameSlot',
      'resolveApproval', 'screenshot', 'slackChannels', 'slackLink', 'spawnList',
      'stopChatSlot', 'uploadFiles', 'voiceSynthesize', 'workspaces', 'chatSlots',
      'notifications', 'status', 'generateTitle', 'dashboardConfig', 'projectGit',
      'mcpActive', 'mcpServers', 'kirocrewConfig'].map(k => [k, vi.fn().mockResolvedValue(
      k === 'chatSlotDetail' ? { messages: [], has_more: false, total: 0 } : {},
    )]),
  ),
  isAuthBannerShown: vi.fn(() => false),
  ApiError: class ApiError extends Error {
    status: number
    constructor(status: number, message: string) { super(message); this.status = status }
  },
}))

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((q: string) => ({
    matches: false, media: q, onchange: null,
    addListener: vi.fn(), removeListener: vi.fn(),
    addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
  })),
})
globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({}) }) as never
globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as never

import ChatPage from '../pages/ChatPage'

// The key loadChatConfig reads (pages/chat/ChatSettings.tsx).
const CHAT_CONFIG_KEY = 'mc-chat-config'

async function renderChatDock() {
  const store = createTestStore()
  act(() => {
    store.dispatch(sseConnected())
    store.dispatch(sseSlots([{ key: 'slot-0', title: 'Top-down gate' }] as never))
    store.dispatch(setActiveSlot('slot-0'))
  })
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const { findByTestId } = render(
    <QueryClientProvider client={queryClient}>
      <Provider store={store}>
        <ThemeProvider>
          <MemoryRouter initialEntries={['/chat?sid=slot-0']}>
            <Routes><Route path="/chat/:slug?" element={<ChatPage />} /></Routes>
          </MemoryRouter>
        </ThemeProvider>
      </Provider>
    </QueryClientProvider>,
  )
  return findByTestId('composer-dock-root')
}

describe('ChatPage with the top-down layout turned on', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem(CHAT_CONFIG_KEY, JSON.stringify({ topDownLayout: true }))
  })
  afterEach(() => {
    cleanup()
    localStorage.clear()
    viewport.isMobile = false
  })

  it('puts the composer at the top of the page on a desktop screen', async () => {
    viewport.isMobile = false
    const dock = await renderChatDock()
    expect(dock.className.split(/\s+/)).toEqual(expect.arrayContaining(['absolute', 'pointer-events-none']))
    expect(dock.className.split(/\s+/)).not.toContain('bottom-0')
    expect(dock.style.top).not.toBe('')
    expect(dock.getAttribute(TOP_OVERLAY_ATTR)).toBe(TOP_OVERLAY_GROWS)
  })

  it('keeps the composer at the bottom of the page on a phone', async () => {
    viewport.isMobile = true
    const dock = await renderChatDock()
    expect(dock.className.split(/\s+/)).toEqual(expect.arrayContaining(['absolute', 'bottom-0', 'pointer-events-none']))
    expect(dock.style.top).toBe('')
    expect(dock.hasAttribute(TOP_OVERLAY_ATTR)).toBe(false)
  })
})
