/**
 * Artifact Viewer behaviour, with emphasis on the isolation guarantees for generated HTML.
 *
 * The assertions below encode the security contract: HTML goes into a sandboxed iframe via
 * srcdoc with scripting disabled, and never into the parent document's innerHTML.
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { ArtifactViewer } from '../components/ArtifactViewer'
import type { Artifact } from '../types/api'

function makeArtifact(overrides: Partial<Artifact> = {}): Artifact {
  return {
    id: 'artifact-1',
    type: 'html',
    title: 'Activation Landing Page',
    content: '<!DOCTYPE html><html><body><h1>Activation</h1></body></html>',
    sanitised: true,
    sanitiser_report: {},
    created_at: '2026-01-01T10:00:00Z',
    ...overrides,
  }
}

const noop = () => {}

describe('ArtifactViewer isolation of generated HTML', () => {
  it('renders HTML inside an iframe using srcdoc', () => {
    const artifact = makeArtifact()
    const { container } = render(
      <ArtifactViewer artifact={artifact} busy={false} canGenerate onGenerate={noop} />,
    )

    const iframe = container.querySelector('iframe')
    expect(iframe).not.toBeNull()
    expect(iframe).toHaveAttribute('srcdoc', artifact.content)
  })

  it('sandboxes the frame without allow-scripts so script cannot execute', () => {
    const { container } = render(
      <ArtifactViewer artifact={makeArtifact()} busy={false} canGenerate onGenerate={noop} />,
    )

    const iframe = container.querySelector('iframe')!
    const sandbox = iframe.getAttribute('sandbox')

    expect(sandbox).not.toBeNull()
    expect(sandbox).not.toContain('allow-scripts')
    expect(sandbox).not.toContain('allow-top-navigation')
    expect(sandbox).not.toContain('allow-popups')
    expect(sandbox).not.toContain('allow-forms')
  })

  it('never injects artifact HTML into the parent document', () => {
    // A payload that would execute if it were placed in the parent DOM.
    const hostile = '<img src=x onerror="window.__pwned = true">'
    const { container } = render(
      <ArtifactViewer
        artifact={makeArtifact({ content: hostile })}
        busy={false}
        canGenerate
        onGenerate={noop}
      />,
    )

    // The markup exists only as the iframe's srcdoc attribute value, not as live parent DOM.
    expect(container.querySelector('img')).toBeNull()
    expect((window as unknown as Record<string, unknown>).__pwned).toBeUndefined()
    expect(container.querySelector('iframe')).toHaveAttribute('srcdoc', hostile)
  })

  it('gives the frame an accessible title naming the artifact', () => {
    render(<ArtifactViewer artifact={makeArtifact()} busy={false} canGenerate onGenerate={noop} />)

    expect(screen.getByTitle('Rendered artifact: Activation Landing Page')).toBeInTheDocument()
  })
})

describe('ArtifactViewer markdown rendering', () => {
  it('renders markdown as formatted HTML rather than raw text', () => {
    const artifact = makeArtifact({
      type: 'markdown',
      title: 'Strategy Doc',
      content: '# Strategy\n\nFocus on **activation** first.',
    })
    const { container } = render(
      <ArtifactViewer artifact={artifact} busy={false} canGenerate onGenerate={noop} />,
    )

    expect(container.querySelector('h1')?.textContent).toBe('Strategy')
    expect(container.querySelector('strong')?.textContent).toBe('activation')
    // Markdown artifacts render directly, not in a frame.
    expect(container.querySelector('iframe')).toBeNull()
  })

  it('sanitises script tags out of markdown artifacts', () => {
    const artifact = makeArtifact({
      type: 'markdown',
      content: 'Plan\n\n<script>window.__pwned = true</script>',
    })
    const { container } = render(
      <ArtifactViewer artifact={artifact} busy={false} canGenerate onGenerate={noop} />,
    )

    expect(container.querySelector('script')).toBeNull()
    expect((window as unknown as Record<string, unknown>).__pwned).toBeUndefined()
  })
})

describe('ArtifactViewer states', () => {
  it('shows an empty state explaining how to produce an artifact', () => {
    render(<ArtifactViewer artifact={null} busy={false} canGenerate onGenerate={noop} />)

    expect(screen.getByText('Nothing generated yet')).toBeInTheDocument()
  })

  it('shows a loading state while generating', () => {
    render(<ArtifactViewer artifact={null} busy canGenerate onGenerate={noop} />)

    expect(screen.getByRole('status')).toHaveTextContent('Generating artifact…')
  })

  it('discloses what the sanitiser removed', () => {
    const artifact = makeArtifact({
      sanitiser_report: {
        modified: true,
        removed_tags: { script: 2 },
        removed_attributes: { onclick: 1 },
        removed_urls: 1,
        css_rules_stripped: 1,
        comments_removed: 0,
      },
    })
    render(<ArtifactViewer artifact={artifact} busy={false} canGenerate onGenerate={noop} />)

    expect(screen.getByText('Unsafe markup was removed before rendering')).toBeInTheDocument()
    expect(screen.getByText(/<script> ×2/)).toBeInTheDocument()
    expect(screen.getByText(/onclick ×1/)).toBeInTheDocument()
  })

  it('does not show a sanitiser note for clean artifacts', () => {
    render(<ArtifactViewer artifact={makeArtifact()} busy={false} canGenerate onGenerate={noop} />)

    expect(screen.queryByText('Unsafe markup was removed before rendering')).toBeNull()
  })
})

describe('ArtifactViewer generation form', () => {
  it('submits the chosen format and instruction', async () => {
    const onGenerate = vi.fn()
    const user = userEvent.setup()
    render(<ArtifactViewer artifact={null} busy={false} canGenerate onGenerate={onGenerate} />)

    await user.type(screen.getByLabelText('Describe the artifact to generate'), 'Landing page')
    await user.click(screen.getByRole('button', { name: 'Generate' }))

    expect(onGenerate).toHaveBeenCalledWith('html', 'Landing page')
  })

  it('disables generation until a session exists', () => {
    render(
      <ArtifactViewer artifact={null} busy={false} canGenerate={false} onGenerate={noop} />,
    )

    expect(screen.getByRole('button', { name: 'Generate' })).toBeDisabled()
    expect(screen.getByLabelText('Describe the artifact to generate')).toBeDisabled()
  })

  it('will not submit an empty instruction', async () => {
    const onGenerate = vi.fn()
    render(<ArtifactViewer artifact={null} busy={false} canGenerate onGenerate={onGenerate} />)

    expect(screen.getByRole('button', { name: 'Generate' })).toBeDisabled()
    expect(onGenerate).not.toHaveBeenCalled()
  })
})
