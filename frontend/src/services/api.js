const BASE_URL = '/api';

// --- Sessions ---

export async function createSession(title = 'New Session') {
  const res = await fetch(`${BASE_URL}/sessions/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error(`Failed to create session: ${res.statusText}`);
  return res.json();
}

export async function listSessions() {
  const res = await fetch(`${BASE_URL}/sessions/`);
  if (!res.ok) throw new Error(`Failed to list sessions: ${res.statusText}`);
  return res.json();
}

export async function updateSession(sessionId, updates) {
  const res = await fetch(`${BASE_URL}/sessions/${sessionId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  });
  if (!res.ok) throw new Error(`Failed to update session: ${res.statusText}`);
  return res.json();
}

export async function deleteSession(sessionId) {
  const res = await fetch(`${BASE_URL}/sessions/${sessionId}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error(`Failed to delete session: ${res.statusText}`);
  return res.json();
}

// --- Documents ---

export async function uploadDocument(sessionId, file) {
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(`${BASE_URL}/sessions/${sessionId}/documents`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail || `Upload failed: ${res.statusText}`);
  }
  return res.json();
}

export async function listDocuments(sessionId) {
  const res = await fetch(`${BASE_URL}/sessions/${sessionId}/documents`);
  if (!res.ok) throw new Error(`Failed to list documents: ${res.statusText}`);
  return res.json();
}

// --- Chat ---

export function streamChat(sessionId, message, onChunk, onDone, onError, { provider, model } = {}) {
  const controller = new AbortController();
  const payload = { message };
  if (provider) payload.provider = provider;
  if (model) payload.model = model;

  fetch(`${BASE_URL}/sessions/${sessionId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal: controller.signal,
  })
    .then((res) => {
      if (!res.ok) throw new Error(`Chat failed: ${res.statusText}`);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      function read() {
        reader
          .read()
          .then(({ done, value }) => {
            if (done) return;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
              if (line.startsWith('data: ')) {
                try {
                  const data = JSON.parse(line.slice(6));
                  if (data.type === 'chunk') {
                    onChunk(data.content);
                  } else if (data.type === 'done') {
                    onDone(data);
                  }
                } catch {
                  // skip malformed SSE lines
                }
              }
            }
            read();
          })
          .catch((err) => {
            if (err.name !== 'AbortError') onError(err);
          });
      }
      read();
    })
    .catch((err) => {
      if (err.name !== 'AbortError') onError(err);
    });

  return () => controller.abort();
}

export async function getChatHistory(sessionId) {
  const res = await fetch(`${BASE_URL}/sessions/${sessionId}/chat/history`);
  if (!res.ok) throw new Error(`Failed to get history: ${res.statusText}`);
  return res.json();
}

// --- Models ---

export async function listModels() {
  const res = await fetch(`${BASE_URL}/models/`);
  if (!res.ok) throw new Error(`Failed to list models: ${res.statusText}`);
  return res.json();
}

export async function getModelSettings() {
  const res = await fetch(`${BASE_URL}/models/settings`);
  if (!res.ok) throw new Error(`Failed to get model settings: ${res.statusText}`);
  return res.json();
}

export async function updateModelSettings(settings) {
  const res = await fetch(`${BASE_URL}/models/settings`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Requested-With': 'XMLHttpRequest',
    },
    body: JSON.stringify(settings),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail || `Failed to update model settings: ${res.statusText}`);
  }
  return res.json();
}
