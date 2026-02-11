import { useChat, useChatDispatch } from '../context/ChatContext';
import { Eye, EyeOff, Shield, ShieldOff } from 'lucide-react';

export function ViewToggle() {
  const { viewMode } = useChat();
  const dispatch = useChatDispatch();

  const isLawyer = viewMode === 'lawyer';

  return (
    <div className="privacy-toggle">
      <span className={`privacy-toggle__label ${!isLawyer ? 'privacy-toggle__label--active' : ''}`}>
        <ShieldOff size={13} />
        AI View
      </span>

      <button
        className={`privacy-toggle__track ${isLawyer ? 'privacy-toggle__track--lawyer' : 'privacy-toggle__track--llm'}`}
        onClick={() => dispatch({ type: 'TOGGLE_VIEW' })}
        role="switch"
        aria-checked={isLawyer}
        title={isLawyer ? 'Showing real data — click to see blinded view' : 'Showing blinded data — click to see real view'}
      >
        <span className="privacy-toggle__thumb">
          {isLawyer ? <Eye size={14} /> : <EyeOff size={14} />}
        </span>
        <span className="privacy-toggle__glow" />
      </button>

      <span className={`privacy-toggle__label ${isLawyer ? 'privacy-toggle__label--active' : ''}`}>
        <Shield size={13} />
        Your View
      </span>
    </div>
  );
}
