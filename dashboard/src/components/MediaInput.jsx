import React, { useState, useEffect } from 'react';
import { Youtube, Upload, FileVideo, X, Loader2 } from 'lucide-react';
import { getApiUrl } from '../config';

export default function MediaInput({ onProcess, isProcessing, processingLabel }) {
    const [youtubeUrlEnabled, setYoutubeUrlEnabled] = useState(true);
    const [mode, setMode] = useState('url'); // 'url' | 'file'
    const [url, setUrl] = useState('');
    const [file, setFile] = useState(null);
    const [acknowledged, setAcknowledged] = useState(false);

    useEffect(() => {
        fetch(getApiUrl('/api/config'))
            .then((r) => r.ok ? r.json() : null)
            .then((cfg) => {
                if (cfg && cfg.youtubeUrlEnabled === false) {
                    setYoutubeUrlEnabled(false);
                    setMode('file');
                }
            })
            .catch(() => {});
    }, []);

    const handleSubmit = (e) => {
        e.preventDefault();
        if (!acknowledged) return;
        if (mode === 'url' && url) {
            onProcess({ type: 'url', payload: url, acknowledged: true });
        } else if (mode === 'file' && file) {
            onProcess({ type: 'file', payload: file, acknowledged: true });
        }
    };

    const handleDrop = (e) => {
        e.preventDefault();
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            setFile(e.dataTransfer.files[0]);
            setMode('file');
        }
    };

    const tabStyle = (active) => ({
        display: 'flex', alignItems: 'center', gap: 6,
        padding: '0.5rem 0.75rem', fontSize: '0.8125rem', fontWeight: 500,
        background: 'transparent', border: 'none', cursor: 'pointer',
        color: active ? 'var(--primary)' : 'var(--muted)',
        borderBottom: `2px solid ${active ? 'var(--primary)' : 'transparent'}`,
        marginBottom: '-1px',
        transition: 'color var(--dur-fast)',
    });

    return (
        <div>
            <div style={{ display: 'flex', gap: 4, borderBottom: '1px solid var(--border)', marginBottom: '0.875rem' }}>
                {youtubeUrlEnabled && (
                    <button type="button" onClick={() => setMode('url')} style={tabStyle(mode === 'url')} aria-pressed={mode === 'url'}>
                        <Youtube size={15} /> YouTube URL
                    </button>
                )}
                <button type="button" onClick={() => setMode('file')} style={tabStyle(mode === 'file')} aria-pressed={mode === 'file'}>
                    <Upload size={15} /> Upload File
                </button>
            </div>

            <form onSubmit={handleSubmit}>
                {mode === 'url' ? (
                    <div>
                        <input
                            type="url"
                            value={url}
                            onChange={(e) => setUrl(e.target.value)}
                            placeholder="https://www.youtube.com/watch?v=..."
                            className="os-input"
                            required
                            aria-label="YouTube URL"
                        />
                    </div>
                ) : (
                    <div
                        className="os-input"
                        style={{
                            padding: '1.5rem', textAlign: 'center', cursor: 'pointer',
                            borderStyle: 'dashed',
                            borderColor: file ? 'var(--primary)' : 'var(--border-2)',
                            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 8,
                        }}
                        onDragOver={(e) => { e.preventDefault(); e.currentTarget.style.borderColor = 'var(--primary)'; }}
                        onDragLeave={(e) => { e.currentTarget.style.borderColor = file ? 'var(--primary)' : 'var(--border-2)'; }}
                        onDrop={handleDrop}
                    >
                        {file ? (
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, color: 'var(--ink)' }}>
                                <FileVideo size={18} style={{ color: 'var(--primary)' }} />
                                <span style={{ fontSize: '0.8125rem', fontWeight: 500 }}>{file.name}</span>
                                <button
                                    type="button"
                                    onClick={(e) => { e.stopPropagation(); setFile(null); }}
                                    className="os-btn os-btn-ghost os-btn-xs"
                                    style={{ padding: 4 }}
                                    aria-label="Remove file"
                                >
                                    <X size={14} />
                                </button>
                            </div>
                        ) : (
                            <label style={{ cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, width: '100%' }}>
                                <input
                                    type="file"
                                    accept="video/*"
                                    onChange={(e) => setFile(e.target.files?.[0] || null)}
                                    style={{ display: 'none' }}
                                />
                                <Upload size={22} style={{ color: 'var(--subtle)' }} />
                                <p style={{ fontSize: '0.8125rem', color: 'var(--muted)', margin: 0 }}>Click to upload or drag and drop</p>
                                <p style={{ fontSize: '0.6875rem', color: 'var(--subtle)', margin: 0 }}>MP4, MOV up to 2GB</p>
                            </label>
                        )}
                    </div>
                )}

                <label style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginTop: '0.875rem', fontSize: '0.75rem', color: 'var(--muted)', cursor: 'pointer', userSelect: 'none', lineHeight: 1.5 }}>
                    <input
                        type="checkbox"
                        checked={acknowledged}
                        onChange={(e) => setAcknowledged(e.target.checked)}
                        style={{ marginTop: 2 }}
                        className="os-checkbox"
                    />
                    <span>
                        I confirm I own this content or have the rights to process it. I am responsible for any content I submit. See our <a href="/#legal" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--primary)', textDecoration: 'underline' }} onClick={(e) => e.stopPropagation()}>Terms &amp; Privacy</a>.
                    </span>
                </label>

                <button
                    type="submit"
                    disabled={isProcessing || !acknowledged || (mode === 'url' && !url) || (mode === 'file' && !file)}
                    className="os-btn os-btn-primary"
                    style={{ width: '100%', marginTop: '0.875rem', justifyContent: 'center' }}
                >
                    {isProcessing ? (
                        <>
                            <Loader2 size={14} className="animate-spin" />
                            {processingLabel || 'Analyzing Video...'}
                        </>
                    ) : (
                        'Generate Clips'
                    )}
                </button>
            </form>
        </div>
    );
}