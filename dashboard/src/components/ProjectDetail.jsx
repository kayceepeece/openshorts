import React, { useState, useEffect } from 'react';
import {
    ChevronLeft, FileVideo, Play, Sparkles,
    BookOpen, FileText, CheckSquare, Trash2,
    Activity, Clock, Download, ChevronRight,
    MessageSquare, RefreshCw, Settings, Plus, X,
    PanelRightOpen, PanelRightClose
} from 'lucide-react';
import MediaInput from './MediaInput';
import ResultCard from './ResultCard';
import { getApiUrl } from '../config';

export default function ProjectDetail({
    project,
    onBack,
    geminiApiKey,
    uploadPostKey,
    uploadUserId,
    elevenLabsKey,
    onPlayClip,
    onPauseClip,
    onProjectUpdated
}) {
    const [videos, setVideos] = useState([]);
    const [clipJobs, setClipJobs] = useState([]);
    const [selectedVideoIds, setSelectedVideoIds] = useState([]);

    // Viewer State — null = closed, video object = open
    const [selectedVideoForViewer, setSelectedVideoForViewer] = useState(null);
    const [activeViewerTab, setActiveViewerTab] = useState('transcript');

    // Settings Modal State
    const [showSettings, setShowSettings] = useState(false);
    const [settingsName, setSettingsName] = useState(project.name);
    const [settingsDossier, setSettingsDossier] = useState(project.dossier_enabled);
    const [settingsRetention, setSettingsRetention] = useState(project.retention_days);
    const [settingsContentType, setSettingsContentType] = useState(project.content_type || 'general');
    const [settingsInstructions, setSettingsInstructions] = useState(project.custom_instructions || '');
    const [savingSettings, setSavingSettings] = useState(false);

    const [viewerLoading, setViewerLoading] = useState(false);
    const [isAnalyzing, setIsAnalyzing] = useState(false);
    const [isClipping, setIsClipping] = useState(false);
    const [customPrompt, setCustomPrompt] = useState('');
    const [expandedClipJobId, setExpandedClipJobId] = useState(null);
    const [error, setError] = useState(null);

    const [activeVideoJobs, setActiveVideoJobs] = useState({});
    const [activeClipJobs, setActiveClipJobs] = useState({});

    const [videoInstructions, setVideoInstructions] = useState('');
    const [savingVideoInstructions, setSavingVideoInstructions] = useState(false);

    /* ── Data fetching ─────────────────────────────────────────────── */
    const fetchVideos = async () => {
        try {
            const res = await fetch(getApiUrl(`/api/projects/${project.id}/videos`));
            if (res.ok) {
                const data = await res.json();
                setVideos(data.videos || []);
                setError(null);
            } else {
                setError(`Failed to load videos: ${res.status}`);
            }
        } catch (e) {
            setError(`Failed to load videos: ${e.message}`);
        }
    };

    const fetchClipJobs = async () => {
        try {
            const res = await fetch(getApiUrl(`/api/projects/${project.id}/clips`));
            if (res.ok) {
                const data = await res.json();
                setClipJobs(data.clip_jobs || []);
                setError(null);
            } else {
                setError('Failed to load clip jobs');
            }
        } catch {
            setError('Failed to connect to server');
        }
    };

    useEffect(() => {
        fetchVideos();
        fetchClipJobs();
        return () => {
            Object.values(activeVideoJobs).forEach(clearInterval);
            Object.values(activeClipJobs).forEach(clearInterval);
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [project.id]);

    useEffect(() => {
        videos.forEach(vid => {
            if (vid.status === 'analyzing' && !activeVideoJobs[vid.id]) startPollingVideo(vid.id);
        });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [videos]);

    useEffect(() => {
        clipJobs.forEach(cj => {
            if ((cj.status === 'queued' || cj.status === 'processing') && !activeClipJobs[cj.id]) startPollingClipJob(cj.id);
        });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [clipJobs]);

    const startPollingVideo = (videoId) => {
        const id = setInterval(async () => {
            try {
                const res = await fetch(getApiUrl(`/api/projects/${project.id}/videos/${videoId}/status`));
                if (res.ok) {
                    const data = await res.json();
                    setVideos(prev => prev.map(v => v.id === videoId ? { ...v, status: data.status, error: data.video?.error } : v));
                    if (data.status === 'ready' || data.status === 'failed') {
                        clearInterval(id);
                        setActiveVideoJobs(prev => { const n = { ...prev }; delete n[videoId]; return n; });
                        fetchVideos();
                    }
                }
            } catch { /* ignore poll errors */ }
        }, 3000);
        setActiveVideoJobs(prev => ({ ...prev, [videoId]: id }));
    };

    const startPollingClipJob = (clipJobId) => {
        const id = setInterval(async () => {
            try {
                const res = await fetch(getApiUrl(`/api/clip-jobs/${clipJobId}`));
                if (res.ok) {
                    const data = await res.json();
                    setClipJobs(prev => prev.map(cj => cj.id === clipJobId ? { ...cj, status: data.status, error: data.error, result_json: data.result_json } : cj));
                    if (data.status === 'completed' || data.status === 'failed') {
                        clearInterval(id);
                        setActiveClipJobs(prev => { const n = { ...prev }; delete n[clipJobId]; return n; });
                        fetchClipJobs();
                    }
                }
            } catch { /* ignore poll errors */ }
        }, 3000);
        setActiveClipJobs(prev => ({ ...prev, [clipJobId]: id }));
    };

    /* ── Actions ───────────────────────────────────────────────────── */
    const handleUploadProcess = async ({ type, payload, acknowledged }) => {
        setIsAnalyzing(true);
        try {
            const formData = new FormData();
            formData.append('acknowledged', acknowledged ? '1' : '0');
            if (type === 'url') formData.append('url', payload);
            else formData.append('file', payload);

            const res = await fetch(getApiUrl(`/api/projects/${project.id}/videos`), {
                method: 'POST',
                headers: { 'X-Gemini-Key': geminiApiKey },
                body: formData
            });
            if (!res.ok) { const err = await res.json(); throw new Error(err.detail || 'Failed to submit video'); }
            const result = await res.json();
            const newVideoObj = {
                id: result.video_id, project_id: project.id, status: 'analyzing',
                source_type: type,
                source_filename: type === 'file' ? payload.name : 'YouTube Video',
                created_at: Date.now() / 1000
            };
            setVideos(prev => [newVideoObj, ...prev]);
            startPollingVideo(result.video_id);
        } catch (e) {
            alert(e.message);
        } finally {
            setIsAnalyzing(false);
        }
    };

    const handleGenerateClips = async () => {
        if (selectedVideoIds.length === 0) return;
        setIsClipping(true);
        try {
            const res = await fetch(getApiUrl(`/api/projects/${project.id}/clip`), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Gemini-Key': geminiApiKey },
                body: JSON.stringify({ video_ids: selectedVideoIds, detection_prompt: customPrompt })
            });
            if (!res.ok) { const err = await res.json(); throw new Error(err.detail || 'Failed to create clipping job'); }
            const result = await res.json();
            setCustomPrompt('');
            setSelectedVideoIds([]);
            fetchClipJobs();
            startPollingClipJob(result.clip_job_id);
            setExpandedClipJobId(result.clip_job_id);
        } catch (e) {
            alert(e.message);
        } finally {
            setIsClipping(false);
        }
    };

    const handleDeleteVideo = async (videoId, e) => {
        e.stopPropagation();
        if (!confirm('Delete this video and its files? This cannot be undone.')) return;
        try {
            const res = await fetch(getApiUrl(`/api/videos/${videoId}`), { method: 'DELETE' });
            if (res.ok) {
                setVideos(prev => prev.filter(v => v.id !== videoId));
                setSelectedVideoIds(prev => prev.filter(id => id !== videoId));
                if (selectedVideoForViewer?.id === videoId) setSelectedVideoForViewer(null);
            }
        } catch { /* ignore network errors */ }
    };

    const handleSelectVideo = (videoId, e) => {
        e.stopPropagation();
        setSelectedVideoIds(prev =>
            prev.includes(videoId) ? prev.filter(id => id !== videoId) : [...prev, videoId]
        );
    };

    const handleLoadViewer = async (video) => {
        // Toggle off if same video
        if (selectedVideoForViewer?.id === video.id) {
            setSelectedVideoForViewer(null);
            return;
        }
        setSelectedVideoForViewer(video);
        setVideoInstructions(video.custom_instructions || '');
        if (!video.transcript_json || !video.dossier_text) {
            setViewerLoading(true);
            try {
                const res = await fetch(getApiUrl(`/api/videos/${video.id}`));
                if (res.ok) {
                    const data = await res.json();
                    if (!data.transcript && data.transcript_json) {
                        try { data.transcript = typeof data.transcript_json === 'string' ? JSON.parse(data.transcript_json) : data.transcript_json; }
                        catch { data.transcript = null; }
                    }
                    setVideos(prev => prev.map(v => v.id === video.id ? data : v));
                    setSelectedVideoForViewer(data);
                    setVideoInstructions(data.custom_instructions || '');
                }
            } catch { /* ignore viewer load errors */ }
            finally { setViewerLoading(false); }
        } else {
            const normalized = { ...video };
            if (!normalized.transcript && normalized.transcript_json) {
                try { normalized.transcript = typeof normalized.transcript_json === 'string' ? JSON.parse(normalized.transcript_json) : normalized.transcript_json; }
                catch { normalized.transcript = null; }
            }
            setSelectedVideoForViewer(normalized);
        }
    };

    const handleSaveVideoInstructions = async () => {
        if (!selectedVideoForViewer) return;
        setSavingVideoInstructions(true);
        try {
            const res = await fetch(getApiUrl(`/api/videos/${selectedVideoForViewer.id}`), {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ custom_instructions: videoInstructions.trim() || null })
            });
            if (!res.ok) { const err = await res.json(); throw new Error(err.detail || 'Failed to save'); }
            const updated = await res.json();
            setVideos(prev => prev.map(v => v.id === updated.id ? { ...v, custom_instructions: updated.custom_instructions } : v));
            setSelectedVideoForViewer(prev => ({ ...prev, custom_instructions: updated.custom_instructions }));
        } catch (e) {
            alert(e.message);
        } finally {
            setSavingVideoInstructions(false);
        }
    };

    const handleSaveSettings = async () => {
        setSavingSettings(true);
        try {
            const res = await fetch(getApiUrl(`/api/projects/${project.id}`), {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: settingsName, dossier_enabled: settingsDossier,
                    retention_days: parseInt(settingsRetention),
                    content_type: settingsContentType,
                    custom_instructions: settingsInstructions.trim() || null
                })
            });
            if (res.ok) {
                const updated = await res.json();
                if (onProjectUpdated) onProjectUpdated(updated);
                setShowSettings(false);
            } else {
                const err = await res.json();
                alert(err.detail || 'Failed to update project');
            }
        } catch {
            alert('Failed to save settings');
        } finally {
            setSavingSettings(false);
        }
    };

    /* ── Sub-components ────────────────────────────────────────────── */
    const StatusChip = ({ status }) => {
        const map = {
            analyzing: 'os-chip-primary',
            ready: 'os-chip-success',
            failed: 'os-chip-error',
            queued: 'os-chip-primary',
            processing: 'os-chip-primary',
            completed: 'os-chip-success',
        };
        return (
            <span className={`os-chip ${map[status] || 'os-chip-default'}`}
                style={status === 'analyzing' || status === 'queued' || status === 'processing'
                    ? { animation: 'dot-pulse 1.8s ease-in-out infinite' } : {}}>
                {status}
            </span>
        );
    };

    const viewerOpen = !!selectedVideoForViewer;

    /* ── Render ────────────────────────────────────────────────────── */
    return (
        <div className="os-fade-in" style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

            {/* ── Page header ── */}
            <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '0.75rem 1rem', borderBottom: '1px solid var(--border)',
                flexShrink: 0, gap: 12,
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                    <button onClick={onBack} className="os-btn os-btn-ghost os-btn-sm" style={{ padding: 6, flexShrink: 0 }}>
                        <ChevronLeft size={16} />
                    </button>
                    <h1 style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--ink)', margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {project.name}
                    </h1>
                    <span className={`os-chip ${project.dossier_enabled ? 'os-chip-accent' : 'os-chip-default'}`}>
                        {project.dossier_enabled ? 'Dossier on' : 'No dossier'}
                    </span>
                    <span className="os-chip os-chip-default" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                        <Clock size={10} /> {project.retention_days}d
                    </span>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                    {viewerOpen && (
                        <span style={{ fontSize: '0.75rem', color: 'var(--muted)' }}>
                            {selectedVideoForViewer.source_filename || selectedVideoForViewer.source_url || 'Video'}
                        </span>
                    )}
                    <button
                        onClick={() => selectedVideoForViewer ? setSelectedVideoForViewer(null) : null}
                        className={`os-btn os-btn-sm ${viewerOpen ? 'os-btn-secondary' : 'os-btn-ghost'}`}
                        title={viewerOpen ? 'Close intelligence viewer' : 'Select a video to open viewer'}
                        style={{ gap: 6, opacity: viewerOpen ? 1 : 0.4 }}
                    >
                        {viewerOpen ? <PanelRightClose size={14} /> : <PanelRightOpen size={14} />}
                        {viewerOpen ? 'Close' : 'Intelligence'}
                    </button>
                    <button onClick={() => setShowSettings(true)} className="os-btn os-btn-ghost os-btn-sm" style={{ padding: 6 }} title="Project settings">
                        <Settings size={15} />
                    </button>
                </div>
            </div>

            {/* ── Error banner ── */}
            {error && (
                <div style={{
                    margin: '0.5rem 1rem 0', padding: '0.625rem 0.875rem', flexShrink: 0,
                    background: 'oklch(0.62 0.18 25 / 0.08)', border: '1px solid oklch(0.62 0.18 25 / 0.25)',
                    borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    fontSize: '0.8125rem', color: 'var(--error)',
                }}>
                    <span>{error}</span>
                    <button onClick={() => setError(null)} className="os-btn os-btn-ghost os-btn-xs">Dismiss</button>
                </div>
            )}

            {/* ── Main content area ── */}
            <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>

                {/* ── Left: primary workflow ── */}
                <div className="os-scroll" style={{
                    flex: 1, overflowY: 'auto', padding: '1rem',
                    display: 'flex', flexDirection: 'column', gap: '0.75rem', minWidth: 0,
                    // Smoothly give width to the viewer when open
                    transition: 'none',
                }}>

                    {/* Upload */}
                    <section className="os-panel" style={{ padding: '1rem' }}>
                        <h3 style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--ink)', margin: '0 0 0.75rem', display: 'flex', alignItems: 'center', gap: 6 }}>
                            <Plus size={14} style={{ color: 'var(--primary)' }} /> Analyze New Video
                        </h3>
                        <MediaInput onProcess={handleUploadProcess} isProcessing={isAnalyzing} />
                    </section>

                    {/* Videos list */}
                    <section className="os-panel" style={{ padding: '1rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
                            <h3 style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--ink)', margin: 0, display: 'flex', alignItems: 'center', gap: 6 }}>
                                <FileVideo size={14} style={{ color: 'var(--primary)' }} />
                                Videos
                                <span style={{ fontSize: '0.75rem', fontWeight: 400, color: 'var(--subtle)' }}>({videos.length})</span>
                            </h3>
                            {selectedVideoIds.length > 0 && (
                                <button
                                    onClick={handleGenerateClips}
                                    disabled={isClipping}
                                    className="os-btn os-btn-primary os-btn-sm"
                                >
                                    {isClipping
                                        ? <><div style={{ width: 12, height: 12, border: '2px solid var(--primary-fg)', borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 0.6s linear infinite' }} /> Working…</>
                                        : <><Sparkles size={13} />{selectedVideoIds.length > 1 ? `Cross-clip ${selectedVideoIds.length}` : 'Generate Clips'}</>
                                    }
                                </button>
                            )}
                        </div>

                        {/* Custom prompt — appears when videos are selected */}
                        {selectedVideoIds.length > 0 && (
                            <div style={{ marginBottom: '0.75rem', animation: 'os-fade-in var(--dur-base) var(--ease-out-quart) both' }}>
                                <label style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: '0.75rem', fontWeight: 500, color: 'var(--muted)', marginBottom: 5 }}>
                                    <MessageSquare size={11} /> Custom prompt <span style={{ color: 'var(--subtle)', fontWeight: 400 }}>(optional)</span>
                                </label>
                                <textarea
                                    value={customPrompt}
                                    onChange={e => setCustomPrompt(e.target.value)}
                                    placeholder="e.g. 'Find funny punchlines', 'Focus on product demo moments'"
                                    className="os-input os-textarea"
                                    style={{ height: 60, fontSize: '0.8125rem' }}
                                />
                            </div>
                        )}

                        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                            {videos.length === 0 ? (
                                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '2rem', color: 'var(--subtle)', textAlign: 'center' }}>
                                    <FileVideo size={28} style={{ color: 'var(--border-2)', marginBottom: 8 }} />
                                    <p style={{ fontSize: '0.8125rem', margin: 0 }}>No videos yet — upload one above.</p>
                                </div>
                            ) : (
                                videos.map(vid => {
                                    const isSelected = selectedVideoIds.includes(vid.id);
                                    const isViewerActive = selectedVideoForViewer?.id === vid.id;
                                    const hasTranscript = !!vid.transcript_json;
                                    const hasDossier = !!vid.dossier_text;

                                    return (
                                        <div
                                            key={vid.id}
                                            onClick={() => vid.status === 'ready' && handleLoadViewer(vid)}
                                            className="os-panel-2"
                                            style={{
                                                padding: '0.625rem 0.75rem',
                                                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                                cursor: vid.status === 'ready' ? 'pointer' : 'default',
                                                borderColor: isViewerActive ? 'var(--primary)' : undefined,
                                                background: isViewerActive ? 'oklch(0.55 0.095 170 / 0.08)' : undefined,
                                                transition: 'border-color var(--dur-fast), background var(--dur-fast)',
                                            }}
                                            onMouseEnter={e => { if (!isViewerActive) e.currentTarget.style.borderColor = 'var(--border-2)'; }}
                                            onMouseLeave={e => { if (!isViewerActive) e.currentTarget.style.borderColor = 'var(--border)'; }}
                                        >
                                            {/* Checkbox + info */}
                                            <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
                                                {vid.status === 'ready' ? (
                                                    <button
                                                        onClick={e => handleSelectVideo(vid.id, e)}
                                                        style={{
                                                            width: 18, height: 18, borderRadius: 4, flexShrink: 0,
                                                            border: isSelected ? 'none' : '1px solid var(--border-2)',
                                                            background: isSelected ? 'var(--primary)' : 'transparent',
                                                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                                                            cursor: 'pointer', transition: 'all var(--dur-fast)',
                                                        }}
                                                    >
                                                        {isSelected && <CheckSquare size={11} style={{ color: 'var(--primary-fg)' }} />}
                                                    </button>
                                                ) : (
                                                    <div style={{ width: 18, height: 18, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                                                        <Activity size={12} style={{ color: 'var(--primary)', animation: 'dot-pulse 1.8s ease-in-out infinite' }} />
                                                    </div>
                                                )}

                                                <div style={{ minWidth: 0 }}>
                                                    <div style={{
                                                        fontSize: '0.8125rem', fontWeight: 500, color: 'var(--ink)',
                                                        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                                                        maxWidth: viewerOpen ? 180 : 380,
                                                    }}>
                                                        {vid.source_filename || vid.source_url || 'Unknown video'}
                                                    </div>
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 3 }}>
                                                        <StatusChip status={vid.status} />
                                                        <span style={{ fontSize: '0.6875rem', color: 'var(--subtle)' }}>
                                                            {vid.source_type === 'youtube' ? 'YouTube' : 'Upload'}
                                                        </span>
                                                        {vid.duration_seconds > 0 && (
                                                            <span style={{ fontSize: '0.6875rem', color: 'var(--subtle)', display: 'flex', alignItems: 'center', gap: 3 }}>
                                                                · <Clock size={10} /> {Math.round(vid.duration_seconds)}s
                                                            </span>
                                                        )}
                                                    </div>
                                                </div>
                                            </div>

                                            {/* Right: badges + delete */}
                                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
                                                {vid.status === 'ready' && (
                                                    <div style={{ display: 'flex', gap: 4 }}>
                                                        <span className={`os-chip ${hasTranscript ? 'os-chip-default' : 'os-chip-error'}`}
                                                            style={{ opacity: hasTranscript ? 1 : 0.5 }}>
                                                            <FileText size={10} /> TXT
                                                        </span>
                                                        {project.dossier_enabled && (
                                                            <span className={`os-chip ${hasDossier ? 'os-chip-default' : 'os-chip-warning'}`}
                                                                style={{ opacity: hasDossier ? 1 : 0.5 }}>
                                                                <BookOpen size={10} /> DOS
                                                            </span>
                                                        )}
                                                    </div>
                                                )}
                                                <button
                                                    onClick={e => handleDeleteVideo(vid.id, e)}
                                                    className="os-btn os-btn-danger os-btn-xs"
                                                    style={{ padding: 5, opacity: 0 }}
                                                    id={`del-vid-${vid.id}`}
                                                    onMouseEnter={e => e.currentTarget.style.opacity = 1}
                                                    onMouseLeave={e => e.currentTarget.style.opacity = 0}
                                                >
                                                    <Trash2 size={11} />
                                                </button>
                                            </div>
                                        </div>
                                    );
                                })
                            )}
                        </div>
                    </section>

                    {/* Clip Jobs */}
                    <section className="os-panel" style={{ padding: '1rem' }}>
                        <h3 style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--ink)', margin: '0 0 0.75rem', display: 'flex', alignItems: 'center', gap: 6 }}>
                            <Sparkles size={14} style={{ color: 'var(--primary)' }} />
                            Clip Jobs
                            <span style={{ fontSize: '0.75rem', fontWeight: 400, color: 'var(--subtle)' }}>({clipJobs.length})</span>
                        </h3>

                        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                            {clipJobs.length === 0 ? (
                                <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--subtle)', fontSize: '0.8125rem' }}>
                                    Select videos above to generate clips.
                                </div>
                            ) : (
                                clipJobs.map(cj => {
                                    const isExpanded = expandedClipJobId === cj.id;
                                    let result = null;
                                    if (cj.result_json) {
                                        try { result = typeof cj.result_json === 'string' ? JSON.parse(cj.result_json) : cj.result_json; }
                                        catch { /* malformed json */ }
                                    }
                                    const ts = new Date(cj.created_at * 1000);
                                    const label = `${ts.toLocaleDateString()} ${ts.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;

                                    return (
                                        <div key={cj.id} className="os-panel-2" style={{ overflow: 'hidden' }}>
                                            <div
                                                onClick={() => setExpandedClipJobId(isExpanded ? null : cj.id)}
                                                style={{
                                                    padding: '0.625rem 0.75rem', display: 'flex', alignItems: 'center',
                                                    justifyContent: 'space-between', cursor: 'pointer',
                                                    transition: 'background var(--dur-fast)',
                                                }}
                                                onMouseEnter={e => e.currentTarget.style.background = 'var(--surface-2)'}
                                                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                                            >
                                                <div>
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
                                                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--muted)' }}>{label}</span>
                                                        <StatusChip status={cj.status} />
                                                    </div>
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.6875rem', color: 'var(--subtle)' }}>
                                                        <span>{cj.id.substring(0, 8)}</span>
                                                        <span>·</span>
                                                        <span>{cj.clip_count} clips</span>
                                                        {cj.video_ids && (() => {
                                                            try {
                                                                const vids = typeof cj.video_ids === 'string' ? JSON.parse(cj.video_ids) : cj.video_ids;
                                                                if (vids.length > 0) {
                                                                    const names = vids.map(vid => {
                                                                        const v = videos.find(v => v.id === vid);
                                                                        return v ? (v.source_filename || v.source_url || vid.substring(0, 8)) : vid.substring(0, 8);
                                                                    });
                                                                    return <><span>·</span><span>From: {names.join(', ')}</span></>;
                                                                }
                                                            } catch { /* ignore */ }
                                                            return null;
                                                        })()}
                                                    </div>
                                                </div>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--muted)', fontSize: '0.75rem' }}>
                                                    {isExpanded ? 'Hide' : 'Show clips'}
                                                    <ChevronRight size={14} style={{ transform: isExpanded ? 'rotate(90deg)' : 'none', transition: 'transform var(--dur-base)', color: isExpanded ? 'var(--primary)' : undefined }} />
                                                </div>
                                            </div>

                                            {isExpanded && (
                                                <div style={{ borderTop: '1px solid var(--border)', background: 'oklch(0.06 0.004 170)', padding: '1rem' }}>
                                                    {cj.status === 'queued' || cj.status === 'processing' ? (
                                                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '2rem', gap: 12 }}>
                                                            <div style={{ width: 28, height: 28, border: '2px solid var(--border-2)', borderTopColor: 'var(--primary)', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
                                                            <p style={{ fontSize: '0.8125rem', color: 'var(--muted)', margin: 0 }}>Detecting moments &amp; rendering…</p>
                                                            <div className="os-progress os-progress-indeterminate" style={{ width: 180 }}>
                                                                <div className="os-progress-bar" />
                                                            </div>
                                                        </div>
                                                    ) : cj.status === 'failed' ? (
                                                        <p style={{ fontSize: '0.8125rem', color: 'var(--error)', textAlign: 'center', padding: '1rem', margin: 0 }}>
                                                            Failed: {cj.error || 'Unknown error'}
                                                        </p>
                                                    ) : result?.clips?.length > 0 ? (
                                                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '0.75rem' }}>
                                                            {result.clips.map((clip, idx) => (
                                                                <ResultCard
                                                                    key={idx} clip={clip} index={idx} jobId={cj.id}
                                                                    uploadPostKey={uploadPostKey} uploadUserId={uploadUserId}
                                                                    geminiApiKey={geminiApiKey} elevenLabsKey={elevenLabsKey}
                                                                    onPlay={onPlayClip} onPause={onPauseClip}
                                                                />
                                                            ))}
                                                        </div>
                                                    ) : (
                                                        <p style={{ fontSize: '0.8125rem', color: 'var(--subtle)', textAlign: 'center', padding: '1rem', margin: 0 }}>No clips found for this job.</p>
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                    );
                                })
                            )}
                        </div>
                    </section>
                </div>

                {/* ── Right: Intelligence Viewer (slide-in panel) ── */}
                {viewerOpen && (
                    <div
                        className="os-fade-in"
                        style={{
                            width: 380, flexShrink: 0,
                            borderLeft: '1px solid var(--border)',
                            background: 'var(--surface)',
                            display: 'flex', flexDirection: 'column',
                            overflow: 'hidden',
                        }}
                    >
                        {/* Viewer header */}
                        <div style={{
                            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                            padding: '0.625rem 0.875rem', borderBottom: '1px solid var(--border)',
                            flexShrink: 0,
                        }}>
                            <div style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--ink)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 260 }}>
                                {selectedVideoForViewer.source_filename || selectedVideoForViewer.source_url || 'Video'}
                            </div>
                            <button onClick={() => setSelectedVideoForViewer(null)} className="os-btn os-btn-ghost os-btn-xs" style={{ padding: 5, flexShrink: 0 }} title="Close viewer">
                                <X size={14} />
                            </button>
                        </div>

                        {/* ID line */}
                        <div style={{ padding: '0.375rem 0.875rem', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
                            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.6875rem', color: 'var(--subtle)' }}>
                                {selectedVideoForViewer.id}
                            </span>
                        </div>

                        {/* Tab bar */}
                        <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
                            {[
                                { id: 'transcript', label: 'Transcript', icon: FileText },
                                ...(project.dossier_enabled ? [{ id: 'dossier', label: 'Dossier', icon: BookOpen }] : []),
                                { id: 'instructions', label: 'Instructions', icon: MessageSquare },
                            ].map(({ id, label, icon: Icon }) => (
                                <button
                                    key={id}
                                    onClick={() => setActiveViewerTab(id)}
                                    style={{
                                        flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
                                        gap: 5, padding: '0.5rem 0.25rem', fontSize: '0.75rem', fontWeight: 500,
                                        border: 'none', background: 'transparent', cursor: 'pointer',
                                        color: activeViewerTab === id ? 'var(--primary)' : 'var(--muted)',
                                        borderBottom: `2px solid ${activeViewerTab === id ? 'var(--primary)' : 'transparent'}`,
                                        transition: 'color var(--dur-fast), border-color var(--dur-fast)',
                                    }}
                                >
                                    <Icon size={12} /> {label}
                                </button>
                            ))}
                        </div>

                        {/* Tab content */}
                        <div className="os-scroll" style={{ flex: 1, overflowY: 'auto', padding: '0.875rem' }}>
                            {viewerLoading ? (
                                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: 200, gap: 10 }}>
                                    <div style={{ width: 24, height: 24, border: '2px solid var(--border-2)', borderTopColor: 'var(--primary)', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
                                    <p style={{ fontSize: '0.8125rem', color: 'var(--muted)', margin: 0 }}>Loading…</p>
                                </div>
                            ) : activeViewerTab === 'transcript' ? (
                                selectedVideoForViewer.transcript ? (
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
                                        <div className="os-log" style={{ maxHeight: 160 }}>
                                            {selectedVideoForViewer.transcript.text}
                                        </div>
                                        <div>
                                            <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--muted)', marginBottom: 6 }}>Segments</div>
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                                                {selectedVideoForViewer.transcript.segments?.map((seg, i) => (
                                                    <div key={i} className="os-panel-2" style={{ display: 'flex', gap: 10, padding: '0.375rem 0.625rem', alignItems: 'flex-start' }}>
                                                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.6875rem', color: 'var(--primary)', fontWeight: 600, flexShrink: 0, paddingTop: 1 }}>
                                                            {Math.floor(seg.start / 60)}:{String(Math.floor(seg.start % 60)).padStart(2, '0')}
                                                        </span>
                                                        <p style={{ fontSize: '0.8125rem', color: 'var(--muted)', margin: 0, lineHeight: 1.5 }}>{seg.text}</p>
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    </div>
                                ) : (
                                    <p style={{ fontSize: '0.8125rem', color: 'var(--subtle)', textAlign: 'center', padding: '2rem', margin: 0 }}>
                                        Transcript loading or empty.
                                    </p>
                                )
                            ) : activeViewerTab === 'dossier' ? (
                                selectedVideoForViewer.dossier_text ? (
                                    <div style={{ fontSize: '0.8125rem', color: 'var(--muted)', lineHeight: 1.7 }}>
                                        {selectedVideoForViewer.dossier_text.split('\n').map((line, i) => {
                                            if (line.startsWith('## ')) return <h3 key={i} style={{ fontSize: '0.9rem', fontWeight: 700, color: 'var(--ink)', margin: '1rem 0 0.375rem' }}>{line.slice(3)}</h3>;
                                            if (line.startsWith('# '))  return <h2 key={i} style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--ink)', margin: '1.25rem 0 0.5rem' }}>{line.slice(2)}</h2>;
                                            if (line.startsWith('- '))  return <li key={i} style={{ marginLeft: 16, marginBottom: 3 }}>{line.slice(2)}</li>;
                                            if (!line.trim()) return <div key={i} style={{ height: 6 }} />;
                                            return <p key={i} style={{ margin: '0 0 6px' }}>{line}</p>;
                                        })}
                                    </div>
                                ) : (
                                    <p style={{ fontSize: '0.8125rem', color: 'var(--subtle)', textAlign: 'center', padding: '2rem', margin: 0 }}>
                                        No dossier available for this video.
                                    </p>
                                )
                            ) : (
                                /* Instructions tab */
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                                    <p style={{ fontSize: '0.8125rem', color: 'var(--muted)', lineHeight: 1.55, margin: 0 }}>
                                        Instructions here apply only to this video, combined with project-level instructions and any per-job prompt.
                                    </p>
                                    <textarea
                                        value={videoInstructions}
                                        onChange={e => setVideoInstructions(e.target.value)}
                                        placeholder="e.g. 'Focus on player introductions' or 'Do not use external footage'"
                                        className="os-input os-textarea"
                                        style={{ height: 140 }}
                                    />
                                    <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                                        <button
                                            onClick={handleSaveVideoInstructions}
                                            disabled={savingVideoInstructions}
                                            className="os-btn os-btn-primary os-btn-sm"
                                        >
                                            {savingVideoInstructions
                                                ? <><RefreshCw size={12} style={{ animation: 'spin 0.6s linear infinite' }} /> Saving…</>
                                                : <><CheckSquare size={12} /> Save</>
                                            }
                                        </button>
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </div>

            {/* ── Settings Modal ── */}
            {showSettings && (
                <div className="os-modal-backdrop" onClick={() => setShowSettings(false)}>
                    <div className="os-modal" onClick={e => e.stopPropagation()}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
                            <h2 style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--ink)', margin: 0 }}>Project Settings</h2>
                            <button onClick={() => setShowSettings(false)} className="os-btn os-btn-ghost os-btn-xs" style={{ padding: 5 }}>
                                <X size={14} />
                            </button>
                        </div>

                        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                                <label style={{ fontSize: '0.8125rem', fontWeight: 500, color: 'var(--muted)' }}>Project Name</label>
                                <input type="text" value={settingsName} onChange={e => setSettingsName(e.target.value)} className="os-input" />
                            </div>

                            <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                                <label style={{ fontSize: '0.8125rem', fontWeight: 500, color: 'var(--muted)' }}>Content Type</label>
                                <select value={settingsContentType} onChange={e => setSettingsContentType(e.target.value)} className="os-input os-select">
                                    <option value="general">General</option>
                                    <option value="sports">Sports</option>
                                    <option value="podcast">Podcast</option>
                                    <option value="lecture">Lecture / Tutorial</option>
                                    <option value="gaming">Gaming</option>
                                    <option value="interview">Interview</option>
                                    <option value="comedy">Comedy</option>
                                </select>
                            </div>

                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0.75rem', background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 6 }}>
                                <div>
                                    <div style={{ fontSize: '0.875rem', fontWeight: 500, color: 'var(--ink)' }}>Dossier Analysis</div>
                                    <div style={{ fontSize: '0.75rem', color: 'var(--subtle)', marginTop: 2 }}>Upload to Gemini for visual analysis</div>
                                </div>
                                <button className="os-toggle" role="switch" aria-checked={settingsDossier} onClick={() => setSettingsDossier(!settingsDossier)} />
                            </div>

                            <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                                <label style={{ fontSize: '0.8125rem', fontWeight: 500, color: 'var(--muted)' }}>File Retention</label>
                                <select value={settingsRetention} onChange={e => setSettingsRetention(e.target.value)} className="os-input os-select">
                                    {[7, 14, 30, 90, 365].map(d => <option key={d} value={d}>{d === 365 ? '1 year' : `${d} days`}</option>)}
                                </select>
                            </div>

                            <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                                <label style={{ fontSize: '0.8125rem', fontWeight: 500, color: 'var(--muted)' }}>
                                    Standing Instructions <span style={{ color: 'var(--subtle)', fontWeight: 400 }}>(optional)</span>
                                </label>
                                <textarea
                                    rows={4}
                                    placeholder={`e.g. "Always include the coach's reaction. Minimum 20s clips."`}
                                    value={settingsInstructions}
                                    onChange={e => setSettingsInstructions(e.target.value)}
                                    className="os-input os-textarea"
                                />
                                <span style={{ fontSize: '0.75rem', color: 'var(--subtle)' }}>Auto-prepended to every clip job. Per-job prompts append after this.</span>
                            </div>
                        </div>

                        <div style={{ display: 'flex', gap: 8, marginTop: '1.25rem', paddingTop: '1rem', borderTop: '1px solid var(--border)' }}>
                            <button onClick={() => setShowSettings(false)} className="os-btn os-btn-secondary" style={{ flex: 1 }}>Cancel</button>
                            <button onClick={handleSaveSettings} disabled={savingSettings || !settingsName.trim()} className="os-btn os-btn-primary" style={{ flex: 1 }}>
                                {savingSettings ? 'Saving…' : 'Save'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Spin keyframe */}
            <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        </div>
    );
}
