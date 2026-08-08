import React, { useState, useEffect } from 'react';
import { Type, Loader2 } from 'lucide-react';
import { getApiUrl } from '../config';
import ModalShell from './ModalShell';
import Segmented from './Segmented';
import RemotionPreview from './RemotionPreview';

const FONT_OPTIONS = [
    { value: 'Verdana', label: 'Verdana' },
    { value: 'Arial', label: 'Arial' },
    { value: 'Impact', label: 'Impact' },
    { value: 'Helvetica', label: 'Helvetica' },
    { value: 'Georgia', label: 'Georgia' },
    { value: 'Courier New', label: 'Courier New' },
];

const COLOR_PRESETS = [
    '#FFFFFF', '#F5F5F5', '#FFFF00', '#00FFFF',
    '#00FF00', '#FF0000', '#FF69B4',
];

const ANIMATION_OPTIONS = [
    { value: 'pop', label: 'Pop' },
    { value: 'word-highlight', label: 'Glow' },
    { value: 'karaoke', label: 'Karaoke' },
    { value: 'none', label: 'None' },
];

const FIELD_LABEL = {
    fontSize: '0.75rem', fontWeight: 500, color: 'var(--muted)',
    display: 'block', marginBottom: 6,
};

function ColorSwatches({ value, onChange, presets = COLOR_PRESETS }) {
    const active = (c) => value?.toLowerCase() === c.toLowerCase();
    return (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {presets.map((c) => (
                <button
                    key={c}
                    type="button"
                    onClick={() => onChange(c)}
                    style={{
                        width: 26, height: 26, borderRadius: '50%', padding: 0, flexShrink: 0, cursor: 'pointer',
                        background: c,
                        border: `2px solid ${active(c) ? 'var(--ink)' : 'var(--border-2)'}`,
                        transition: 'border-color var(--dst-fast)',
                    }}
                    aria-label={`Color ${c}`}
                    aria-pressed={active(c)}
                />
            ))}
            <label
                title="Custom color"
                style={{
                    width: 26, height: 26, borderRadius: '50%',
                    border: '2px dashed var(--border-2)', cursor: 'pointer',
                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                    position: 'relative', overflow: 'hidden',
                }}
            >
                <span style={{ fontSize: '0.8125rem', color: 'var(--subtle)' }}>+</span>
                <input
                    type="color"
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer' }}
                    aria-label="Custom color"
                />
            </label>
        </div>
    );
}

export default function SubtitleModal({ isOpen, onClose, onGenerate, isProcessing, videoUrl, jobId, clipIndex, existingHook }) {
    const [position, setPosition] = useState('bottom');
    const FONT_SIZE = 24;
    const [fontName, setFontName] = useState('Verdana');
    const [fontColor, setFontColor] = useState('#FFFFFF');
    const [highlightColor, setHighlightColor] = useState('#FFDD00');
    const [borderColor, setBorderColor] = useState('#000000');
    const [borderWidth, setBorderWidth] = useState(2);
    const [bgColor, setBgColor] = useState('#000000');
    const [bgOpacity, setBgOpacity] = useState(0.0);
    const [animation, setAnimation] = useState('pop');
    const [showTextEditor, setShowTextEditor] = useState(false);

    // Remotion preview state
    const [captions, setCaptions] = useState([]);
    const [originalCaptions, setOriginalCaptions] = useState([]);
    const [editableText, setEditableText] = useState('');
    const [durationSec, setDurationSec] = useState(30);
    const [captionsLoading, setCaptionsLoading] = useState(false);
    const [useRemotionPreview, setUseRemotionPreview] = useState(false);

    useEffect(() => {
        if (!isOpen || !jobId || clipIndex === undefined) return;

        setCaptionsLoading(true);
        fetch(getApiUrl(`/api/clip/${jobId}/${clipIndex}/transcript`))
            .then((res) => res.ok ? res.json() : null)
            .then((data) => {
                if (data && data.captions && data.captions.length > 0) {
                    setCaptions(data.captions);
                    setOriginalCaptions(data.captions);
                    setEditableText(data.captions.map(c => c.text).join(' '));
                    setDurationSec(data.durationSec || 30);
                    setUseRemotionPreview(true);
                } else {
                    setUseRemotionPreview(false);
                }
            })
            .catch(() => setUseRemotionPreview(false))
            .finally(() => setCaptionsLoading(false));
    }, [isOpen, jobId, clipIndex]);

    const handleTextEdit = (newText) => {
        setEditableText(newText);
        const newWords = newText.split(/\s+/).filter(w => w.length > 0);
        if (newWords.length === 0 || originalCaptions.length === 0) {
            setCaptions([]);
            return;
        }

        const totalDurationMs = originalCaptions[originalCaptions.length - 1].endMs - originalCaptions[0].startMs;
        const startMs = originalCaptions[0].startMs;
        const wordDurationMs = totalDurationMs / newWords.length;

        const newCaptions = newWords.map((word, i) => ({
            text: word,
            startMs: Math.round(startMs + i * wordDurationMs),
            endMs: Math.round(startMs + (i + 1) * wordDurationMs),
        }));
        setCaptions(newCaptions);
    };

    if (!isOpen) return null;

    const subtitleConfig = {
        captions,
        position,
        style: {
            fontFamily: fontName,
            fontSize: FONT_SIZE * 2.2,
            fontColor,
            highlightColor,
            borderColor,
            borderWidth: borderWidth * 1.5,
            bgColor,
            bgOpacity,
            animation,
        },
    };

    const bw = Math.max(borderWidth, 0);
    const bc = borderColor;
    const outlineShadow = bw > 0 ? [
        `-${bw}px -${bw}px 0 ${bc}`, `${bw}px -${bw}px 0 ${bc}`,
        `-${bw}px ${bw}px 0 ${bc}`, `${bw}px ${bw}px 0 ${bc}`,
        `0 -${bw}px 0 ${bc}`, `0 ${bw}px 0 ${bc}`,
        `-${bw}px 0 0 ${bc}`, `${bw}px 0 0 ${bc}`,
    ].join(', ') : 'none';

    const fallbackPreviewStyle = {
        fontFamily: fontName,
        color: fontColor,
        fontSize: '20px',
        fontWeight: 'bold',
        maxWidth: '85%',
        padding: '6px 12px',
        borderRadius: '4px',
        textAlign: 'center',
        lineHeight: '1.3',
        ...(bgOpacity > 0
            ? {
                backgroundColor: `${bgColor}${Math.round(bgOpacity * 255).toString(16).padStart(2, '0')}`,
                textShadow: 'none',
            }
            : { textShadow: outlineShadow }
        ),
    };

    return (
        <ModalShell
            isOpen={isOpen}
            onClose={onClose}
            title="Auto Subtitles"
            icon={<Type size={14} style={{ color: 'var(--primary)', flexShrink: 0 }} />}
            maxWidth={840}
        >
            <div style={{ display: 'flex', gap: '1.25rem' }}>
                {/* Left: Preview */}
                <div style={{
                    flex: 1, minWidth: 0,
                    display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                    background: 'var(--bg)', borderRadius: 8, overflow: 'hidden', position: 'relative',
                    aspectRatio: '9/16', maxHeight: '60vh',
                }}>
                    {captionsLoading ? (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--muted)', fontSize: '0.875rem' }}>
                            <Loader2 size={16} className="animate-spin" />
                            Loading preview...
                        </div>
                    ) : useRemotionPreview ? (
                        <RemotionPreview
                            videoUrl={videoUrl}
                            durationInSeconds={durationSec}
                            subtitles={subtitleConfig}
                            hook={existingHook || null}
                        />
                    ) : (
                        <>
                            <video src={videoUrl} style={{ width: '100%', height: '100%', objectFit: 'contain', opacity: 0.5 }} muted playsInline />
                            <div style={{
                                position: 'absolute', width: '100%', padding: '0 2rem', textAlign: 'center',
                                display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', pointerEvents: 'none',
                                ...(position === 'top' ? { top: '5rem' } : position === 'bottom' ? { bottom: '5rem' } : {}),
                            }}>
                                <span style={fallbackPreviewStyle}>
                                    This is how your subtitles<br />will appear on the video
                                </span>
                            </div>
                        </>
                    )}
                </div>

                {/* Right: Controls */}
                <div className="os-scroll" style={{
                    width: 300, flexShrink: 0, overflowY: 'auto', paddingRight: 4,
                    display: 'flex', flexDirection: 'column', gap: '1rem', maxHeight: '60vh',
                }}>
                    <Segmented label="Position" options={['top', 'middle', 'bottom'].map(p => ({ value: p, label: p.charAt(0).toUpperCase() + p.slice(1) }))} value={position} onChange={setPosition} columns={3} />
                    <Segmented label="Animation" options={ANIMATION_OPTIONS} value={animation} onChange={setAnimation} columns={2} />

                    {useRemotionPreview && (
                        <div>
                            <button
                                type="button"
                                onClick={() => setShowTextEditor(!showTextEditor)}
                                className="os-btn os-btn-ghost os-btn-sm"
                                style={{ width: '100%', justifyContent: 'space-between', fontSize: '0.75rem', fontWeight: 600, color: 'var(--muted)', marginBottom: 6, gap: 6 }}
                            >
                                <span>Edit Text ({captions.length} words)</span>
                                <span style={{ transition: 'transform 200ms', transform: showTextEditor ? 'rotate(180deg)' : 'none', color: 'var(--subtle)' }}>▾</span>
                            </button>
                            {showTextEditor && (
                                <textarea
                                    value={editableText}
                                    onChange={(e) => handleTextEdit(e.target.value)}
                                    rows={4}
                                    className="os-input os-textarea"
                                    placeholder="Edit subtitle text..."
                                />
                            )}
                        </div>
                    )}

                    <div>
                        <label style={FIELD_LABEL}>Font</label>
                        <select value={fontName} onChange={(e) => setFontName(e.target.value)} className="os-input os-select">
                            {FONT_OPTIONS.map((f) => (
                                <option key={f.value} value={f.value} style={{ fontFamily: f.value }}>{f.label}</option>
                            ))}
                        </select>
                    </div>

                    <div>
                        <label style={FIELD_LABEL}>Text Color</label>
                        <ColorSwatches value={fontColor} onChange={setFontColor} />
                    </div>

                    <div>
                        <label style={FIELD_LABEL}>Highlight Color</label>
                        <ColorSwatches
                            value={highlightColor}
                            onChange={setHighlightColor}
                            presets={['#FFDD00', '#FF4444', '#00FF88', '#00BBFF', '#FF69B4']}
                        />
                    </div>

                    <div>
                        <label style={FIELD_LABEL}>Border</label>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <label style={{ width: 32, height: 32, borderRadius: 6, border: '1px solid var(--border)', cursor: 'pointer', overflow: 'hidden', flexShrink: 0, position: 'relative' }} title="Border color">
                                <div style={{ width: '100%', height: '100%', backgroundColor: borderColor }} />
                                <input type="color" value={borderColor} onChange={(e) => setBorderColor(e.target.value)} style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer' }} aria-label="Border color" />
                            </label>
                            <div style={{ flex: 1 }}>
                                <input
                                    type="range"
                                    min="0"
                                    max="5"
                                    value={borderWidth}
                                    onChange={(e) => setBorderWidth(parseInt(e.target.value))}
                                    style={{ width: '100%', accentColor: 'var(--primary)' }}
                                    aria-label="Border width"
                                />
                                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.6875rem', color: 'var(--subtle)' }}>
                                    <span>None</span>
                                    <span>Thick</span>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                            <label style={{ ...FIELD_LABEL, marginBottom: 0 }}>Background Box</label>
                            <button
                                type="button"
                                className="os-toggle"
                                role="switch"
                                aria-checked={bgOpacity > 0}
                                onClick={() => setBgOpacity(bgOpacity > 0 ? 0 : 0.5)}
                            />
                        </div>
                        {bgOpacity > 0 && (
                            <div className="os-fade-in" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                <label style={{ width: 32, height: 32, borderRadius: 6, border: '1px solid var(--border)', cursor: 'pointer', overflow: 'hidden', flexShrink: 0, position: 'relative' }} title="Background color">
                                    <div style={{ width: '100%', height: '100%', backgroundColor: bgColor }} />
                                    <input type="color" value={bgColor} onChange={(e) => setBgColor(e.target.value)} style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer' }} aria-label="Background color" />
                                </label>
                                <div style={{ flex: 1 }}>
                                    <input
                                        type="range"
                                        min="10"
                                        max="100"
                                        value={Math.round(bgOpacity * 100)}
                                        onChange={(e) => setBgOpacity(parseInt(e.target.value) / 100)}
                                        style={{ width: '100%', accentColor: 'var(--primary)' }}
                                        aria-label="Background opacity"
                                    />
                                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.6875rem', color: 'var(--subtle)' }}>
                                        <span>Transparent</span>
                                        <span>{Math.round(bgOpacity * 100)}%</span>
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </div>

            <button
                onClick={() => onGenerate({
                    position, fontSize: FONT_SIZE, fontName, fontColor, borderColor, borderWidth, bgColor, bgOpacity,
                    remotion: useRemotionPreview ? subtitleConfig : null,
                })}
                disabled={isProcessing}
                className="os-btn os-btn-primary"
                style={{ width: '100%', justifyContent: 'center', gap: 6, marginTop: '1rem' }}
            >
                {isProcessing ? <Loader2 size={14} className="animate-spin" /> : <Type size={14} />}
                {isProcessing ? 'Generating...' : 'Generate Subtitles'}
            </button>
        </ModalShell>
    );
}