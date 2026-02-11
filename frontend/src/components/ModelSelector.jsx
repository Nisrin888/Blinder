import { useState, useEffect, useRef } from 'react';
import { useChat, useChatDispatch } from '../context/ChatContext';
import { listModels } from '../services/api';
import { ChevronDown, Cpu, Cloud, Zap } from 'lucide-react';

const PROVIDER_ICONS = {
  ollama: Cpu,
  openai: Zap,
  anthropic: Cloud,
};

const PROVIDER_LABELS = {
  ollama: 'Ollama (Local)',
  openai: 'OpenAI',
  anthropic: 'Anthropic',
};

export function ModelSelector() {
  const { selectedProvider, selectedModel, availableProviders } = useChat();
  const dispatch = useChatDispatch();
  const [open, setOpen] = useState(false);
  const [defaultProvider, setDefaultProvider] = useState('ollama');
  const [defaultModel, setDefaultModel] = useState('llama3');
  const dropdownRef = useRef(null);

  useEffect(() => {
    loadModels();
  }, []);

  useEffect(() => {
    function handleClickOutside(e) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const loadModels = async () => {
    try {
      const data = await listModels();
      dispatch({ type: 'SET_AVAILABLE_PROVIDERS', payload: data.providers });
      setDefaultProvider(data.default_provider);
      setDefaultModel(data.default_model);
    } catch {
      // Fallback — just show ollama
    }
  };

  const activeProvider = selectedProvider || defaultProvider;
  const activeModel = selectedModel || defaultModel;

  const handleSelect = (provider, modelId) => {
    dispatch({
      type: 'SET_MODEL_SELECTION',
      payload: { provider, model: modelId },
    });
    setOpen(false);
  };

  // Display name for the currently selected model
  const getDisplayName = () => {
    for (const p of availableProviders) {
      const model = p.models.find((m) => m.id === activeModel && m.provider === activeProvider);
      if (model) return model.name;
    }
    // Fallback: clean up model ID
    const name = activeModel.split(':')[0];
    return name.charAt(0).toUpperCase() + name.slice(1);
  };

  const Icon = PROVIDER_ICONS[activeProvider] || Cpu;

  return (
    <div className="model-selector" ref={dropdownRef}>
      <button
        className="model-selector__trigger"
        onClick={() => setOpen(!open)}
        title="Select AI model"
      >
        <Icon size={14} />
        <span className="model-selector__name">{getDisplayName()}</span>
        <ChevronDown size={12} className={`model-selector__chevron ${open ? 'model-selector__chevron--open' : ''}`} />
      </button>

      {open && (
        <div className="model-selector__dropdown">
          {availableProviders.map((provider) => (
            <div key={provider.provider} className="model-selector__group">
              <div className="model-selector__group-header">
                {(() => {
                  const GroupIcon = PROVIDER_ICONS[provider.provider] || Cpu;
                  return <GroupIcon size={12} />;
                })()}
                <span>{PROVIDER_LABELS[provider.provider] || provider.provider}</span>
                {!provider.available && (
                  <span className="model-selector__badge model-selector__badge--disabled">
                    {provider.provider === 'ollama' ? 'Offline' : 'No key'}
                  </span>
                )}
              </div>
              {provider.models.map((model) => {
                const isActive = model.id === activeModel && model.provider === activeProvider;
                const isDisabled = !provider.available;
                return (
                  <button
                    key={`${model.provider}-${model.id}`}
                    className={`model-selector__item ${isActive ? 'model-selector__item--active' : ''} ${isDisabled ? 'model-selector__item--disabled' : ''}`}
                    onClick={() => !isDisabled && handleSelect(model.provider, model.id)}
                    disabled={isDisabled}
                  >
                    <span className="model-selector__item-name">{model.name}</span>
                    <span className="model-selector__item-context">{model.context}</span>
                  </button>
                );
              })}
            </div>
          ))}
          <button
            className="model-selector__settings-link"
            onClick={() => {
              setOpen(false);
              dispatch({ type: 'TOGGLE_SETTINGS' });
            }}
          >
            Configure API keys...
          </button>
        </div>
      )}
    </div>
  );
}
