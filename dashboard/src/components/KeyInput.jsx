import React, { useState, useEffect } from 'react';
import { Key, Eye, EyeOff, Check } from 'lucide-react';

export default function KeyInput({ onKeySet, savedKey }) {
    const [key, setKey] = useState(savedKey || '');
    const [isVisible, setIsVisible] = useState(false);
    const [isSaved, setIsSaved] = useState(!!savedKey);

    useEffect(() => {
        if (savedKey) setKey(savedKey);
    }, [savedKey]);

    const handleSave = () => {
        if (key.trim().length > 0) {
            onKeySet(key);
            setIsSaved(true);
        }
    };

    return (
        <div className="os-panel" style={{ padding: '1.25rem', marginBottom: '2rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: '0.875rem' }}>
                <div style={{
                    width: 32, height: 32, borderRadius: 6, flexShrink: 0,
                    background: 'oklch(0.55 0.095 170 / 0.12)', border: '1px solid oklch(0.55 0.095 170 / 0.25)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                    <Key size={15} style={{ color: 'var(--primary)' }} />
                </div>
                <h2 style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--ink)', margin: 0 }}>Gemini API Key</h2>
            </div>

            <div style={{ display: 'flex', gap: 8 }}>
                <div style={{ position: 'relative', flex: 1 }}>
                    <input
                        type={isVisible ? "text" : "password"}
                        value={key}
                        onChange={(e) => {
                            setKey(e.target.value);
                            setIsSaved(false);
                        }}
                        placeholder="AIzaSy..."
                        className="os-input"
                        style={{ fontFamily: 'var(--font-mono)', paddingRight: '2.5rem' }}
                        aria-label="Gemini API key"
                    />
                    <button
                        onClick={() => setIsVisible(!isVisible)}
                        className="os-btn os-btn-ghost os-btn-xs"
                        style={{ position: 'absolute', right: 4, top: 4, padding: 5 }}
                        aria-label={isVisible ? 'Hide key' : 'Show key'}
                    >
                        {isVisible ? <EyeOff size={15} /> : <Eye size={15} />}
                    </button>
                </div>
                <button
                    onClick={handleSave}
                    disabled={!key || isSaved}
                    className={`os-btn os-btn-sm ${isSaved ? 'os-chip-success os-btn-ghost' : 'os-btn-primary'}`}
                    style={{ flexShrink: 0, gap: 5 }}
                >
                    {isSaved ? <><Check size={13} /> Ready</> : 'Set Key'}
                </button>
            </div>
            <p style={{ margin: '0.75rem 0 0', fontSize: '0.75rem', color: 'var(--subtle)', lineHeight: 1.5 }}>
                Your key is stored locally in your browser for convenience.
                <br />
                <a
                    href="https://aistudio.google.com/app/apikey"
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ color: 'var(--primary)', marginTop: 4, textDecoration: 'none', display: 'inline-block' }}
                >
                    Get your free Gemini API Key here →
                </a>
            </p>
        </div>
    );
}