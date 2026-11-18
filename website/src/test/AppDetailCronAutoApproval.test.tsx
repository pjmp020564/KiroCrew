/**
 * The app's page names the manifest crons that run without asking.
 *
 * A cron an app's manifest declares with `approval_mode: "auto"` has its tool
 * calls approved without a prompt, after the deny rules and the security policy.
 * The permissions card lists those jobs by name, so the owner reads it before
 * installing or enabling the app. A manifest whose crons ask for nothing shows no
 * box, and the store's manifest normalizer keeps only the string "auto".
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('../i18n/t', () => ({
  i18nT: (key: string, vars?: Record<string, unknown>) =>
    vars && Object.keys(vars).length ? `${key} ${Object.values(vars).join(' ')}` : key,
}))

import { CronAutoApprovalBox } from '../pages/AppDetailGrantBoxes'

describe('CronAutoApprovalBox', () => {
  it('names each job that runs auto, and only those', () => {
    render(
      <CronAutoApprovalBox
        crons={[
          { name: 'rotation-check', approval_mode: 'auto' },
          { name: 'digest' },
          { name: 'dispatch', approval_mode: 'auto' },
        ]}
      />,
    )
    const box = screen.getByTestId('cron-auto-approval')
    expect(box.textContent).toContain('pages.appDetailPage.cron_auto_approval_desc')
    expect(box.textContent).toContain('rotation-check')
    expect(box.textContent).toContain('dispatch')
    expect(box.textContent).not.toContain('digest')
  })

  it('renders nothing when no job runs auto', () => {
    const { container } = render(<CronAutoApprovalBox crons={[{ name: 'digest' }, { name: 'poll', approval_mode: 'ask' }]} />)
    expect(container.innerHTML).toBe('')
  })

  it('renders nothing for a manifest with no crons', () => {
    const { container } = render(<CronAutoApprovalBox crons={undefined} />)
    expect(container.innerHTML).toBe('')
  })
})
