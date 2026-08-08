import React, { useState } from 'react';
import { Sparkles, Loader2 } from 'lucide-react';
import ModalShell from './ModalShell';
import Segmented from './Segmented';
import RemotionPreview from './RemotionPreview';

const ENTRANCE_OPTIONS = [
    { value: 'spring', label: 'Bounce' },
    { value: 'fade', label: 'Fade' },
    { value: 'slide-up', label: 'Slide Up' },
    { value: 'none', label: 'None' },
];

const FIELD_LABEL = {
    fontSize: '0.75rem', fontWeight: 500, color: 'var(--muted)',
    display: 'flex', alignItems: 'center', gap: 5, marginBottom: 6,
};

export default function HookModal({ isOpen, onClose, onGenerate, isProcessing, videoUrl, initialText, durationInSeconds, existingSubtitles }) {
    const [text, setText] = useState(initialText || 'POV: You are using the viral hook feature');
    const [position, setPosition] = useState('top');
    const [size, setSize] = useState('M');
    const [entranceAnimation, setEntranceAnimation] = useState('spring');
    const [displayDuration, setDisplayDuration] = useState(5);

    if (!isOpen) return null;

    const hookConfig = {
        text: text || 'Enter your text...',
        position,
        size,
        entranceAnimation,
        displayDurationSec: displayDuration,
    };

    const useRemotionPreview = !!videoUrl;

    const getPositionClass = () => {
        switch (position) {
            case 'center': return 'items-center justify-center';
            case 'bottom': return 'items-center justify-end pb-[20%]';
            case 'top': default: return 'items-center justify-start pt-[20%]';
        }
    };

    return (
        <ModalShell
            isOpen={isOpen}
            onClose={onClose}
            title="Viral Hook"
            icon={<Sparkles size={14} style={{ color: 'var(--primary)', flexShrink: 0 }} />}
            maxWidth={840}
        >
            <div style={{ display: 'flex', gap: '1.25rem', flexDirection: 'row', maxHeight: '80vh' }}>
                {/* Left: Preview */}
                <div style={{
                    flex: 1, minWidth: 0,
                    display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                    background: 'var(--bg)', borderRadius: 8, overflow: 'hidden',
                    aspectRatio: '9/16', maxHeight: '64vh',
                }}>
                    {useRemotionPreview ? (
                        <RemotionPreview
                            videoUrl={videoUrl}
                            durationInSeconds={durationInSeconds || 30}
                            hook={hookConfig}
                            subtitles={existingSubtitles || null}
                        />
                    ) : (
                        <>
                            <video src={videoUrl} className="w-full h-full object-contain" style={{ opacity: 0.5 }} muted playsInline />
                            <div className={`absolute inset-0 flex w-full h-full pointer-events-none ${getPositionClass()}`}>
                                <div
                                    style={{
                                        fontSize: size === 'S' ? 14 : size === 'L' ? 24 : 18,
                                        maxWidth: size === 'L' ? '95%' : '90%',
                                        color: 'oklch(0.15 0.01 170)',
                                        fontWeight: 700,
                                        padding: '10px 12px',
                                        borderRadius: 8,
                                        textAlign: 'center',
                                        whiteSpace: 'pre-wrap',
                                        backgroundColor: 'oklch(0.95 0.01 170 / 0.82)',
                                        boxShadow: '0 4px 15px oklch(0 0 0 / 0.5)',
                                        fontFamily: 'Noto Serif, serif',
                                    }}
                                >
                                    {text || 'Enter your text...'}
                                </div>
                            </div>
                        </>
                    )}
                </div>

                {/* Right: Controls */}
                <div style={{ width: 300, flexShrink: 0, display: 'flex', flexDirection: 'column' }}>
                    <div className="os-scroll" style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '1rem', paddingRight: 4 }}>
                        {/* Text Input */}
                        <div>
                            <label style={FIELD_LABEL}>Text</label>
                            <textarea
                                value={text}
                                onChange={(e) => setText(e.target.value)}
                                rows={3}
                                className="os-input os-textarea"
                                style={{ fontFamily: 'Noto Serif, serif' }}
                                placeholder="Enter text that will stop the scroll..."
                            />
                        </div>

                        <div>
                            <label style={FIELD_LABEL}>Position</label>
                            <Segmented
                                options={['top', 'center', 'bottom'].map(p => ({ value: p, label: p.charAt(0).toUpperCase() + p.slice(1) }))}
                                value={position}
                                onChange={setPosition}
                                columns={3}
                            />
                        </div>

                        <div>
                            <label style={FIELD_LABEL}>Size</label>
                            <Segmented
                                options={[
                                    { value: 'S', label: 'Small' },
                                    { value: 'M', label: 'Medium' },
                                    { value: 'L', label: 'Large' },
                                ]}
                                value={size}
                                onChange={setSize}
                                columns={3}
                            />
                        </div>

                        <div>
                            <label style={FIELD_LABEL}>Entrance</label>
                            <Segmented
                                options={ENTRANCE_OPTIONS}
                                value={entranceAnimation}
                                onChange={setEntranceAnimation}
                                columns={2}
                            />
                        </div>

                        {/* Display Duration */}
                        <div>
                            <label style={{ ...FIELD_LABEL, marginBottom: 4 }}>Duration: {displayDuration}s</label>
                            <input
                                type="range"
                                min="2"
                                max="15"
                                value={displayDuration}
                                onChange={(e) => setDisplayDuration(parseInt(e.target.value))}
                                style={{ width: '100%', accentColor: 'var(--primary)' }}
                            />
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.6875rem', color: 'var(--subtle)' }}>
                                <span>2s</span>
                                <span>15s</span>
                            </div>
                        </div>

                        <div className="os-panel-2" style={{ padding: '0.625rem 0.75rem', fontSize: '0.75rem', color: 'var(--muted)', lineHeight: 1.5 }}>
                            <strong style={{ color: 'var(--ink)' }}>Tip:</strong> Keep it short and punchy. Using "POV:" or specific questions works best for retention.
                        </div>
                    </div>

                    <button
                        onClick={() => onGenerate({ text, position, size, remotion: hookConfig })}
                        disabled={isProcessing || !text.trim()}
                        className="os-btn os-btn-primary"
                        style={{ width: '100%', marginTop: '1rem', padding: '0.625rem', flexShrink: 0, justifyContent: 'center', gap: 6 }}
                    >
                        {isProcessing ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                        {isProcessing ? 'Generating...' : 'Add Hook'}
                    </button>
                </div>
            </div>
        </ModalShell>
    );
}