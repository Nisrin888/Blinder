import { useChat } from '../context/ChatContext';
import { CitationPanel } from './CitationPanel';

/**
 * Parse text and replace [N] citation markers with superscript elements.
 * Avoids matching pseudonyms like [PERSON_1] — only bare numbers match.
 */
function renderContentWithCitations(text, citations, onMarkerClick) {
  const citationMap = {};
  if (citations) {
    for (const c of citations) {
      if (c.marker != null) {
        citationMap[c.marker] = c;
      }
    }
  }

  const hasCitationMarkers = Object.keys(citationMap).length > 0;

  return text.split('\n').map((line, lineIdx) => {
    if (!hasCitationMarkers || !line) {
      return <p key={lineIdx}>{line || '\u00A0'}</p>;
    }

    // Split on [N] patterns (only bare digits, not [PERSON_1] etc.)
    const parts = [];
    const regex = /\[(\d+)\]/g;
    let lastIndex = 0;
    let match;

    while ((match = regex.exec(line)) !== null) {
      const num = parseInt(match[1], 10);
      // Only treat as citation if it's in our citation map
      if (!(num in citationMap)) continue;

      if (match.index > lastIndex) {
        parts.push(line.slice(lastIndex, match.index));
      }
      parts.push(
        <sup
          key={`${lineIdx}-${match.index}`}
          className="citation-marker"
          data-index={num}
          title={citationMap[num]?.filename || `Source ${num}`}
          onClick={() => onMarkerClick?.(num)}
        >
          {num}
        </sup>
      );
      lastIndex = regex.lastIndex;
    }

    if (lastIndex < line.length) {
      parts.push(line.slice(lastIndex));
    }

    // If no markers were found in this line, render plain text
    if (parts.length === 0) {
      return <p key={lineIdx}>{line || '\u00A0'}</p>;
    }

    return <p key={lineIdx}>{parts}</p>;
  });
}

export function MessageBubble({ message }) {
  const { viewMode } = useChat();

  const content = viewMode === 'lawyer' ? message.lawyer_content : message.blinded_content;
  const isUser = message.role === 'user';

  const handleMarkerClick = (markerNum) => {
    const el = document.getElementById(`citation-source-${message.id}-${markerNum}`);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      el.classList.add('citations__item--highlighted');
      setTimeout(() => el.classList.remove('citations__item--highlighted'), 1500);
    }
  };

  return (
    <div className={`message ${isUser ? 'message--user' : 'message--assistant'}`}>
      <div className="message__avatar">
        {isUser ? 'You' : 'AI'}
      </div>
      <div className="message__body">
        <div className="message__content">
          {!isUser && message.citations?.length > 0
            ? renderContentWithCitations(content, message.citations, handleMarkerClick)
            : content.split('\n').map((line, i) => (
                <p key={i}>{line || '\u00A0'}</p>
              ))
          }
        </div>
        {viewMode === 'llm' && !isUser && (
          <div className="message__badge message__badge--blinded">
            Shielded Response
          </div>
        )}
        {viewMode === 'llm' && isUser && (
          <div className="message__badge message__badge--blinded">
            Shielded Input
          </div>
        )}
        {message.threats_detected && message.threats_detected.length > 0 && (
          <div className="message__threats">
            {message.threats_detected.map((t, i) => (
              <span key={i} className="message__threat-tag">
                {t.threat_type}: {t.description}
              </span>
            ))}
          </div>
        )}
        {!isUser && message.citations && message.citations.length > 0 && (
          <CitationPanel citations={message.citations} messageId={message.id} />
        )}
      </div>
    </div>
  );
}
