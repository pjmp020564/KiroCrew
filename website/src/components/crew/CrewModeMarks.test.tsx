import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { CrewGhostBadge, CrewModeComposerChip, CrewStatusDot, CrewWorkerStack } from './CrewModeMarks'
import { OPEN_DELAY_MS } from '../InstantTip'

const reducedMotion = vi.hoisted(() => ({ value: false }))
vi.mock('../../hooks/useReducedMotion', () => ({ useReducedMotion: () => reducedMotion.value }))

describe('CrewModeMarks', () => {
  it('draws the ghost badge on the crew gradient at the size asked', () => {
    render(<CrewGhostBadge size={20} />)
    const badge = screen.getByTestId('crew-ghost-badge')
    expect(badge.className).toContain('crew-grad')
    expect(badge.style.width).toBe('20px')
    expect(badge.getAttribute('aria-hidden')).toBe('true')
  })

  it('the status dot names the state in its tone, as text or for screen readers only', () => {
    const { rerender } = render(<CrewStatusDot group="approval" />)
    let dot = screen.getByTestId('crew-status')
    expect(dot.getAttribute('data-group')).toBe('approval')
    expect(dot.className).toContain('crew-tone-warn')
    expect(dot.textContent).toBe('Approval needed')
    expect(dot.querySelector('.sr-only')).toBeNull()

    rerender(<CrewStatusDot group="waiting" withLabel={false} />)
    dot = screen.getByTestId('crew-status')
    // A waiting worker's dot is hollow; the word stays for a screen reader.
    expect(dot.querySelector('[aria-hidden]')?.className).toContain('border-current')
    expect(dot.querySelector('.sr-only')?.textContent).toBe('Waiting')
  })

  it('the worker stack shows up to `max` ghosts in their tones and counts the rest', () => {
    render(<CrewWorkerStack groups={['approval', 'working', 'done', 'waiting']} max={3} />)
    const stack = screen.getByTestId('crew-worker-stack')
    const ghosts = stack.querySelectorAll('[data-group]')
    expect([...ghosts].map(g => g.getAttribute('data-group'))).toEqual(['approval', 'working', 'done'])
    expect(ghosts[0].className).toContain('crew-tone-warn')
    expect(stack.textContent).toContain('+1')
  })

  it('a full stack shows no count', () => {
    render(<CrewWorkerStack groups={['working']} />)
    expect(screen.getByTestId('crew-worker-stack').textContent).not.toContain('+')
  })

  it('the composer chip is a pressed toggle while it can still be turned off, and a read-only mark after', () => {
    const onTurnOff = vi.fn()
    const { rerender } = render(<CrewModeComposerChip onTurnOff={onTurnOff} />)
    const chip = screen.getByTestId('crew-mode-composer-chip')
    expect(chip.tagName).toBe('BUTTON')
    expect(chip.getAttribute('aria-pressed')).toBe('true')
    expect(chip.getAttribute('title')).toContain('Turn off conductor mode')
    fireEvent.click(chip)
    expect(onTurnOff).toHaveBeenCalledTimes(1)

    rerender(<CrewModeComposerChip />)
    const mark = screen.getByTestId('crew-mode-composer-chip')
    // Read-only: a focusable anchor for its tip, with no toggle state and no native title.
    expect(mark.tagName).toBe('BUTTON')
    expect(mark).not.toHaveAttribute('aria-pressed')
    expect(mark).not.toHaveAttribute('title')
    expect(mark).not.toHaveAttribute('aria-describedby')
    expect(mark.getAttribute('aria-label')).toBe('Conductor mode is on for this chat')
    expect(mark.className).toContain('cursor-default')
    expect(mark.textContent).toBe('')
    expect(mark.querySelector('.lucide-zap')).not.toBeNull()
  })

  describe('the read-only bolt shows its name in a tip', () => {
    beforeEach(() => { vi.useFakeTimers() })
    afterEach(() => { vi.useRealTimers() })

    it('on hover, after the intent delay, and hides on leave', () => {
      render(<CrewModeComposerChip />)
      const mark = screen.getByTestId('crew-mode-composer-chip')
      fireEvent.pointerEnter(mark, { pointerType: 'mouse' })
      fireEvent.mouseEnter(mark)
      expect(screen.queryByRole('tooltip')).toBeNull()
      act(() => { vi.advanceTimersByTime(OPEN_DELAY_MS) })
      expect(screen.getByRole('tooltip')).toHaveTextContent('Conductor mode is on for this chat')
      fireEvent.mouseLeave(mark)
      expect(screen.queryByRole('tooltip')).toBeNull()
    })

    it('on keyboard focus at once, and Escape hides it', () => {
      render(<CrewModeComposerChip />)
      const mark = screen.getByTestId('crew-mode-composer-chip')
      fireEvent.focus(mark)
      expect(screen.getByRole('tooltip')).toHaveTextContent('Conductor mode is on for this chat')
      fireEvent.keyDown(window, { key: 'Escape' })
      expect(screen.queryByRole('tooltip')).toBeNull()
    })

    it('on a touch tap, since the mark has no click to lose', () => {
      render(<CrewModeComposerChip />)
      const mark = screen.getByTestId('crew-mode-composer-chip')
      fireEvent.pointerEnter(mark, { pointerType: 'touch' })
      fireEvent.pointerDown(mark, { pointerType: 'touch' })
      fireEvent.pointerUp(mark, { pointerType: 'touch' })
      fireEvent.mouseEnter(mark)
      fireEvent.mouseDown(mark)
      fireEvent.focus(mark)
      fireEvent.mouseUp(mark)
      fireEvent.click(mark)
      expect(screen.getByRole('tooltip')).toHaveTextContent('Conductor mode is on for this chat')
    })
  })

  it('marks conductor mode with a lightning bolt, not the ghost', () => {
    render(<CrewModeComposerChip />)
    const chip = screen.getByTestId('crew-mode-composer-chip')
    expect(chip.querySelector('.lucide-zap')).not.toBeNull()
    expect(chip.querySelector('[data-testid="kiro-ghost-mark"]')).toBeNull()
  })
})
