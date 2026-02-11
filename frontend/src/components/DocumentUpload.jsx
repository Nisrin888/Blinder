import { useRef, useState, useEffect } from 'react';
import { useChat, useChatDispatch } from '../context/ChatContext';
import { uploadDocument } from '../services/api';
import { Plus, FileText, Shield, Loader2, X } from 'lucide-react';

export function DocumentUpload() {
  const { activeSessionId, documents } = useChat();
  const dispatch = useChatDispatch();
  const fileInputRef = useRef(null);
  const [uploading, setUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState('');
  const [showPanel, setShowPanel] = useState(false);

  // Reset upload state when switching sessions — prevents loading
  // indicator from leaking across different chats
  useEffect(() => {
    setUploading(false);
    setUploadStatus('');
    setShowPanel(false);
  }, [activeSessionId]);

  const handleFiles = async (files) => {
    if (!activeSessionId || files.length === 0) return;

    setUploading(true);
    setUploadStatus('Scanning for sensitive data...');
    setShowPanel(true);

    try {
      for (const file of files) {
        setUploadStatus(`Processing ${file.name}...`);
        const result = await uploadDocument(activeSessionId, file);
        dispatch({ type: 'ADD_DOCUMENT', payload: result.document });
        setUploadStatus(
          result.document.pii_count > 0
            ? `${file.name}: ${result.document.pii_count} entities blinded`
            : `${file.name}: No PII detected — document is clean`
        );
      }
    } catch (err) {
      dispatch({ type: 'SET_ERROR', payload: err.message });
      setUploadStatus('Upload failed');
    } finally {
      setUploading(false);
      setTimeout(() => setUploadStatus(''), 3000);
    }
  };

  if (!activeSessionId) return null;

  return (
    <div className="doc-attach">
      <button
        className={`doc-attach__btn ${documents.length > 0 ? 'doc-attach__btn--has-docs' : ''}`}
        onClick={() => setShowPanel(!showPanel)}
        title="Attach documents"
      >
        {uploading ? (
          <Loader2 size={20} className="spin" />
        ) : (
          <Plus size={20} />
        )}
        {documents.length > 0 && (
          <span className="doc-attach__count">{documents.length}</span>
        )}
      </button>

      {showPanel && (
        <div className="doc-attach__panel">
          <div className="doc-attach__panel-header">
            <span>Documents</span>
            <button
              className="doc-attach__close"
              onClick={() => setShowPanel(false)}
            >
              <X size={14} />
            </button>
          </div>

          {uploadStatus && (
            <div className="doc-attach__status">
              {uploading && <Loader2 size={12} className="spin" />}
              <span>{uploadStatus}</span>
            </div>
          )}

          {documents.length > 0 && (
            <div className="doc-attach__list">
              {documents.map((doc) => (
                <div key={doc.id} className="doc-attach__item">
                  <FileText size={14} />
                  <span className="doc-attach__name">{doc.filename}</span>
                  <span className={`doc-attach__pii ${doc.pii_count === 0 ? 'doc-attach__pii--clean' : ''}`}>
                    <Shield size={10} />
                    {doc.pii_count > 0 ? doc.pii_count : 'Clean'}
                  </span>
                </div>
              ))}
            </div>
          )}

          <button
            className="doc-attach__upload-btn"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
          >
            <Plus size={16} />
            <span>Add Document</span>
          </button>

          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".pdf,.docx,.txt,.doc,.xlsx,.xls,.csv"
            onChange={(e) => handleFiles(Array.from(e.target.files))}
            style={{ display: 'none' }}
          />
        </div>
      )}
    </div>
  );
}
