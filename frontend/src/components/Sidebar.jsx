import { useEffect } from 'react';
import { useChat, useChatDispatch } from '../context/ChatContext';
import { listSessions, createSession, deleteSession, updateSession } from '../services/api';
import { Plus, Trash2, MessageSquare, Settings } from 'lucide-react';

const DOMAIN_OPTIONS = [
  { value: 'legal', label: 'Legal', color: '#4f8cff' },
  { value: 'finance', label: 'Finance', color: '#4fff8c' },
  { value: 'healthcare', label: 'Health', color: '#ff4f8c' },
  { value: 'hr', label: 'HR', color: '#ffc04f' },
  { value: 'general', label: 'General', color: '#a0a0a0' },
];

function domainColor(domain) {
  return DOMAIN_OPTIONS.find((d) => d.value === domain)?.color || '#a0a0a0';
}

function domainLabel(domain) {
  return DOMAIN_OPTIONS.find((d) => d.value === domain)?.label || 'General';
}

export function Sidebar() {
  const { sessions, activeSessionId } = useChat();
  const dispatch = useChatDispatch();

  useEffect(() => {
    loadSessions();
  }, []);

  const loadSessions = async () => {
    try {
      const data = await listSessions();
      dispatch({ type: 'SET_SESSIONS', payload: data.sessions || [] });
    } catch {
      // fresh start, no sessions yet
    }
  };

  const handleNewSession = async () => {
    try {
      const session = await createSession('New Chat');
      dispatch({ type: 'ADD_SESSION', payload: session });
    } catch (err) {
      dispatch({ type: 'SET_ERROR', payload: err.message });
    }
  };

  const handleDeleteSession = async (e, sessionId) => {
    e.stopPropagation();
    try {
      await deleteSession(sessionId);
      dispatch({ type: 'REMOVE_SESSION', payload: sessionId });
    } catch (err) {
      dispatch({ type: 'SET_ERROR', payload: err.message });
    }
  };

  const handleSelectSession = (sessionId) => {
    dispatch({ type: 'SET_ACTIVE_SESSION', payload: sessionId });
  };

  const handleDomainChange = async (e, sessionId) => {
    e.stopPropagation();
    const domain = e.target.value;
    try {
      await updateSession(sessionId, { domain });
      dispatch({
        type: 'UPDATE_SESSION_DOMAIN',
        payload: { id: sessionId, domain },
      });
    } catch (err) {
      dispatch({ type: 'SET_ERROR', payload: err.message });
    }
  };

  return (
    <aside className="sidebar">
      <div className="sidebar__header">
        <h1 className="sidebar__title">Blinder</h1>
        <span className="sidebar__subtitle">Privacy-first AI</span>
      </div>

      <button className="sidebar__new-btn" onClick={handleNewSession}>
        <Plus size={18} />
        New Chat
      </button>

      <div className="sidebar__sessions">
        {sessions.map((session) => {
          const isActive = session.id === activeSessionId;
          const domain = session.domain || 'general';

          return (
            <div
              key={session.id}
              className={`sidebar__session ${
                isActive ? 'sidebar__session--active' : ''
              }`}
              onClick={() => handleSelectSession(session.id)}
            >
              <MessageSquare size={16} />
              <div className="sidebar__session-info">
                <span className="sidebar__session-title">{session.title}</span>
                {isActive ? (
                  <select
                    className="sidebar__domain-select"
                    value={domain}
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => handleDomainChange(e, session.id)}
                  >
                    {DOMAIN_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <span
                    className="sidebar__domain-badge"
                    style={{ color: domainColor(domain) }}
                  >
                    {domainLabel(domain)}
                  </span>
                )}
              </div>
              <button
                className="sidebar__delete-btn"
                onClick={(e) => handleDeleteSession(e, session.id)}
              >
                <Trash2 size={14} />
              </button>
            </div>
          );
        })}
      </div>

      <div className="sidebar__footer">
        <button
          className="sidebar__settings-btn"
          onClick={() => dispatch({ type: 'TOGGLE_SETTINGS' })}
        >
          <Settings size={16} />
          <span>Model Settings</span>
        </button>
        <div className="sidebar__security-badge">
          Your data stays private
        </div>
      </div>
    </aside>
  );
}
