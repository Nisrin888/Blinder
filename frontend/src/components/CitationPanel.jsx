import { useState } from 'react';
import { useChat } from '../context/ChatContext';

export function CitationPanel({ citations }) {
  const { viewMode } = useChat();
  const [expandedIdx, setExpandedIdx] = useState(null);

  if (!citations || citations.length === 0) return null;

  const toggle = (idx) => {
    setExpandedIdx(expandedIdx === idx ? null : idx);
  };

  return (
    <div className="citations">
      <div className="citations__label">Sources</div>
      <div className="citations__chips">
        {citations.map((c, idx) => (
          <div key={idx} className="citations__chip-wrapper">
            <button
              className={`citations__chip ${expandedIdx === idx ? 'citations__chip--active' : ''}`}
              onClick={() => toggle(idx)}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" />
                <line x1="16" y1="17" x2="8" y2="17" />
              </svg>
              <span className="citations__chip-name">{c.filename}</span>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                {expandedIdx === idx
                  ? <polyline points="18 15 12 9 6 15" />
                  : <polyline points="6 9 12 15 18 9" />
                }
              </svg>
            </button>
            {expandedIdx === idx && (
              <div className="citations__snippet">
                <p>
                  {viewMode === 'lawyer' ? c.snippet_lawyer : c.snippet_blinded}
                </p>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
