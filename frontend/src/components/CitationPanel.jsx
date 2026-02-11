import { useChat } from '../context/ChatContext';

const CIRCLED_NUMBERS = ['', '\u2460', '\u2461', '\u2462', '\u2463', '\u2464', '\u2465', '\u2466', '\u2467', '\u2468', '\u2469'];

function getCircledNumber(n) {
  return CIRCLED_NUMBERS[n] || `(${n})`;
}

export function CitationPanel({ citations, messageId }) {
  const { viewMode } = useChat();

  if (!citations || citations.length === 0) return null;

  // Sort by marker number if available, otherwise by score
  const sorted = [...citations].sort((a, b) => {
    if (a.marker != null && b.marker != null) return a.marker - b.marker;
    if (a.marker != null) return -1;
    if (b.marker != null) return 1;
    return b.score - a.score;
  });

  return (
    <div className="citations">
      <div className="citations__header">
        Sources ({sorted.length})
      </div>
      <div className="citations__list">
        {sorted.map((c, idx) => {
          const markerNum = c.marker ?? idx + 1;
          const snippet = viewMode === 'lawyer' ? c.snippet_lawyer : c.snippet_blinded;

          return (
            <div
              key={idx}
              className="citations__item"
              id={`citation-source-${messageId}-${markerNum}`}
            >
              <div className="citations__item-header">
                <span className="citations__marker">{getCircledNumber(markerNum)}</span>
                <span className="citations__filename">{c.filename}</span>
                {c.score > 0 && (
                  <span className="citations__score">
                    {Math.round(c.score * 100)}%
                  </span>
                )}
              </div>
              {snippet && (
                <div className="citations__snippet">
                  <p>{snippet}</p>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
