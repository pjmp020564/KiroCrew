/** The small marks every Crew Mode surface shares: the solid ghost badge,
 *  the composer bolt, a worker's state dot and a stack of tiny worker ghosts
 *  coloured by state. Colours are theme tokens (`styles/crew-mode.css`,
 *  `lib/crewWorkers.ts`), so light and dark themes follow without a branch here. */
import { motion, useReducedMotion } from 'framer-motion'
import { KiroGhostMark } from '../KiroGhostMark'
import { InstantTip, useInstantTip } from '../InstantTip'
import { Zap } from 'lucide-react'
import { i18nT } from '../../i18n/t'
import { CREW_GROUP_LABEL_KEY, CREW_GROUP_TONE, type CrewWorkerGroup } from '../../lib/crewWorkers'

/** The solid ghost on the crew gradient: the breadcrumb's root. */
export function CrewGhostBadge({ size = 28 }: { size?: number }) {
  return (
    <span aria-hidden="true" data-testid="crew-ghost-badge" className="crew-grad shrink-0 rounded-full grid place-items-center" style={{ width: size, height: size }}>
      <KiroGhostMark size={Math.round(size * 0.5)} className="inline-block shrink-0 text-aim-fg" />
    </span>
  )
}

/** A worker's state as a dot and a word. The word is the state, not a hint. */
export function CrewStatusDot({ group, withLabel = true, className = '' }: { group: CrewWorkerGroup; withLabel?: boolean; className?: string }) {
  const label = i18nT(CREW_GROUP_LABEL_KEY[group])
  return (
    <span data-testid="crew-status" data-group={group} className={`inline-flex items-center gap-1 text-[12px] shrink-0 ${CREW_GROUP_TONE[group]} ${className}`}>
      <span aria-hidden="true" className={`w-2 h-2 rounded-full ${group === 'waiting' ? 'border border-current' : 'bg-current'}`} />
      {withLabel ? <span>{label}</span> : <span className="sr-only">{label}</span>}
    </span>
  )
}

/** Up to `max` tiny worker ghosts, one per worker, needs-you first. */
export function CrewWorkerStack({ groups, max = 6 }: { groups: CrewWorkerGroup[]; max?: number }) {
  const shown = groups.slice(0, max)
  const extra = groups.length - shown.length
  return (
    <span aria-hidden="true" data-testid="crew-worker-stack" className="inline-flex items-center -space-x-1">
      {shown.map((g, i) => (
        // Tinted by the worker's own state colour, so the stack reads at a glance.
        <span key={i} data-group={g} className={`w-[18px] h-[18px] rounded-full grid place-items-center border border-current ring-2 ring-bg ${CREW_GROUP_TONE[g]}`}
          style={{ backgroundColor: 'color-mix(in srgb, currentColor 22%, var(--bg-elevated))' }}>
          <KiroGhostMark size={11} className="inline-block shrink-0" />
        </span>
      ))}
      {extra > 0 && <span className="pl-2 text-[11px] text-muted">+{extra}</span>}
    </span>
  )
}

/** One coloured bolt before a Conductor mode session title. */
export function ConductorModeTitleMark() {
  return (
    <span
      className="lucide-inline mr-1 shrink-0 conductor-mode-accent"
      role="img"
      aria-label={i18nT('components.crewMode.chip_off')}
      title={i18nT('components.crewMode.chip_off')}
      data-testid="conductor-mode-title-mark"
    >
      <Zap size={14} aria-hidden="true" />
    </span>
  )
}

/** The composer's Conductor mode mark is one lightning bolt. With
 *  `onTurnOff` (no message sent yet) it is a pressed icon button. Without it,
 *  it is a read-only status mark. Its accessible name keeps the hidden meaning.
 *
 *  The read-only mark shows that name in an `InstantTip` on hover, keyboard
 *  focus and touch tap, so a sighted person can learn what the bolt means. It
 *  is a focusable button with no click action, as the resource posture chip
 *  is, so a tap has no click to lose (`openOnTap`). The bubble repeats the
 *  accessible name, so the anchor carries no `aria-describedby`. */
export function CrewModeComposerChip({ onTurnOff }: { onTurnOff?: () => void } = {}) {
  const reduceMotion = useReducedMotion()
  const { tip, tipHandlers, tipId } = useInstantTip({ openOnTap: true })
  if (onTurnOff) {
    return (
      <motion.button
        type="button"
        data-testid="crew-mode-composer-chip"
        aria-label={i18nT('components.crewMode.chip_off')}
        aria-pressed={true}
        title={i18nT('components.crewMode.chip_hint_on')}
        onClick={onTurnOff}
        initial={reduceMotion ? { opacity: 0 } : false}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.2 }}
        className="inline-grid h-7 w-7 place-items-center rounded-md shrink-0 cursor-pointer hover:bg-bg-hover mc-touch-hit"
      >
        <Zap size={16} aria-hidden="true" className="shrink-0 conductor-mode-accent" />
      </motion.button>
    )
  }
  const label = i18nT('components.crewMode.composer_chip_label')
  const { 'aria-describedby': _bubbleId, ...handlers } = tipHandlers
  void _bubbleId
  return (
    <>
      <motion.button
        type="button"
        data-testid="crew-mode-composer-chip"
        aria-label={label}
        {...handlers}
        initial={reduceMotion ? { opacity: 0 } : false}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.2 }}
        className="inline-grid h-7 w-7 place-items-center shrink-0 cursor-default select-none focus-visible:outline-2 focus-visible:outline-accent"
      >
        <Zap size={16} aria-hidden="true" className="shrink-0 conductor-mode-accent" />
      </motion.button>
      <InstantTip tip={tip} tipId={tipId} className="w-max max-w-[20rem] break-words">{label}</InstantTip>
    </>
  )
}
