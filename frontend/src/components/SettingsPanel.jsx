import { useState, useEffect } from 'react';
import { useChat, useChatDispatch } from '../context/ChatContext';
import { getModelSettings, updateModelSettings, listModels } from '../services/api';
import { X, Key, Check, AlertCircle, Loader2 } from 'lucide-react';

export function SettingsPanel() {
  const { showSettings } = useChat();
  const dispatch = useChatDispatch();

  const [openaiKey, setOpenaiKey] = useState('');
  const [anthropicKey, setAnthropicKey] = useState('');
  const [defaultProvider, setDefaultProvider] = useState('ollama');
  const [openaiKeySet, setOpenaiKeySet] = useState(false);
  const [anthropicKeySet, setAnthropicKeySet] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (showSettings) loadSettings();
  }, [showSettings]);

  const loadSettings = async () => {
    try {
      const data = await getModelSettings();
      setDefaultProvider(data.default_provider);
      setOpenaiKeySet(data.openai_api_key_set);
      setAnthropicKeySet(data.anthropic_api_key_set);
    } catch {
      // ignore
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError('');
    setSaved(false);
    try {
      const updates = { default_provider: defaultProvider };
      if (openaiKey.trim()) updates.openai_api_key = openaiKey.trim();
      if (anthropicKey.trim()) updates.anthropic_api_key = anthropicKey.trim();

      const result = await updateModelSettings(updates);
      setOpenaiKeySet(result.openai_api_key_set);
      setAnthropicKeySet(result.anthropic_api_key_set);
      setOpenaiKey('');
      setAnthropicKey('');
      setSaved(true);

      // Refresh available models
      try {
        const models = await listModels();
        dispatch({ type: 'SET_AVAILABLE_PROVIDERS', payload: models.providers });
      } catch {
        // non-critical
      }

      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  if (!showSettings) return null;

  return (
    <div className="settings-overlay" onClick={() => dispatch({ type: 'SET_SHOW_SETTINGS', payload: false })}>
      <div className="settings-panel" onClick={(e) => e.stopPropagation()}>
        <div className="settings-panel__header">
          <h2>Model Settings</h2>
          <button
            className="settings-panel__close"
            onClick={() => dispatch({ type: 'SET_SHOW_SETTINGS', payload: false })}
          >
            <X size={18} />
          </button>
        </div>

        <div className="settings-panel__body">
          <div className="settings-panel__section">
            <label className="settings-panel__label">Default Provider</label>
            <select
              className="settings-panel__select"
              value={defaultProvider}
              onChange={(e) => setDefaultProvider(e.target.value)}
            >
              <option value="ollama">Ollama (Local)</option>
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
            </select>
            <p className="settings-panel__hint">
              {defaultProvider === 'ollama'
                ? 'Runs locally — no data leaves your machine.'
                : 'Blinded prompts are sent to the API — real PII never leaves your machine.'}
            </p>
          </div>

          <div className="settings-panel__section">
            <label className="settings-panel__label">
              <Key size={14} />
              OpenAI API Key
              {openaiKeySet && (
                <span className="settings-panel__status settings-panel__status--set">
                  <Check size={12} /> Configured
                </span>
              )}
            </label>
            <input
              className="settings-panel__input"
              type="password"
              placeholder={openaiKeySet ? 'Key is set — enter new to replace' : 'sk-...'}
              value={openaiKey}
              onChange={(e) => setOpenaiKey(e.target.value)}
            />
          </div>

          <div className="settings-panel__section">
            <label className="settings-panel__label">
              <Key size={14} />
              Anthropic API Key
              {anthropicKeySet && (
                <span className="settings-panel__status settings-panel__status--set">
                  <Check size={12} /> Configured
                </span>
              )}
            </label>
            <input
              className="settings-panel__input"
              type="password"
              placeholder={anthropicKeySet ? 'Key is set — enter new to replace' : 'sk-ant-...'}
              value={anthropicKey}
              onChange={(e) => setAnthropicKey(e.target.value)}
            />
          </div>

          <div className="settings-panel__privacy-note">
            <AlertCircle size={14} />
            <span>
              Even with cloud models, Blinder pseudonymizes all PII before sending.
              The API only sees <code>[PERSON_1]</code>, never real names.
            </span>
          </div>

          {error && (
            <div className="settings-panel__error">{error}</div>
          )}

          <button
            className="settings-panel__save"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? (
              <><Loader2 size={14} className="spin" /> Saving...</>
            ) : saved ? (
              <><Check size={14} /> Saved</>
            ) : (
              'Save Settings'
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
