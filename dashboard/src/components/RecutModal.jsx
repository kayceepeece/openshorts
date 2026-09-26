import React, { useState, useEffect, useRef } from 'react';
import { Loader2, AlertCircle, Plus, Trash2, Scissors, Zap, Film, Grip, ArrowUp, ArrowDown, ArrowLeft, ArrowRight } from 'lucide-react';
import { getApiUrl } from '../config';
import ModalShell from './ModalShell';

/**
 * Clip editor: adjust a finished clip's cut without re-running the job,
 * and nudge per-scene crop centres by hand.
 * Segments are positions in the ORIGINAL video (source seconds), prefilled
 * from the clip's current cut. Save sends them to the recut endpoint.
 */
export default function RecutModal({ isOpen, onClose, jobId, clipIndex, videoUrl, onRecut }) {
    const [loading, setLoading] = useState(true);
    const [segments, setSegments] = useState([]);
    const [canonicalRange, setCanonicalRange] = useState(null);
    const [snapToWords, setSnapToWords] = useState(true);
    const [withCaptions, setWithCaptions] = useState(true);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState(null);
    const [sourceTime, setSourceTime] = useState(null);
    const [activeTab, setActiveTab] = useState('cut'); // 'cut' | 'frame'

    // Per-scene crop-nudge state
    const [scenesLoading, setScenesLoading] = useState(false);
    const [scenes, setScenes] = useState([]);
    const [sourceWidth, setSourceWidth] = useState(0);
    const [sourceHeight, setSourceHeight] = useState(0);
    const [cropWidthFrac, setCropWidthFrac] = useState(0.5625); // 9:16 default
    const [savedOverrides, setSavedOverrides] = useState({});
    const [cropNudging, setCropNudging] = useState(false);

    const videoRef = useRef(null);

    // Load EDL (cut) data
    useEffect(() => {
        if (!isOpen) return;
        setLoading(true);
        setError(null);
        setSourceTime(null);
        fetch(getApiUrl(`/api/clip-jobs/${jobId}/clips/${clipIndex}/edl`))
            .then((r) => { if (!r.ok) throw new Error('Could not load the current cut.'); return r.json(); })
            .then((d) => {
                setSegments(d.segments || []);
                setCanonicalRange(d.canonical_range || null);
                setLoading(false);
            })
            .catch((e) => { setError(e.message); setLoading(false); });
    }, [isOpen, jobId, clipIndex]);

    // Load scene data when switching to the frame tab
    useEffect(() => {
        if (!isOpen || activeTab !== 'frame') return;
        setScenesLoading(true);
        fetch(getApiUrl(`/api/clip-jobs/${jobId}/clips/${clipIndex}/scenes`))
            .then((r) => { if (!r.ok) throw new Error('Could not load scenes.'); return r.json(); })
            .then((d) => {
                setScenes(d.scenes || []);
                setSourceWidth(d.source_width || 0);
                setSourceHeight(d.source_height || 0);
                setCropWidthFrac(d.crop_width_fraction || 0.5625);
                setSavedOverrides(d.saved_overrides || {});
                setScenesLoading(false);
            })
            .catch((e) => { setError(e.message); setScenesLoading(false); });
    }, [isOpen, jobId, clipIndex, activeTab]);

    // Map clip-relative playback time -> source-absolute seconds
    const toSourceTime = (t) => {
        let acc = 0;
        for (const s of segments) {
            const dur = s.end - s.start;
            if (t <= acc + dur) return s.start + Math.max(0, t - acc);
            acc += dur;
        }
        return null;
    };

    const pathKind = (() => {
        if (!canonicalRange || segments.length === 0) return null;
        const inside = segments.every(
            (s) => s.start >= canonicalRange.start - 0.05 && s.end <= canonicalRange.end + 0.05
        );
        return inside ? 'fast' : 'full';
    })();

    const totalSecs = segments.reduce((a, s) => a + Math.max(0, s.end - s.start), 0);

    const updateSeg = (i, field, val) => {
        const v = parseFloat(val);
        if (isNaN(v)) return;
        setSegments((segs) => segs.map((s, j) => (j === i ? { ...s, [field]: v } : s)));
    };

    const addSegment = () => {
        setSegments((segs) => {
            if (segs.length >= 12) return segs;
            const last = segs[segs.length - 1];
            const base = last ? last.end : (canonicalRange ? canonicalRange.start : 0);
            return [...segs, { start: Math.round(base * 10) / 10, end: Math.round((base + 3) * 10) / 10 }];
        });
    };

    const removeSegment = (i) => setSegments((segs) => segs.filter((_, j) => j !== i));

    // Crop nudge helpers
    const getOverride = (sceneIdx) => {
        return savedOverrides[sceneIdx] || null;
    };

    const setOverride = (sceneIdx, value) => {
        setSavedOverrides((prev) => {
            if (value === null) {
                const next = { ...prev };
                delete next[sceneIdx];
                return next;
            }
            return { ...prev, [sceneIdx]: value };
        });
    };

    const nudgeScene = (sceneIdx, dir) => {
        const ov = getOverride(sceneIdx);
        const frac = ov || 0.5;
        const step = 0.02;
        let newFrac = dir === 'left' ? Math.max(0, frac - step) : Math.min(1, frac + step);
        setOverride(sceneIdx, { x: Math.round(newFrac * 10000) / 10000, y: 0.5 });
    };

    const handleSaveFrame = async () => {
        setSaving(true);
        setError(null);
        try {
            const res = await fetch(getApiUrl(`/api/clip-jobs/${jobId}/clips/${clipIndex}/reframe`), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ clip_index: clipIndex, crop_overrides: savedOverrides, reapply_captions: withCaptions }),
            });
            if (!res.ok) {
                const t = await res.text();
                let msg = t;
                try { msg = JSON.parse(t).detail || t; } catch { /* keep raw */ }
                throw new Error(msg);
            }
            const data = await res.json();
            if (onRecut) onRecut(data);
            onClose();
        } catch (e) {
            setError(e.message);
        } finally {
            setSaving(false);
        }
    };

    const handleSave = async () => {
        setSaving(true);
        setError(null);
        try {
            const res = await fetch(getApiUrl(`/api/clip-jobs/${jobId}/clips/${clipIndex}/rerender`), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ segments, snap_to_words: snapToWords, with_captions: withCaptions }),
            });
            if (!res.ok) {
                const t = await res.text();
                let msg = t;
                try { msg = JSON.parse(t).detail || t; } catch { /* keep raw */ }
                throw new Error(msg);
            }
            const data = await res.json();
            if (onRecut) onRecut(data);
            onClose();
        } catch (e) {
            setError(e.message);
        } finally {
            setSaving(false);
        }
    };

    return (
        <ModalShell isOpen={isOpen} onClose={onClose} title="Edit Clip" maxWidth={560}>
            {/* Tab bar */}
            <div style={{ display: 'flex', gap: 4, marginBottom: 12 }}>
                <button onClick={() => setActiveTab('cut')}
                    style={{ flex: 1, padding: '0.5rem', border: 'none', borderRadius: 8, cursor: 'pointer',
                        background: activeTab === 'cut' ? 'var(--primary)' : 'var(--panel)',
                        color: activeTab === 'cut' ? '#fff' : 'var(--muted)', fontWeight: 600, fontSize: '0.8125rem' }}>
                    ✂️ Cut
                </button>
                <button onClick={() => setActiveTab('frame')}
                    style={{ flex: 1, padding: '0.5rem', border: 'none', borderRadius: 8, cursor: 'pointer',
                        background: activeTab === 'frame' ? 'var(--primary)' : 'var(--panel)',
                        color: activeTab === 'frame' ? '#fff' : 'var(--muted)', fontWeight: 600, fontSize: '0.8125rem' }}>
                    🎯 Frame
                </button>
            </div>

            {loading ? (
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, padding: '2rem' }}>
                    <Loader2 size={18} className="animate-spin" style={{ color: 'var(--primary)' }} />
                    <span style={{ fontSize: '0.8125rem', color: 'var(--muted)' }}>Loading current cut…</span>
                </div>
            ) : activeTab === 'cut' ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
                    {/* Preview */}
                    <div style={{ position: 'relative', background: 'var(--bg)', borderRadius: 10, overflow: 'hidden', aspectRatio: '9/16', maxHeight: 300, margin: '0 auto', width: '100%', maxWidth: 220 }}>
                        <video ref={videoRef} src={videoUrl} controls playsInline preload="metadata"
                            style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                            onTimeUpdate={(e) => setSourceTime(toSourceTime(e.currentTarget.currentTime))} />
                    </div>
                    <div style={{ textAlign: 'center', fontSize: '0.75rem', color: 'var(--muted)', fontFamily: 'var(--font-mono)', minHeight: 18 }}>
                        {sourceTime !== null
                            ? <>Preview position = original video <b style={{ color: 'var(--ink)' }}>{sourceTime.toFixed(1)}s</b></>
                            : <>Play the preview to read exact cut points</>}
                    </div>

                    {/* Segments */}
                    <div>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                            <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--muted)' }}>
                                Segments <span style={{ fontWeight: 400 }}>(seconds in the original video)</span>
                            </label>
                            {canonicalRange && (
                                <span className="os-chip" style={{ fontFamily: 'var(--font-mono)' }}>
                                    window {canonicalRange.start.toFixed(1)}–{canonicalRange.end.toFixed(1)}s
                                </span>
                            )}
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                            {segments.map((s, i) => (
                                <div key={i} className="os-panel-2" style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '0.5rem 0.625rem' }}>
                                    <span className="os-chip os-chip-default" style={{ minWidth: 26, textAlign: 'center' }}>{i + 1}</span>
                                    <input type="number" step={0.1} min={0} value={s.start}
                                        onChange={(e) => updateSeg(i, 'start', e.target.value)}
                                        className="os-input" style={{ width: 90, fontFamily: 'var(--font-mono)' }}
                                        aria-label={`Segment ${i + 1} start`} />
                                    <span style={{ color: 'var(--subtle)' }}>→</span>
                                    <input type="number" step={0.1} min={0} value={s.end}
                                        onChange={(e) => updateSeg(i, 'end', e.target.value)}
                                        className="os-input" style={{ width: 90, fontFamily: 'var(--font-mono)' }}
                                        aria-label={`Segment ${i + 1} end`} />
                                    <span style={{ marginLeft: 'auto', fontSize: '0.75rem', color: 'var(--subtle)', fontFamily: 'var(--font-mono)' }}>
                                        {(Math.max(0, s.end - s.start)).toFixed(1)}s
                                    </span>
                                    <button onClick={() => removeSegment(i)} className="os-btn os-btn-ghost os-btn-sm"
                                        style={{ padding: '0.375rem' }} title="Remove segment" disabled={segments.length <= 1}>
                                        <Trash2 size={13} />
                                    </button>
                                </div>
                            ))}
                        </div>
                        <button onClick={addSegment} className="os-btn os-btn-ghost os-btn-sm"
                            style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
                            <Plus size={13} /> Add segment
                        </button>
                    </div>

                    {/* Options */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                        {[
                            { key: 'snap', label: 'Snap cuts to word boundaries', desc: 'Avoids cutting mid-word', value: snapToWords, set: setSnapToWords },
                            { key: 'caps', label: 'Re-burn captions', desc: 'Captions rebuilt for the new cut', value: withCaptions, set: setWithCaptions },
                        ].map(({ key, label, desc, value, set }) => (
                            <label key={key} className="os-panel-2" style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '0.625rem 0.75rem', cursor: 'pointer' }}>
                                <div>
                                    <div style={{ fontSize: '0.8125rem', color: 'var(--ink)' }}>{label}</div>
                                    <div style={{ fontSize: '0.6875rem', color: 'var(--subtle)' }}>{desc}</div>
                                </div>
                                <input type="checkbox" checked={value} onChange={(e) => set(e.target.checked)}
                                    className="os-checkbox" style={{ marginLeft: 'auto' }} aria-label={label} />
                            </label>
                        ))}
                    </div>

                    {pathKind && (
                        <div className={`os-chip ${pathKind === 'fast' ? 'os-chip-success' : 'os-chip-warning'}`}
                            style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '0.5rem 0.625rem', lineHeight: 1.5, whiteSpace: 'normal' }}>
                            {pathKind === 'fast' ? <Zap size={13} /> : <Film size={13} />}
                            <span>
                                {pathKind === 'fast'
                                    ? `Fast path — everything stays inside the original window, done in seconds. New length ≈ ${totalSecs.toFixed(1)}s.`
                                    : `Full path — reaches outside the original window, so it re-cuts from the source video and reframes. Takes longer. New length ≈ ${totalSecs.toFixed(1)}s.`}
                            </span>
                        </div>
                    )}

                    {error && (
                        <div className="os-chip os-chip-error" style={{ display: 'flex', alignItems: 'flex-start', gap: 6, padding: '0.5rem 0.625rem', whiteSpace: 'normal', lineHeight: 1.5 }}>
                            <AlertCircle size={12} className="shrink-0" style={{ marginTop: 2 }} />
                            <span>{error}</span>
                        </div>
                    )}

                    <button onClick={handleSave} disabled={saving || segments.length === 0}
                        className="os-btn os-btn-primary" style={{ width: '100%', justifyContent: 'center' }}>
                        {saving ? <><Loader2 size={14} className="animate-spin" /> Re-cutting…</> : <><Scissors size={14} /> Save new cut</>}
                    </button>
                </div>
            ) : (
                /* Frame tab: per-scene crop-nudge UI */
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
                    {scenesLoading ? (
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, padding: '2rem' }}>
                            <Loader2 size={18} className="animate-spin" style={{ color: 'var(--primary)' }} />
                            <span style={{ fontSize: '0.8125rem', color: 'var(--muted)' }}>Loading scenes…</span>
                        </div>
                    ) : (
                        <>
                            {/* Info */}
                            <div className="os-chip" style={{ padding: '0.5rem 0.625rem', fontSize: '0.75rem', color: 'var(--muted)', lineHeight: 1.5 }}>
                                Drag the crop centre for each scene to fix bad framing.
                                The CUT is never touched — only the crop position changes.
                                Source: {sourceWidth}×{sourceHeight}, crop ≈ {cropWidthFrac * 100 > 0 ? (cropWidthFrac * 100).toFixed(1) : '9:16'}.
                            </div>

                            {/* Scene list */}
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                                {scenes.map((scene, idx) => {
                                    const ov = getOverride(idx);
                                    const cx = ov ? ov.x : (scene.suggested_center || 0.5);
                                    const cy = ov ? ov.y : (scene.suggested_center_y || 0.5);
                                    return (
                                        <div key={idx} className="os-panel-2" style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: '0.625rem 0.75rem' }}>
                                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                                                <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--ink)' }}>
                                                    Scene {idx + 1}
                                                    <span style={{ fontWeight: 400, color: 'var(--subtle)', marginLeft: 8, fontSize: '0.75rem' }}>
                                                        {scene.start.toFixed(1)}–{scene.end.toFixed(1)}s
                                                    </span>
                                                </span>
                                                {ov ? (
                                                    <button onClick={() => setOverride(idx, null)}
                                                        style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--subtle)', fontSize: '0.6875rem' }}>
                                                        Reset
                                                    </button>
                                                ) : null}
                                            </div>

                                            {/* Mini preview area */}
                                            <div style={{ position: 'relative', background: '#1a1a2e', borderRadius: 6, overflow: 'hidden', aspectRatio: '9/16', maxHeight: 120 }}>
                                                {scene.thumbnail_url ? (
                                                    <img src={scene.thumbnail_url} alt={`Scene ${idx + 1}`}
                                                        style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                                                ) : (
                                                    <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--subtle)', fontSize: '0.75rem' }}>
                                                        No preview
                                                    </div>
                                                )}
                                                {/* Crop indicator */}
                                                <div style={{
                                                    position: 'absolute', top: 0, left: `${(cx - cropWidthFrac / 2) * 100}%`,
                                                    width: `${cropWidthFrac * 100}%`, height: '100%',
                                                    border: '2px solid var(--primary)', borderRadius: 2,
                                                    pointerEvents: 'none',
                                                    boxShadow: '0 0 0 9999px rgba(0,0,0,0.35)'
                                                }} />
                                                {/* Centre marker */}
                                                <div style={{
                                                    position: 'absolute', top: '50%', left: `${cx * 100}%`,
                                                    transform: 'translate(-50%, -50%)',
                                                    width: 8, height: 8, borderRadius: '50%',
                                                    background: 'var(--primary)', border: '2px solid #fff',
                                                    pointerEvents: 'none'
                                                }} />
                                            </div>

                                            {/* Nudge controls */}
                                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, justifyContent: 'center' }}>
                                                <button onClick={() => nudgeScene(idx, 'left')} className="os-btn os-btn-ghost os-btn-sm" aria-label="Nudge left">
                                                    <ArrowLeft size={14} />
                                                </button>
                                                <button onClick={() => nudgeScene(idx, 'up')} className="os-btn os-btn-ghost os-btn-sm" aria-label="Nudge up">
                                                    <ArrowUp size={14} />
                                                </button>
                                                <span style={{ fontSize: '0.6875rem', fontFamily: 'var(--font-mono)', color: 'var(--ink)', minWidth: 50, textAlign: 'center' }}>
                                                    {cx.toFixed(2)}, {cy.toFixed(2)}
                                                </span>
                                                <button onClick={() => nudgeScene(idx, 'down')} className="os-btn os-btn-ghost os-btn-sm" aria-label="Nudge down">
                                                    <ArrowDown size={14} />
                                                </button>
                                                <button onClick={() => nudgeScene(idx, 'right')} className="os-btn os-btn-ghost os-btn-sm" aria-label="Nudge right">
                                                    <ArrowRight size={14} />
                                                </button>
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>

                            {/* Save frame button */}
                            <button onClick={handleSaveFrame} disabled={saving || Object.keys(savedOverrides).length === 0}
                                className="os-btn os-btn-primary" style={{ width: '100%', justifyContent: 'center' }}>
                                {saving ? <><Loader2 size={14} className="animate-spin" /> Re-framing…</> : <><Grip size={14} /> Save framing</>}
                            </button>
                        </>
                    )}

                    {error && (
                        <div className="os-chip os-chip-error" style={{ display: 'flex', alignItems: 'flex-start', gap: 6, padding: '0.5rem 0.625rem', whiteSpace: 'normal', lineHeight: 1.5 }}>
                            <AlertCircle size={12} className="shrink-0" style={{ marginTop: 2 }} />
                            <span>{error}</span>
                        </div>
                    )}
                </div>
            )}
        </ModalShell>
    );
}
