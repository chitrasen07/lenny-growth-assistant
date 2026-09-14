/**
 * Citation display.
 *
 * The point of these tests is traceability: a reviewer must be able to see which sources
 * the answer used, read the underlying excerpt, and never be shown invented metadata.
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { SourceList } from '../components/SourceList'
import type { Source } from '../types/api'

function makeSource(overrides: Partial<Source> = {}): Source {
  return {
    chunk_id: 'chunk-1',
    transcript_id: 'transcript-1',
    title: 'Episode with a guest',
    episode: 'Episode 12',
    guest: 'A Guest',
    source_url: 'https://example.com/episode-12',
    source_file: 'episode-12.txt',
    chunk_index: 3,
    speaker: 'Guest',
    excerpt: 'The single biggest activation lever was reducing time to first value.',
    distance: 0.18,
    marker: 1,
    cited: true,
    ...overrides,
  }
}

describe('SourceList', () => {
  it('renders nothing when there are no sources', () => {
    const { container } = render(<SourceList sources={[]} />)

    expect(container).toBeEmptyDOMElement()
  })

  it('shows the episode title, episode and guest when present', () => {
    render(<SourceList sources={[makeSource()]} />)

    expect(screen.getByText('Episode with a guest')).toBeInTheDocument()
    expect(screen.getByText('Episode 12')).toBeInTheDocument()
    expect(screen.getByText('Guest: A Guest')).toBeInTheDocument()
  })

  it('omits optional metadata the transcript did not declare instead of inventing it', () => {
    render(
      <SourceList
        sources={[makeSource({ episode: null, guest: null, source_url: null, speaker: null })]}
      />,
    )

    expect(screen.queryByText(/^Guest:/)).toBeNull()
    expect(screen.queryByRole('link')).toBeNull()
    // The title is still plain text, not a fabricated link.
    expect(screen.getByText('Episode with a guest')).toBeInTheDocument()
  })

  it('links to the source URL safely in a new tab', () => {
    render(<SourceList sources={[makeSource()]} />)

    const link = screen.getByRole('link', { name: 'Episode with a guest' })
    expect(link).toHaveAttribute('href', 'https://example.com/episode-12')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('reveals the underlying excerpt and its provenance on demand', async () => {
    const user = userEvent.setup()
    render(<SourceList sources={[makeSource()]} />)

    expect(screen.queryByText(/time to first value/)).toBeNull()

    await user.click(screen.getByRole('button', { name: 'Show excerpt' }))

    expect(screen.getByText(/time to first value/)).toBeInTheDocument()
    expect(screen.getByText(/episode-12\.txt · chunk 3/)).toBeInTheDocument()
  })

  it('distinguishes cited sources from ones merely retrieved', () => {
    render(
      <SourceList
        sources={[
          makeSource({ chunk_id: 'a', marker: 1, cited: true }),
          makeSource({ chunk_id: 'b', marker: 2, cited: false }),
          makeSource({ chunk_id: 'c', marker: 3, cited: false }),
        ]}
      />,
    )

    expect(screen.getByText('1 cited of 3 retrieved')).toBeInTheDocument()
    expect(screen.getByText('2 more retrieved but not cited')).toBeInTheDocument()
  })

  it('still lists retrieved sources when the answer cited none', () => {
    render(
      <SourceList
        sources={[
          makeSource({ chunk_id: 'a', marker: 1, cited: false }),
          makeSource({ chunk_id: 'b', marker: 2, cited: false }),
        ]}
      />,
    )

    expect(screen.getByText('2 retrieved')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Show excerpt' })).toHaveLength(2)
  })
})
