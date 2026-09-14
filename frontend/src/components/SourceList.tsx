/**
 * Citation display.
 *
 * Sources the answer actually referenced are shown first and marked; sources that were
 * retrieved but not cited are kept in a collapsed list so a reviewer can see everything
 * the model was given. Optional metadata (guest, episode, URL) is rendered only when the
 * transcript declared it — nothing is filled in with a guess.
 */

import { useState } from 'react'

import type { Source } from '../types/api'

function SourceItem({ source }: { source: Source }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <li className={`source${source.cited ? ' source--cited' : ''}`}>
      <div className="source__head">
        <span className="source__marker" aria-hidden="true">
          S{source.marker}
        </span>
        <div className="source__meta">
          <p className="source__title">
            {source.source_url ? (
              <a href={source.source_url} target="_blank" rel="noopener noreferrer">
                {source.title}
              </a>
            ) : (
              source.title
            )}
          </p>
          <p className="source__details">
            {source.episode && <span>{source.episode}</span>}
            {source.guest && <span>Guest: {source.guest}</span>}
            <span title="Cosine distance: lower is a closer match">
              match {(1 - source.distance).toFixed(2)}
            </span>
          </p>
        </div>
      </div>

      <button
        type="button"
        className="source__toggle"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        {expanded ? 'Hide excerpt' : 'Show excerpt'}
      </button>

      {expanded && (
        <blockquote className="source__excerpt">
          {source.excerpt}
          <footer>
            {source.source_file} · chunk {source.chunk_index}
            {source.speaker ? ` · ${source.speaker}` : ''}
          </footer>
        </blockquote>
      )}
    </li>
  )
}

export function SourceList({ sources }: { sources: Source[] }) {
  if (sources.length === 0) return null

  const cited = sources.filter((source) => source.cited)
  const retrieved = sources.filter((source) => !source.cited)

  return (
    <section className="sources" aria-label="Sources for this answer">
      <h4 className="sources__heading">
        Sources
        <span className="sources__count">
          {cited.length > 0
            ? `${cited.length} cited of ${sources.length} retrieved`
            : `${sources.length} retrieved`}
        </span>
      </h4>

      <ul className="sources__list">
        {(cited.length > 0 ? cited : retrieved).map((source) => (
          <SourceItem key={source.chunk_id} source={source} />
        ))}
      </ul>

      {cited.length > 0 && retrieved.length > 0 && (
        <details className="sources__extra">
          <summary>{retrieved.length} more retrieved but not cited</summary>
          <ul className="sources__list">
            {retrieved.map((source) => (
              <SourceItem key={source.chunk_id} source={source} />
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}
