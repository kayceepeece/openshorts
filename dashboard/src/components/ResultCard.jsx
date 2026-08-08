import React, { useState, useEffect } from 'react';
import { Download, Share2, Youtube, Instagram, Video, CheckCircle, AlertCircle, Loader2, Wand2, Type, Calendar, Languages } from 'lucide-react';
import { getApiUrl } from '../config';
import SubtitleModal from './SubtitleModal';
import HookModal from './HookModal';
import TranslateModal from './TranslateModal';
import ModalShell from './ModalShell';
import { renderInBrowser } from '../lib/renderInBrowser';

const TikTokMark = ({ size = 14, className }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className}>
        <path d="M19.589 6.686a4.793 4.793 0 0 1-3.77-4.245V2h-3.445v13.672a2.896 2.896 0 0 1-5.201 1.743l-.002-.001.002.001a2.895 2.895 0 0 1 3.183-4.51v-3.5a6.329 6.329 0 0 0-5.394 10.692 6.33 6.33 0 0 0 10.857-4.424V8.687a8.182 8.182 0 0 0 4.773 1.526V6.79a4.831 4.831 0 0 1-1.003-.104z" />
    </svg>
);

const actionBtn = (handle, label, Icon, busy, kind, busyLabel) => (
    <button
        onClick={handle}
        disabled={busy}
        className={`os-btn os-btn-sm ${
            kind === 'primary' ? 'os-btn-primary'
            : kind === 'hook' ? 'os-btn-secondary'
            : kind === 'post' ? 'os-btn-primary'
            : kind === 'download' ? 'os-btn-ghost'
            : 'os-btn-secondary'
        }`}
        style={{ justifyContent: 'center', gap: 5 }}
    >
        {busy ? <Loader2 size={12} className="animate-spin" /> : <Icon size={12} />}
        {busy && busyLabel ? busyLabel : label}
    </button>
);

export default function ResultCard({ clip, index, jobId, uploadPostKey, uploadUserId, geminiApiKey, elevenLabsKey, onPlay, onPause }) {
    const [showModal, setShowModal] = useState(false);
    const [showSubtitleModal, setShowSubtitleModal] = useState(false);
    const [showHookModal, setShowHookModal] = useState(false);
    const [showTranslateModal, setShowTranslateModal] = useState(false);
    const videoRef = React.useRef(null);
    const originalVideoUrl = getApiUrl(clip.video_url); // Never changes — used for Remotion previews
    const [currentVideoUrl, setCurrentVideoUrl] = useState(originalVideoUrl);

    const [platforms, setPlatforms] = useState({ tiktok: true, instagram: true, youtube: true });
    const [postTitle, setPostTitle] = useState("");
    const [postDescription, setPostDescription] = useState("");
    const [isScheduling, setIsScheduling] = useState(false);
    const [scheduleDate, setScheduleDate] = useState("");

    const [posting, setPosting] = useState(false);
    const [postResult, setPostResult] = useState(null);

    const [isEditing, setIsEditing] = useState(false);
    const [isSubtitling, setIsSubtitling] = useState(false);
    const [isHooking, setIsHooking] = useState(false);
    const [isTranslating, setIsTranslating] = useState(false);
    const [editError, setEditError] = useState(null);

    const [clipDuration, setClipDuration] = useState(clip.end && clip.start ? clip.end - clip.start : 30);

    const [activeLayers, setActiveLayers] = useState({ subtitles: null, hook: null, effects: null });

    useEffect(() => {
        if (!jobId || index === undefined) return;
        fetch(getApiUrl(`/api/clip/${jobId}/${index}/transcript`))
            .then(res => res.ok ? res.json() : null)
            .then(data => {
                if (data && data.durationSec) setClipDuration(data.durationSec);
            })
            .catch(() => {});
    }, [jobId, index]);

    useEffect(() => {
        if (showModal) {
            setPostTitle(clip.video_title_for_youtube_short || "Viral Short");
            setPostDescription(clip.video_description_for_instagram || clip.video_description_for_tiktok || "");
            setIsScheduling(false);
            setScheduleDate("");
            setPostResult(null);
        }
    }, [showModal, clip]);

    const renderLayers = async (layers) => {
        const blobUrl = await renderInBrowser({
            videoUrl: originalVideoUrl,
            durationInSeconds: clipDuration,
            subtitles: layers.subtitles,
            hook: layers.hook,
            effects: layers.effects,
        });
        setCurrentVideoUrl(blobUrl);
        if (videoRef.current) videoRef.current.load();
    };

    const handleAutoEdit = async () => {
        setIsEditing(true);
        setEditError(null);
        try {
            const apiKey = geminiApiKey || localStorage.getItem('gemini_key');

            if (!apiKey) {
                throw new Error("Gemini API Key is missing. Please set it in Settings.");
            }

            // Try Remotion effects endpoint first
            const effectsRes = await fetch(getApiUrl('/api/effects/generate'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Gemini-Key': apiKey },
                body: JSON.stringify({
                    job_id: jobId,
                    clip_index: index,
                    input_filename: currentVideoUrl.split('/').pop()
                })
            });

            if (effectsRes.ok) {
                const data = await effectsRes.json();
                if (data.effects && data.effects.segments) {
                    const newLayers = { ...activeLayers, effects: data.effects };
                    setActiveLayers(newLayers);
                    await renderLayers(newLayers);
                    return;
                }
            }

            // Fallback: legacy FFmpeg edit endpoint
            const res = await fetch(getApiUrl('/api/edit'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Gemini-Key': apiKey },
                body: JSON.stringify({
                    job_id: jobId,
                    clip_index: index,
                    input_filename: currentVideoUrl.split('/').pop()
                })
            });

            if (!res.ok) {
                const errText = await res.text();
                try {
                    const jsonErr = JSON.parse(errText);
                    throw new Error(jsonErr.detail || errText);
                } catch {

                    throw new Error(errText);
                }
            }

            const data = await res.json();
            if (data.new_video_url) {
                setCurrentVideoUrl(getApiUrl(data.new_video_url));
                if (videoRef.current) videoRef.current.load();
            }

        } catch (e) {
            setEditError(e.message);
            setTimeout(() => setEditError(null), 5000);
        } finally {
            setIsEditing(false);
        }
    };

    const handleSubtitle = async (options) => {
        setIsSubtitling(true);
        setEditError(null);
        try {
            if (options.remotion) {
                const newLayers = { ...activeLayers, subtitles: options.remotion };
                setActiveLayers(newLayers);
                await renderLayers(newLayers);
                setShowSubtitleModal(false);
                return;
            }

            const res = await fetch(getApiUrl('/api/subtitle'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    job_id: jobId,
                    clip_index: index,
                    position: options.position,
                    font_size: options.fontSize,
                    font_name: options.fontName,
                    font_color: options.fontColor,
                    border_color: options.borderColor,
                    border_width: options.borderWidth,
                    bg_color: options.bgColor,
                    bg_opacity: options.bgOpacity,
                    input_filename: currentVideoUrl.split('/').pop()
                })
            });

            if (!res.ok) throw new Error(await res.text());
            const data = await res.json();
            if (data.new_video_url) {
                setCurrentVideoUrl(getApiUrl(data.new_video_url));
                if (videoRef.current) videoRef.current.load();
                setShowSubtitleModal(false);
            }
        } catch (e) {
            setEditError(e.message);
            setTimeout(() => setEditError(null), 5000);
        } finally {
            setIsSubtitling(false);
        }
    };

    const handleHook = async (hookData) => {
        setIsHooking(true);
        setEditError(null);
        try {
            if (hookData.remotion) {
                const newLayers = { ...activeLayers, hook: hookData.remotion };
                setActiveLayers(newLayers);
                await renderLayers(newLayers);
                setShowHookModal(false);
                return;
            }

            const payload = typeof hookData === 'string'
                ? { text: hookData, position: 'top', size: 'M' }
                : hookData;

            const res = await fetch(getApiUrl('/api/hook'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    job_id: jobId,
                    clip_index: index,
                    text: payload.text,
                    position: payload.position,
                    size: payload.size,
                    input_filename: currentVideoUrl.split('/').pop()
                })
            });

            if (!res.ok) throw new Error(await res.text());
            const data = await res.json();
            if (data.new_video_url) {
                setCurrentVideoUrl(getApiUrl(data.new_video_url));
                if (videoRef.current) videoRef.current.load();
                setShowHookModal(false);
            }
        } catch (e) {
            setEditError(e.message);
            setTimeout(() => setEditError(null), 5000);
        } finally {
            setIsHooking(false);
        }
    };

    const handleTranslate = async (options) => {
        setIsTranslating(true);
        setEditError(null);
        try {
            const apiKey = elevenLabsKey;

            if (!apiKey) {
                throw new Error("ElevenLabs API Key is missing. Please set it in Settings.");
            }

            const requestBody = {
                job_id: jobId,
                clip_index: index,
                target_language: options.targetLanguage,
                input_filename: currentVideoUrl.split('/').pop()
            };

            const res = await fetch(getApiUrl('/api/translate'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-ElevenLabs-Key': apiKey },
                body: JSON.stringify(requestBody)
            });

            if (!res.ok) {
                const errText = await res.text();
                try {
                    const jsonErr = JSON.parse(errText);
                    throw new Error(jsonErr.detail || errText);
                } catch {
                    throw new Error(errText);
                }
            }

            const data = await res.json();
            if (data.new_video_url) {
                setCurrentVideoUrl(getApiUrl(data.new_video_url));
                if (videoRef.current) videoRef.current.load();
                setShowTranslateModal(false);
            }

        } catch (e) {
            setEditError(e.message);
            setTimeout(() => setEditError(null), 5000);
        } finally {
            setIsTranslating(false);
        }
    };

    const handlePost = async () => {
        if (!uploadPostKey || !uploadUserId) {
            setPostResult({ success: false, msg: "Missing API Key or User ID." });
            return;
        }

        const selectedPlatforms = Object.keys(platforms).filter(k => platforms[k]);
        if (selectedPlatforms.length === 0) {
            setPostResult({ success: false, msg: "Select at least one platform." });
            return;
        }

        if (isScheduling && !scheduleDate) {
            setPostResult({ success: false, msg: "Please select a date and time." });
            return;
        }

        setPosting(true);
        setPostResult(null);

        try {
            const payload = {
                job_id: jobId,
                clip_index: index,
                api_key: uploadPostKey,
                user_id: uploadUserId,
                platforms: selectedPlatforms,
                title: postTitle,
                description: postDescription
            };

            if (isScheduling && scheduleDate) {
                payload.scheduled_date = new Date(scheduleDate).toISOString();
                payload.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
            }

            const res = await fetch(getApiUrl('/api/social/post'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (!res.ok) {
                const errText = await res.text();
                try {
                    const jsonErr = JSON.parse(errText);
                    throw new Error(jsonErr.detail || errText);
                } catch {

                    throw new Error(errText);
                }
            }

            setPostResult({ success: true, msg: isScheduling ? "Scheduled successfully!" : "Posted successfully!" });
            setTimeout(() => {
                setShowModal(false);
                setPostResult(null);
            }, 3000);

        } catch (e) {
            setPostResult({ success: false, msg: `Failed: ${e.message}` });
        } finally {
            setPosting(false);
        }
    };

    const handleDownload = async () => {
        try {
            const response = await fetch(currentVideoUrl);
            if (!response.ok) throw new Error('Download failed');
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = url;
            a.download = `clip-${index + 1}.mp4`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        } catch {
            window.open(currentVideoUrl, '_blank');
        }
    };

    return (
        <div className="os-panel" style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: 300, maxHeight: 560 }}>
            <div style={{ display: 'flex', gap: 0, flex: 1, minHeight: 0, flexDirection: 'column' }}>
                {/* Video preview */}
                <div style={{ position: 'relative', background: 'var(--bg)', flexShrink: 0, aspectRatio: '9/16', maxHeight: 240, minHeight: 160 }}>
                    <video
                        ref={videoRef}
                        src={currentVideoUrl}
                        controls
                        style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                        playsInline
                        onPlay={() => {
                            const currentTime = videoRef.current ? videoRef.current.currentTime : 0;
                            onPlay && onPlay(clip.start + currentTime);
                        }}
                        onPause={() => onPause && onPause()}
                        onEnded={() => {
                            if (videoRef.current) {
                                videoRef.current.currentTime = 0;
                                videoRef.current.play();
                            }
                        }}
                    />
                    <span className="os-chip os-chip-default" style={{ position: 'absolute', top: 8, left: 8 }}>
                        Clip {index + 1}
                    </span>

                    {isEditing && (
                        <div style={{
                            position: 'absolute', inset: 0, zIndex: 'var(--z-sticky)',
                            background: 'oklch(0.04 0 0 / 0.72)',
                            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 10,
                        }}>
                            <Loader2 size={26} className="animate-spin" style={{ color: 'var(--primary)' }} />
                            <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--ink)' }}>AI Magic in Progress...</span>
                            <span style={{ fontSize: '0.6875rem', color: 'var(--muted)' }}>Applying viral edits &amp; zooms</span>
                        </div>
                    )}
                </div>

                {/* Content */}
                <div className="os-scroll" style={{ flex: 1, minWidth: 0, padding: '1rem', display: 'flex', flexDirection: 'column', gap: '0.75rem', overflowY: 'auto' }}>
                    <div>
                        <h3 style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--ink)', margin: '0 0 6px', lineHeight: 1.35 }} title={clip.video_title_for_youtube_short}>
                            {clip.video_title_for_youtube_short || "Viral Clip Generated"}
                        </h3>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                            <span className="os-chip os-chip-default">{Math.floor(clip.end - clip.start)}s</span>
                            <span className="os-chip os-chip-default">#shorts</span>
                            <span className="os-chip os-chip-default">#viral</span>
                        </div>
                    </div>

                    <div className="os-panel-2" style={{ padding: '0.625rem 0.75rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.6875rem', fontWeight: 600, color: 'var(--muted)', marginBottom: 4 }}>
                            <Youtube size={11} style={{ color: 'var(--error)' }} />
                            YouTube Title
                        </div>
                        <p style={{ fontSize: '0.8125rem', color: 'var(--muted)', margin: 0, userSelect: 'all', overflowWrap: 'break-word' }}>
                            {clip.video_title_for_youtube_short || "Viral Short Video"}
                        </p>
                    </div>

                    <div className="os-panel-2" style={{ padding: '0.625rem 0.75rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.6875rem', fontWeight: 600, color: 'var(--muted)', marginBottom: 4 }}>
                            <Instagram size={11} style={{ color: 'var(--accent)' }} />
                            Caption
                        </div>
                        <p style={{ fontSize: '0.8125rem', color: 'var(--muted)', margin: 0, userSelect: 'all', overflowWrap: 'break-word' }}>
                            {clip.video_description_for_tiktok || clip.video_description_for_instagram}
                        </p>
                    </div>

                    {editError && (
                        <div className="os-chip os-chip-error" style={{ display: 'flex', alignItems: 'flex-start', gap: 6, padding: '0.5rem 0.625rem', whiteSpace: 'normal', lineHeight: 1.5 }}>
                            <AlertCircle size={12} className="shrink-0" style={{ marginTop: 2 }} />
                            <span>{editError}</span>
                        </div>
                    )}

                    {/* Action footer */}
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 6, paddingTop: '0.625rem', borderTop: '1px solid var(--border)', marginTop: 'auto' }}>
                        {actionBtn(handleAutoEdit, isEditing ? 'Editing...' : 'Auto Edit', Wand2, isEditing, 'secondary')}
                        {actionBtn(() => setShowSubtitleModal(true), isSubtitling ? 'Adding...' : 'Subtitles', Type, isSubtitling, 'secondary')}
                        {actionBtn(() => setShowHookModal(true), isHooking ? 'Adding...' : 'Viral Hook', Wand2, isHooking, 'secondary')}
                        {actionBtn(() => setShowTranslateModal(true), isTranslating ? 'Translating...' : 'Dub Voice', Languages, isTranslating, 'secondary')}
                        {actionBtn(() => setShowModal(true), 'Post', Share2, false, 'primary')}
                        {actionBtn(handleDownload, 'Download', Download, false, 'download')}
                    </div>
                </div>
            </div>

            {/* Post Modal */}
            <ModalShell isOpen={showModal} onClose={() => setShowModal(false)} title="Post / Schedule" maxWidth={460}>
                {!uploadPostKey && (
                    <div className="os-chip os-chip-warning" style={{ display: 'flex', alignItems: 'flex-start', gap: 6, marginBottom: '0.875rem', padding: '0.5rem 0.625rem', whiteSpace: 'normal', lineHeight: 1.5 }}>
                        <AlertCircle size={13} className="shrink-0" style={{ marginTop: 1 }} />
                        <span>Configure API Key in Settings first.</span>
                    </div>
                )}

                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                    <div>
                        <label style={{ fontSize: '0.75rem', fontWeight: 500, color: 'var(--muted)', marginBottom: 4, display: 'block' }}>Video Title</label>
                        <input
                            type="text"
                            value={postTitle}
                            onChange={(e) => setPostTitle(e.target.value)}
                            className="os-input"
                            placeholder="Enter a catchy title..."
                        />
                    </div>

                    <div>
                        <label style={{ fontSize: '0.75rem', fontWeight: 500, color: 'var(--muted)', marginBottom: 4, display: 'block' }}>Caption / Description</label>
                        <textarea
                            value={postDescription}
                            onChange={(e) => setPostDescription(e.target.value)}
                            rows={4}
                            className="os-input os-textarea"
                            placeholder="Write a caption for your post..."
                        />
                    </div>

                    <div className="os-panel-2" style={{ padding: '0.75rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.8125rem', fontWeight: 500, color: 'var(--ink)' }}>
                                <Calendar size={14} style={{ color: 'var(--primary)' }} /> Schedule Post
                            </div>
                            <button
                                type="button"
                                className="os-toggle"
                                role="switch"
                                aria-checked={isScheduling}
                                onClick={() => setIsScheduling(!isScheduling)}
                            />
                        </div>

                        {isScheduling && (
                            <div className="os-fade-in" style={{ marginTop: 6 }}>
                                <label style={{ fontSize: '0.75rem', color: 'var(--muted)', marginBottom: 4, display: 'block' }}>Select Date &amp; Time</label>
                                <input
                                    type="datetime-local"
                                    value={scheduleDate}
                                    onChange={(e) => setScheduleDate(e.target.value)}
                                    className="os-input"
                                    style={{ colorScheme: 'dark' }}
                                />
                            </div>
                        )}
                    </div>

                    <div>
                        <label style={{ fontSize: '0.75rem', fontWeight: 500, color: 'var(--muted)', marginBottom: 6, display: 'block' }}>Select Platforms</label>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                            {[
                                { key: 'tiktok', label: 'TikTok', icon: TikTokMark, color: 'var(--accent)' },
                                { key: 'instagram', label: 'Instagram', icon: Instagram, color: 'var(--accent)' },
                                { key: 'youtube', label: 'YouTube Shorts', icon: Youtube, color: 'var(--error)' },
                            ].map(({ key, label, icon: Icon, color }) => (
                                <label key={key} className="os-panel-2" style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '0.625rem 0.75rem', cursor: 'pointer' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.8125rem', color: 'var(--ink)' }}>
                                        <Icon size={15} style={{ color }} /> {label}
                                    </div>
                                    <input
                                        type="checkbox"
                                        checked={platforms[key]}
                                        onChange={(e) => setPlatforms({ ...platforms, [key]: e.target.checked })}
                                        className="os-checkbox"
                                        style={{ marginLeft: 'auto' }}
                                        aria-label={label}
                                    />
                                </label>
                            ))}
                        </div>
                    </div>
                </div>

                {postResult && (
                    <div className={`os-chip ${postResult.success ? 'os-chip-success' : 'os-chip-error'}`} style={{ display: 'flex', alignItems: 'flex-start', gap: 6, marginTop: '0.75rem', padding: '0.5rem 0.625rem', whiteSpace: 'normal', lineHeight: 1.5 }}>
                        {postResult.success ? <CheckCircle size={13} className="shrink-0" style={{ marginTop: 1 }} /> : <AlertCircle size={13} className="shrink-0" style={{ marginTop: 1 }} />}
                        <span>{postResult.msg}</span>
                    </div>
                )}

                <button
                    onClick={handlePost}
                    disabled={posting || !uploadPostKey}
                    className="os-btn os-btn-primary"
                    style={{ width: '100%', marginTop: '0.875rem', justifyContent: 'center' }}
                >
                    {posting ? <><Loader2 size={14} className="animate-spin" /> {isScheduling ? 'Scheduling...' : 'Publishing...'}</> : <><Share2 size={14} /> {isScheduling ? 'Schedule Post' : 'Publish Now'}</>}
                </button>
            </ModalShell>

            <SubtitleModal
                isOpen={showSubtitleModal}
                onClose={() => setShowSubtitleModal(false)}
                onGenerate={handleSubtitle}
                isProcessing={isSubtitling}
                videoUrl={originalVideoUrl}
                jobId={jobId}
                clipIndex={index}
                existingHook={activeLayers.hook}
            />

            <HookModal
                isOpen={showHookModal}
                onClose={() => setShowHookModal(false)}
                onGenerate={handleHook}
                isProcessing={isHooking}
                videoUrl={originalVideoUrl}
                initialText={clip.viral_hook_text}
                durationInSeconds={clip.end && clip.start ? clip.end - clip.start : 30}
                existingSubtitles={activeLayers.subtitles}
            />

            <TranslateModal
                isOpen={showTranslateModal}
                onClose={() => setShowTranslateModal(false)}
                onTranslate={handleTranslate}
                isProcessing={isTranslating}
                videoUrl={currentVideoUrl}
                hasApiKey={!!elevenLabsKey}
            />
        </div>
    );
}