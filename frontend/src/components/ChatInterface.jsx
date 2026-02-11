import { useState, useRef, useEffect } from 'react';
import { useChat, useChatDispatch } from '../context/ChatContext';
import { streamChat, getChatHistory, listDocuments } from '../services/api';
import { MessageBubble } from './MessageBubble';
import { DocumentUpload } from './DocumentUpload';
import { ViewToggle } from './ViewToggle';
import { ModelSelector } from './ModelSelector';
import { Send, Loader2 } from 'lucide-react';

export function ChatInterface() {
  const { activeSessionId, sessions, messages, isStreaming, streamingContent, viewMode, error, selectedProvider, selectedModel } =
    useChat();
  const dispatch = useChatDispatch();
  const [input, setInput] = useState('');
  const messagesEndRef = useRef(null);
  const cancelRef = useRef(null);

  useEffect(() => {
    if (activeSessionId) {
      loadHistory();
      loadDocuments();
    }
  }, [activeSessionId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);

  const loadHistory = async () => {
    try {
      const data = await getChatHistory(activeSessionId);
      dispatch({ type: 'SET_MESSAGES', payload: data.messages || [] });
    } catch {
      dispatch({ type: 'SET_MESSAGES', payload: [] });
    }
  };

  const loadDocuments = async () => {
    try {
      const docs = await listDocuments(activeSessionId);
      dispatch({ type: 'SET_DOCUMENTS', payload: docs || [] });
    } catch {
      dispatch({ type: 'SET_DOCUMENTS', payload: [] });
    }
  };

  const handleSend = () => {
    if (!input.trim() || isStreaming || !activeSessionId) return;

    const userMessage = input.trim();
    setInput('');

    // Add user message to UI immediately (lawyer view = raw input, blinded comes later)
    dispatch({
      type: 'ADD_MESSAGE',
      payload: {
        id: `temp-${Date.now()}`,
        role: 'user',
        lawyer_content: userMessage,
        blinded_content: 'Processing...',
        threats_detected: [],
        created_at: new Date().toISOString(),
      },
    });

    dispatch({ type: 'SET_STREAMING', payload: true });
    dispatch({ type: 'SET_STREAMING_CONTENT', payload: '' });

    cancelRef.current = streamChat(
      activeSessionId,
      userMessage,
      // onChunk
      (chunk) => {
        dispatch({ type: 'APPEND_STREAMING_CONTENT', payload: chunk });
      },
      // onDone
      (data) => {
        dispatch({ type: 'SET_STREAMING', payload: false });
        dispatch({ type: 'SET_STREAMING_CONTENT', payload: '' });

        if (data.title) {
          dispatch({
            type: 'UPDATE_SESSION_TITLE',
            payload: { id: activeSessionId, title: data.title },
          });
        }

        if (data.domain) {
          dispatch({
            type: 'UPDATE_SESSION_DOMAIN',
            payload: { id: activeSessionId, domain: data.domain },
          });
        }

        // Update the temp user message with real blinded content
        // Then reload full history to get proper IDs and blinded content
        loadHistory();
      },
      // onError
      (err) => {
        dispatch({ type: 'SET_STREAMING', payload: false });
        dispatch({ type: 'SET_STREAMING_CONTENT', payload: '' });
        dispatch({ type: 'SET_ERROR', payload: err.message });
      },
      // model selection
      { provider: selectedProvider, model: selectedModel }
    );
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  if (!activeSessionId) {
    return (
      <div className="chat-empty">
        <div className="chat-empty__content">
          <h2>Blinder</h2>
          <p>
            Privacy-first AI assistant.
            Your data never leaves your machine.
          </p>
          <p className="chat-empty__hint">
            Create a new chat to get started.
          </p>
        </div>
      </div>
    );
  }

  const hasConversation = messages.length > 0 || isStreaming;

  return (
    <div className={`chat ${hasConversation ? 'chat--active' : 'chat--centered'}`}>
      <div className="chat__header">
        <h2 className="chat__title">
          {sessions.find((s) => s.id === activeSessionId)?.title || 'New Chat'}
        </h2>
        <ViewToggle />
      </div>

      {error && (
        <div className="chat__error" onClick={() => dispatch({ type: 'CLEAR_ERROR' })}>
          {error}
        </div>
      )}

      {hasConversation && (
        <div className="chat__messages">
          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}

          {isStreaming && streamingContent && (
            <div className="message message--assistant">
              <div className="message__avatar">AI</div>
              <div className="message__body">
                <div className="message__content">
                  {streamingContent.split('\n').map((line, i) => (
                    <p key={i}>{line || '\u00A0'}</p>
                  ))}
                  <span className="message__cursor">|</span>
                </div>
              </div>
            </div>
          )}

          {isStreaming && !streamingContent && (
            <div className="message message--assistant">
              <div className="message__avatar">AI</div>
              <div className="message__body">
                <div className="message__content message__content--loading">
                  <Loader2 size={16} className="spin" />
                  <span>Thinking...</span>
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      )}

      <div className={`chat__input-wrapper ${hasConversation ? 'chat__input-wrapper--bottom' : 'chat__input-wrapper--center'}`}>
        {!hasConversation && (
          <div className="chat__greeting">
            <h3>What would you like to explore?</h3>
            <p>Upload documents and chat — your sensitive data stays private.</p>
          </div>
        )}
        <div className="chat__input-controls">
          <ModelSelector />
        </div>
        <div className="chat__input-area">
          <DocumentUpload />
          <textarea
            className="chat__input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Message Blinder..."
            disabled={isStreaming}
            rows={1}
          />
          <button
            className="chat__send-btn"
            onClick={handleSend}
            disabled={!input.trim() || isStreaming}
          >
            {isStreaming ? <Loader2 size={20} className="spin" /> : <Send size={20} />}
          </button>
        </div>
      </div>
    </div>
  );
}
