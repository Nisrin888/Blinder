import { createContext, useContext, useReducer } from 'react';

const ChatContext = createContext(null);
const ChatDispatchContext = createContext(null);

const initialState = {
  sessions: [],
  activeSessionId: null,
  messages: [],
  documents: [],
  isStreaming: false,
  streamingContent: '',
  viewMode: 'lawyer', // 'lawyer' or 'llm'
  error: null,
  // Model selection
  selectedProvider: null,  // null = use server default
  selectedModel: null,     // null = use server default
  availableProviders: [],  // populated from /api/models
  showSettings: false,
};

function chatReducer(state, action) {
  switch (action.type) {
    case 'SET_SESSIONS':
      return { ...state, sessions: action.payload };
    case 'ADD_SESSION':
      return {
        ...state,
        sessions: [action.payload, ...state.sessions],
        activeSessionId: action.payload.id,
        messages: [],
        documents: [],
      };
    case 'SET_ACTIVE_SESSION':
      return {
        ...state,
        activeSessionId: action.payload,
        messages: [],
        documents: [],
        streamingContent: '',
        error: null,
      };
    case 'REMOVE_SESSION':
      return {
        ...state,
        sessions: state.sessions.filter((s) => s.id !== action.payload),
        activeSessionId:
          state.activeSessionId === action.payload ? null : state.activeSessionId,
        messages: state.activeSessionId === action.payload ? [] : state.messages,
      };
    case 'SET_MESSAGES':
      return { ...state, messages: action.payload };
    case 'ADD_MESSAGE':
      return { ...state, messages: [...state.messages, action.payload] };
    case 'UPDATE_LAST_MESSAGE':
      return {
        ...state,
        messages: state.messages.map((m, i) =>
          i === state.messages.length - 1 ? { ...m, ...action.payload } : m
        ),
      };
    case 'SET_DOCUMENTS':
      return { ...state, documents: action.payload };
    case 'ADD_DOCUMENT':
      return { ...state, documents: [...state.documents, action.payload] };
    case 'SET_STREAMING':
      return { ...state, isStreaming: action.payload };
    case 'SET_STREAMING_CONTENT':
      return { ...state, streamingContent: action.payload };
    case 'APPEND_STREAMING_CONTENT':
      return { ...state, streamingContent: state.streamingContent + action.payload };
    case 'UPDATE_SESSION_TITLE':
      return {
        ...state,
        sessions: state.sessions.map((s) =>
          s.id === action.payload.id ? { ...s, title: action.payload.title } : s
        ),
      };
    case 'UPDATE_SESSION_DOMAIN':
      return {
        ...state,
        sessions: state.sessions.map((s) =>
          s.id === action.payload.id ? { ...s, domain: action.payload.domain } : s
        ),
      };
    case 'TOGGLE_VIEW':
      return { ...state, viewMode: state.viewMode === 'lawyer' ? 'llm' : 'lawyer' };
    case 'SET_VIEW':
      return { ...state, viewMode: action.payload };
    case 'SET_ERROR':
      return { ...state, error: action.payload };
    case 'CLEAR_ERROR':
      return { ...state, error: null };
    case 'SET_SELECTED_PROVIDER':
      return { ...state, selectedProvider: action.payload };
    case 'SET_SELECTED_MODEL':
      return { ...state, selectedModel: action.payload };
    case 'SET_MODEL_SELECTION':
      return {
        ...state,
        selectedProvider: action.payload.provider,
        selectedModel: action.payload.model,
      };
    case 'SET_AVAILABLE_PROVIDERS':
      return { ...state, availableProviders: action.payload };
    case 'TOGGLE_SETTINGS':
      return { ...state, showSettings: !state.showSettings };
    case 'SET_SHOW_SETTINGS':
      return { ...state, showSettings: action.payload };
    default:
      return state;
  }
}

export function ChatProvider({ children }) {
  const [state, dispatch] = useReducer(chatReducer, initialState);
  return (
    <ChatContext.Provider value={state}>
      <ChatDispatchContext.Provider value={dispatch}>
        {children}
      </ChatDispatchContext.Provider>
    </ChatContext.Provider>
  );
}

export function useChat() {
  const context = useContext(ChatContext);
  if (!context) throw new Error('useChat must be used within ChatProvider');
  return context;
}

export function useChatDispatch() {
  const context = useContext(ChatDispatchContext);
  if (!context) throw new Error('useChatDispatch must be used within ChatProvider');
  return context;
}
