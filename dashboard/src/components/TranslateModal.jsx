import React, { useState } from 'react';
import { Loader2, Globe, Languages, AlertCircle } from 'lucide-react';
import ModalShell from './ModalShell';

const LANGUAGES = {
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "pl": "Polish",
    "hi": "Hindi",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "ar": "Arabic",
    "ru": "Russian",
    "tr": "Turkish",
    "nl": "Dutch",
    "sv": "Swedish",
    "id": "Indonesian",
    "fil": "Filipino",
    "ms": "Malay",
    "vi": "Vietnamese",
    "th": "Thai",
    "uk": "Ukrainian",
    "el": "Greek",
    "cs": "Czech",
    "fi": "Finnish",
    "ro": "Romanian",
    "da": "Danish",
    "bg": "Bulgarian",
    "hr": "Croatian",
    "sk": "Slovak",
    "ta": "Tamil",
    "en": "English",
};

export default function TranslateModal({ isOpen, onClose, onTranslate, isProcessing, videoUrl, hasApiKey }) {
    const [targetLanguage, setTargetLanguage] = useState('es');

    const handleSubmit = () => {
        onTranslate({ targetLanguage });
    };

    return (
        <ModalShell
            isOpen={isOpen}
            onClose={onClose}
            title="Dub Voice"
            subtitle="AI voice translation by ElevenLabs"
            maxWidth={440}
        >
            {!hasApiKey && (
                <div className="os-chip os-chip-warning" style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: '0.875rem', padding: '0.5rem 0.625rem', whiteSpace: 'normal', lineHeight: 1.5 }}>
                    <AlertCircle size={14} className="shrink-0" style={{ marginTop: 1 }} />
                    <span>Configure ElevenLabs API Key in Settings first.</span>
                </div>
            )}

            {/* Preview */}
            <div style={{ marginBottom: '1rem', borderRadius: 8, overflow: 'hidden', background: 'var(--bg)' }}>
                <video
                    src={videoUrl}
                    className="w-full h-full object-contain"
                    style={{ aspectRatio: '16/9', maxHeight: 240 }}
                    muted
                    playsInline
                />
            </div>

            {/* Language Selection */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5, marginBottom: '0.875rem' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.8125rem', fontWeight: 500, color: 'var(--muted)' }}>
                    <Globe size={13} />
                    Target Language
                </label>
                <select
                    value={targetLanguage}
                    onChange={(e) => setTargetLanguage(e.target.value)}
                    className="os-input os-select"
                    disabled={isProcessing}
                >
                    {Object.entries(LANGUAGES).sort((a, b) => a[1].localeCompare(b[1])).map(([code, name]) => (
                        <option key={code} value={code}>
                            {name}
                        </option>
                    ))}
                </select>
            </div>

            {/* Info */}
            <div className="os-panel-2" style={{ padding: '0.625rem 0.75rem', marginBottom: '1rem' }}>
                <p style={{ fontSize: '0.75rem', color: 'var(--muted)', lineHeight: 1.5, margin: 0 }}>
                    The audio will be dubbed with AI-generated voice in the selected language, matching the original speaker's characteristics.
                </p>
            </div>

            {/* Processing State */}
            {isProcessing && (
                <div className="os-panel-2" style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '0.75rem', marginBottom: '1rem' }}>
                    <Loader2 size={18} className="animate-spin" style={{ color: 'var(--primary)', flexShrink: 0 }} />
                    <div>
                        <p style={{ fontSize: '0.8125rem', fontWeight: 500, color: 'var(--ink)', margin: 0 }}>Dubbing audio...</p>
                        <p style={{ fontSize: '0.6875rem', color: 'var(--subtle)', margin: 0 }}>This may take a few minutes</p>
                    </div>
                </div>
            )}

            {/* Actions */}
            <div style={{ display: 'flex', gap: 8 }}>
                <button
                    onClick={onClose}
                    disabled={isProcessing}
                    className="os-btn os-btn-secondary"
                    style={{ flex: 1 }}
                >
                    Cancel
                </button>
                <button
                    onClick={handleSubmit}
                    disabled={isProcessing || !hasApiKey}
                    className="os-btn os-btn-primary"
                    style={{ flex: 1, justifyContent: 'center', alignItems: 'center', gap: 6 }}
                >
                    {isProcessing ? (
                        <>
                            <Loader2 size={14} className="animate-spin" />
                            Dubbing...
                        </>
                    ) : (
                        <>
                            <Languages size={14} />
                            Dub Voice
                        </>
                    )}
                </button>
            </div>
        </ModalShell>
    );
}