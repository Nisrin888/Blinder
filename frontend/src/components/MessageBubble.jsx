import { useChat } from '../context/ChatContext';
import { CitationPanel } from './CitationPanel';

export function MessageBubble({ message }) {
  const { viewMode } = useChat();

  const content = viewMode === 'lawyer' ? message.lawyer_content : message.blinded_content;
  const isUser = message.role === 'user';

  return (
    <div className={`message ${isUser ? 'message--user' : 'message--assistant'}`}>
      <div className="message__avatar">
        {isUser ? 'You' : 'AI'}
      </div>
      <div className="message__body">
        <div className="message__content">
          {content.split('\n').map((line, i) => (
            <p key={i}>{line || '\u00A0'}</p>
          ))}
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
          <CitationPanel citations={message.citations} />
        )}
      </div>
    </div>
  );
}
