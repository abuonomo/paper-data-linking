import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { fetchSimilarPapers } from '../services/apiPublic'
import { colors } from '../styles'

const styles = {
  container: {
    padding: '16px',
    width: '280px',
    flexShrink: 0,
  },
  heading: {
    fontSize: '0.85rem',
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
    color: colors.primaryText,
    marginBottom: '12px',
    paddingBottom: '8px',
    borderBottom: `2px solid ${colors.linkText}`,
  },
  list: {
    listStyle: 'none',
    margin: 0,
    padding: 0,
  },
  item: {
    marginBottom: '12px',
    paddingBottom: '12px',
    borderBottom: '1px solid #e0e0d8',
  },
  title: {
    fontSize: '0.85rem',
    lineHeight: 1.35,
    color: colors.linkText,
    textDecoration: 'none',
    display: 'block',
    marginBottom: '4px',
  },
  meta: {
    fontSize: '0.75rem',
    color: '#888',
  },
  score: {
    display: 'inline-block',
    fontSize: '0.7rem',
    color: '#666',
    backgroundColor: '#f0f0e8',
    borderRadius: '3px',
    padding: '1px 5px',
    marginLeft: '6px',
  },
  missions: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '3px',
    marginTop: '5px',
  },
  missionChip: {
    display: 'inline-block',
    padding: '1px 5px',
    backgroundColor: '#e6fffa',
    color: '#285e61',
    borderRadius: '3px',
    fontSize: '0.65rem',
    border: '1px solid #b2f5ea',
    whiteSpace: 'nowrap',
    lineHeight: '1.4',
  },
  skeletonLine: {
    height: '0.75rem',
    backgroundColor: '#e8e8e0',
    borderRadius: '3px',
    animation: 'none',
  },
  skeletonItem: {
    marginBottom: '12px',
    paddingBottom: '12px',
    borderBottom: '1px solid #e0e0d8',
  },
}

function formatAuthors(authors) {
  if (!authors || authors.length === 0) return ''
  if (authors.length === 1) return authors[0]
  return `${authors[0]} et al.`
}

const SimilarPapers = ({ bibcode, includeUnvalidated = false }) => {
  const [papers, setPapers] = useState(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    if (!bibcode) return
    let cancelled = false
    setPapers(null)
    setError(false)

    fetchSimilarPapers(bibcode, includeUnvalidated)
      .then(data => { if (!cancelled) setPapers(data) })
      .catch(() => { if (!cancelled) setError(true) })

    return () => { cancelled = true }
  }, [bibcode, includeUnvalidated])

  const loading = papers === null && !error
  const empty = error || (papers !== null && papers.length === 0)

  let content
  if (empty) {
    content = (
      <div style={{ fontSize: '0.8rem', color: '#999', fontStyle: 'italic' }}>
        No similar papers found.
      </div>
    )
  } else if (loading) {
    content = (
        <ul style={styles.list}>
          {[...Array(8)].map((_, i) => (
            <li key={i} style={styles.skeletonItem}>
              <div style={{ ...styles.skeletonLine, width: '95%', marginBottom: '4px' }} />
              <div style={{ ...styles.skeletonLine, width: `${60 + (i % 3) * 12}%`, marginBottom: '6px' }} />
              <div style={{ ...styles.skeletonLine, width: '45%', height: '0.6rem', marginBottom: '6px' }} />
              <div style={{ display: 'flex', gap: '4px' }}>
                <div style={{ ...styles.skeletonLine, width: '36px', height: '0.65rem' }} />
                <div style={{ ...styles.skeletonLine, width: '28px', height: '0.65rem' }} />
              </div>
            </li>
          ))}
        </ul>
    )
  } else {
    content = (
      <ul style={styles.list}>
        {papers.map(p => (
          <li key={p.bibcode} style={styles.item}>
            <Link to={`/public/p/${encodeURIComponent(p.bibcode)}`} style={styles.title}>
              {p.title}
            </Link>
            <span style={styles.meta}>
              {formatAuthors(p.authors)}{p.year ? ` (${p.year})` : ''}
              <span style={styles.score}>{p.score.toFixed(2)}</span>
            </span>
            {p.missions && p.missions.length > 0 && (
              <div style={styles.missions}>
                {p.missions.map(m => (
                  <span key={m} style={styles.missionChip}>{m}</span>
                ))}
              </div>
            )}
          </li>
        ))}
      </ul>
    )
  }

  return (
    <div style={styles.container}>
      <div style={styles.heading}>Similar Papers</div>
      {content}
    </div>
  )
}

export default SimilarPapers
