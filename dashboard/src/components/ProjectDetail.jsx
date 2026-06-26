import React, { useState, useEffect } from 'react';
import { 
    ChevronLeft, FileVideo, Play, Sparkles, 
    BookOpen, FileText, CheckSquare, Trash2, 
    Activity, Clock, Download, ChevronRight,
    MessageSquare, RefreshCw, Settings, Plus
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
    
    // Viewer State
    const [selectedVideoForViewer, setSelectedVideoForViewer] = useState(null);
    const [activeViewerTab, setActiveViewerTab] = useState('transcript'); // 'transcript' | 'dossier'
    
    // Settings Modal State
    const [showSettings, setShowSettings] = useState(false);
    const [settingsName, setSettingsName] = useState(project.name);
    const [settingsDossier, setSettingsDossier] = useState(project.dossier_enabled);
    const [settingsRetention, setSettingsRetention] = useState(project.retention_days);
    const [settingsContentType, setSettingsContentType] = useState(project.content_type || 'general');
    const [settingsInstructions, setSettingsInstructions] = useState(project.custom_instructions || '');
    const [savingSettings, setSavingSettings] = useState(false);
    
    // Viewer Loading State
    const [viewerLoading, setViewerLoading] = useState(false);
    
    // UI Loading/Status States
    const [isAnalyzing, setIsAnalyzing] = useState(false);
    const [isClipping, setIsClipping] = useState(false);
    const [customPrompt, setCustomPrompt] = useState('');
    const [expandedClipJobId, setExpandedClipJobId] = useState(null);
    const [error, setError] = useState(null);
    
    // Active jobs polling tracker
    const [activeVideoJobs, setActiveVideoJobs] = useState({}); // { videoId: intervalId }
    const [activeClipJobs, setActiveClipJobs] = useState({}); // { clipJobId: intervalId }

    const fetchVideos = async () => {
        try {
            const res = await fetch(getApiUrl(`/api/projects/${project.id}/videos`));
            if (res.ok) {
                const data = await res.json();
                setVideos(data.videos || []);
                setError(null);
            } else {
                setError("Failed to load videos");
            }
        } catch (e) {
            console.error("Failed to fetch videos", e);
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
                setError("Failed to load clip jobs");
            }
        } catch (e) {
            console.error("Failed to fetch clip jobs", e);
            setError("Failed to connect to server");
        }
    };

    useEffect(() => {
        fetchVideos();
        fetchClipJobs();
        
        // Cleanup intervals on unmount
        return () => {
            Object.values(activeVideoJobs).forEach(clearInterval);
            Object.values(activeClipJobs).forEach(clearInterval);
        };
    }, [project.id]);

    // Check for active (analyzing) videos and poll their status
    useEffect(() => {
        videos.forEach(vid => {
            if (vid.status === 'analyzing' && !activeVideoJobs[vid.id]) {
                startPollingVideo(vid.id);
            }
        });
    }, [videos]);

    // Check for active (queued/processing) clip jobs and poll their status
    useEffect(() => {
        clipJobs.forEach(cj => {
            if ((cj.status === 'queued' || cj.status === 'processing') && !activeClipJobs[cj.id]) {
                startPollingClipJob(cj.id);
            }
        });
    }, [clipJobs]);

    const startPollingVideo = (videoId) => {
        const intervalId = setInterval(async () => {
            try {
                const res = await fetch(getApiUrl(`/api/projects/${project.id}/videos/${videoId}/status`));
                if (res.ok) {
                    const data = await res.json();
                    
                    // Update video status in state
                    setVideos(prevVideos => 
                        prevVideos.map(v => v.id === videoId ? { ...v, status: data.status, error: data.video?.error } : v)
                    );
                    
                    if (data.status === 'ready' || data.status === 'failed') {
                        clearInterval(intervalId);
                        setActiveVideoJobs(prev => {
                            const next = { ...prev };
                            delete next[videoId];
                            return next;
                        });
                        fetchVideos(); // Reload complete data
                    }
                }
            } catch (e) {
                console.error("Error polling video", videoId, e);
            }
        }, 3000);

        setActiveVideoJobs(prev => ({ ...prev, [videoId]: intervalId }));
    };

    const startPollingClipJob = (clipJobId) => {
        const intervalId = setInterval(async () => {
            try {
                const res = await fetch(getApiUrl(`/api/clip-jobs/${clipJobId}`));
                if (res.ok) {
                    const data = await res.json();
                    
                    // Update clip job status in state
                    setClipJobs(prevJobs => 
                        prevJobs.map(cj => cj.id === clipJobId ? { ...cj, status: data.status, error: data.error, result_json: data.result_json } : cj)
                    );
                    
                    if (data.status === 'completed' || data.status === 'failed') {
                        clearInterval(intervalId);
                        setActiveClipJobs(prev => {
                            const next = { ...prev };
                            delete next[clipJobId];
                            return next;
                        });
                        fetchClipJobs(); // Reload complete data
                    }
                }
            } catch (e) {
                console.error("Error polling clip job", clipJobId, e);
            }
        }, 3000);

        setActiveClipJobs(prev => ({ ...prev, [clipJobId]: intervalId }));
    };

    const handleUploadProcess = async ({ type, payload, acknowledged }) => {
        setIsAnalyzing(true);
        try {
            const formData = new FormData();
            formData.append('acknowledged', acknowledged ? '1' : '0');
            
            if (type === 'url') {
                formData.append('url', payload);
            } else {
                formData.append('file', payload);
            }

            const res = await fetch(getApiUrl(`/api/projects/${project.id}/videos`), {
                method: 'POST',
                headers: {
                    'X-Gemini-Key': geminiApiKey
                },
                body: formData
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || "Failed to submit video");
            }

            const result = await res.json();
            // Inject temp video in list
            const newVideoObj = {
                id: result.video_id,
                project_id: project.id,
                status: 'analyzing',
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
                headers: {
                    'Content-Type': 'application/json',
                    'X-Gemini-Key': geminiApiKey
                },
                body: JSON.stringify({
                    video_ids: selectedVideoIds,
                    detection_prompt: customPrompt
                })
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || "Failed to create clipping job");
            }

            const result = await res.json();
            setCustomPrompt('');
            setSelectedVideoIds([]);
            
            // Fetch updated jobs
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
        if (!confirm("Are you sure you want to delete this video and its files? This cannot be undone.")) return;
        try {
            const res = await fetch(getApiUrl(`/api/videos/${videoId}`), {
                method: 'DELETE'
            });
            if (res.ok) {
                setVideos(prev => prev.filter(v => v.id !== videoId));
                setSelectedVideoIds(prev => prev.filter(id => id !== videoId));
                if (selectedVideoForViewer && selectedVideoForViewer.id === videoId) {
                    setSelectedVideoForViewer(null);
                }
            }
        } catch (e) {
            console.error(e);
        }
    };

    const handleSelectVideo = (videoId, e) => {
        e.stopPropagation();
        setSelectedVideoIds(prev => 
            prev.includes(videoId) ? prev.filter(id => id !== videoId) : [...prev, videoId]
        );
    };

    const handleLoadViewer = async (video) => {
        setSelectedVideoForViewer(video);
        // If transcript or dossier aren't fully loaded, fetch video detail
        if (!video.transcript || !video.dossier_text) {
            setViewerLoading(true);
            try {
                const res = await fetch(getApiUrl(`/api/videos/${video.id}`));
                if (res.ok) {
                    const data = await res.json();
                    setVideos(prev => prev.map(v => v.id === video.id ? data : v));
                    setSelectedVideoForViewer(data);
                }
            } catch (e) {
                console.error("Failed to load video details for viewer", e);
            } finally {
                setViewerLoading(false);
            }
        }
    };

    const handleSaveSettings = async () => {
        setSavingSettings(true);
        try {
            const res = await fetch(getApiUrl(`/api/projects/${project.id}`), {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: settingsName,
                    dossier_enabled: settingsDossier,
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
                alert(err.detail || "Failed to update project");
            }
        } catch (e) {
            alert("Failed to save settings");
        } finally {
            setSavingSettings(false);
        }
    };

    return (
        <div className="h-full flex flex-col animate-[fadeIn_0.3s_ease-out]">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-white/5 pb-4 mb-4 shrink-0">
                <div className="flex items-center gap-3">
                    <button 
                        onClick={onBack}
                        className="p-2 bg-white/5 hover:bg-white/10 text-zinc-300 hover:text-white rounded-xl transition-all"
                    >
                        <ChevronLeft size={20} />
                    </button>
                    <div>
                        <span className="text-xs text-primary font-semibold tracking-wider uppercase">Project Platform</span>
                        <h1 className="text-2xl font-black text-white">{project.name}</h1>
                    </div>
                </div>
                
                <div className="flex items-center gap-4 text-xs text-zinc-500 bg-white/5 px-4 py-2 rounded-xl border border-white/5">
                    <span className="flex items-center gap-1.5"><Clock size={14} /> Retention: {project.retention_days} days</span>
                    <span className="w-1.5 h-1.5 rounded-full bg-zinc-700" />
                    <span className="flex items-center gap-1.5">
                        <BookOpen size={14} /> Dossier: {project.dossier_enabled ? 
                            <span className="text-emerald-400 font-semibold">Enabled</span> : 
                            <span className="text-zinc-400">Disabled</span>
                        }
                    </span>
                    <button
                        onClick={() => setShowSettings(true)}
                        className="ml-2 p-1.5 hover:bg-white/10 rounded-lg transition-colors"
                        title="Project Settings"
                    >
                        <Settings size={14} />
                    </button>
                </div>
            </div>

            {/* Error Banner */}
            {error && (
                <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-xl flex items-center justify-between">
                    <span className="text-xs text-red-400">{error}</span>
                    <button onClick={() => setError(null)} className="text-red-400 hover:text-red-300 text-xs">Dismiss</button>
                </div>
            )}

            {/* Content Layout */}
            <div className="flex-1 flex flex-col lg:flex-row gap-6 overflow-hidden min-h-0">
                
                {/* Left Panel: Videos, Upload, Clip Settings */}
                <div className="flex-1 flex flex-col gap-6 overflow-y-auto pr-2 custom-scrollbar min-h-0">
                    
                    {/* Add Video section */}
                    <div className="bg-surface border border-white/5 rounded-2xl p-5 shrink-0">
                        <h3 className="text-sm font-semibold text-zinc-300 mb-3 flex items-center gap-2">
                            <Plus size={16} className="text-primary" /> Analyze New Video
                        </h3>
                        <MediaInput onProcess={handleUploadProcess} isProcessing={isAnalyzing} />
                    </div>

                    {/* Videos List */}
                    <div className="bg-surface border border-white/5 rounded-2xl p-5 flex flex-col min-h-[300px]">
                        <div className="flex items-center justify-between mb-4">
                            <h3 className="text-sm font-bold text-white flex items-center gap-2">
                                <FileVideo size={16} className="text-primary" /> 
                                Videos List ({videos.length})
                            </h3>
                            
                            {selectedVideoIds.length > 0 && (
                                <button
                                    onClick={handleGenerateClips}
                                    disabled={isClipping}
                                    className="px-4 py-2 bg-gradient-to-r from-primary to-indigo-500 hover:from-primary/95 hover:to-indigo-500/95 disabled:opacity-50 text-white rounded-xl text-xs font-bold transition-all shadow-lg flex items-center gap-2 shadow-primary/20"
                                >
                                    {isClipping ? (
                                        <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                                    ) : (
                                        <Sparkles size={14} />
                                    )}
                                    {selectedVideoIds.length > 1 ? `Cross-Clip ${selectedVideoIds.length} Videos` : "Generate Clips"}
                                </button>
                            )}
                        </div>

                        {selectedVideoIds.length > 0 && (
                            <div className="mb-4 bg-white/5 border border-white/5 rounded-xl p-3 animate-[slideDown_0.2s_ease-out]">
                                <label className="block text-xs font-semibold text-zinc-400 mb-1.5 flex items-center gap-1.5">
                                    <MessageSquare size={12} /> Custom Clipping Prompt (Optional)
                                </label>
                                <textarea
                                    value={customPrompt}
                                    onChange={(e) => setCustomPrompt(e.target.value)}
                                    placeholder="Examples: 'Find funny punchlines', 'Focus on product demo moments', 'Extract key technical insights'"
                                    className="w-full text-xs bg-black/40 border border-white/10 rounded-lg p-2.5 text-white placeholder-zinc-600 focus:outline-none focus:border-primary/50 resize-none h-16"
                                />
                            </div>
                        )}

                        <div className="flex-1 overflow-y-auto space-y-2.5 max-h-[350px] pr-1 custom-scrollbar">
                            {videos.length === 0 ? (
                                <div className="h-full flex flex-col items-center justify-center text-zinc-500 py-10">
                                    <FileVideo size={36} className="text-zinc-700 mb-2" />
                                    <p className="text-xs">No videos in this project yet.</p>
                                </div>
                            ) : (
                                videos.map(vid => {
                                    const isSelected = selectedVideoIds.includes(vid.id);
                                    const hasTranscript = !!vid.transcript_json;
                                    const hasDossier = !!vid.dossier_text;
                                    const isViewerActive = selectedVideoForViewer?.id === vid.id;

                                    return (
                                        <div
                                            key={vid.id}
                                            onClick={() => vid.status === 'ready' && handleLoadViewer(vid)}
                                            className={`group border rounded-xl p-3.5 transition-all flex items-center justify-between cursor-pointer ${
                                                isViewerActive 
                                                    ? 'bg-primary/5 border-primary/20' 
                                                    : 'bg-white/[0.02] border-white/5 hover:border-white/10 hover:bg-white/[0.04]'
                                            }`}
                                        >
                                            <div className="flex items-center gap-3 min-w-0">
                                                {vid.status === 'ready' ? (
                                                    <button
                                                        onClick={(e) => handleSelectVideo(vid.id, e)}
                                                        className={`w-5 h-5 rounded flex items-center justify-center transition-all ${
                                                            isSelected 
                                                                ? 'bg-primary text-black' 
                                                                : 'border border-zinc-700 hover:border-zinc-500 group-hover:bg-white/5'
                                                        }`}
                                                    >
                                                        {isSelected && <CheckSquare size={14} />}
                                                    </button>
                                                ) : (
                                                    <div className="w-5 h-5 flex items-center justify-center">
                                                        <Activity className="text-zinc-600 animate-pulse" size={14} />
                                                    </div>
                                                )}

                                                <div className="min-w-0">
                                                    <h4 className="text-sm font-semibold text-white truncate max-w-[200px] sm:max-w-[320px]">
                                                        {vid.source_filename || vid.source_url || "Unknown video"}
                                                    </h4>
                                                    <div className="flex items-center gap-2 mt-1">
                                                        <span className={`text-[10px] px-2 py-0.5 rounded-full uppercase font-bold border ${
                                                            vid.status === 'analyzing' ? 'bg-primary/10 border-primary/20 text-primary animate-pulse' :
                                                            vid.status === 'ready' ? 'bg-green-500/10 border-green-500/20 text-green-400' :
                                                            'bg-red-500/10 border-red-500/20 text-red-400'
                                                        }`}>
                                                            {vid.status}
                                                        </span>
                                                        <span className="text-[10px] text-zinc-500">
                                                            {vid.source_type === 'youtube' ? 'YouTube' : 'Upload'}
                                                        </span>
                                                        {vid.duration_seconds > 0 && (
                                                            <span className="text-[10px] text-zinc-500 flex items-center gap-1">
                                                                • <Clock size={10} /> {Math.round(vid.duration_seconds)}s
                                                            </span>
                                                        )}
                                                    </div>
                                                </div>
                                            </div>

                                            <div className="flex items-center gap-2.5">
                                                {vid.status === 'ready' && (
                                                    <div className="flex items-center gap-2 text-xs font-semibold">
                                                        <span className={`flex items-center gap-1 px-1.5 py-0.5 rounded ${hasTranscript ? 'bg-white/5 text-zinc-300' : 'bg-red-500/5 text-red-400 opacity-60'}`}>
                                                            <FileText size={12} /> TXT
                                                        </span>
                                                        {project.dossier_enabled && (
                                                            <span className={`flex items-center gap-1 px-1.5 py-0.5 rounded ${hasDossier ? 'bg-white/5 text-zinc-300' : 'bg-yellow-500/5 text-yellow-400 opacity-60'}`}>
                                                                <BookOpen size={12} /> DOS
                                                            </span>
                                                        )}
                                                    </div>
                                                )}

                                                <button
                                                    onClick={(e) => handleDeleteVideo(vid.id, e)}
                                                    className="p-1.5 bg-red-500/5 border border-red-500/10 text-red-400 rounded-lg hover:bg-red-500/20 opacity-0 group-hover:opacity-100 transition-all shrink-0"
                                                >
                                                    <Trash2 size={13} />
                                                </button>
                                            </div>
                                        </div>
                                    );
                                })
                            )}
                        </div>
                    </div>

                    {/* Clip Jobs History */}
                    <div className="bg-surface border border-white/5 rounded-2xl p-5 flex flex-col">
                        <h3 className="text-sm font-bold text-white mb-4 flex items-center gap-2">
                            <Sparkles size={16} className="text-primary" /> Clip Jobs History ({clipJobs.length})
                        </h3>

                        <div className="space-y-3">
                            {clipJobs.length === 0 ? (
                                <div className="text-center text-zinc-500 py-10">
                                    <p className="text-xs">No clip jobs run yet. Select videos to get started.</p>
                                </div>
                            ) : (
                                clipJobs.map(cj => {
                                    const isExpanded = expandedClipJobId === cj.id;
                                    let result = null;
                                    if (cj.result_json) {
                                        try {
                                            result = typeof cj.result_json === 'string' ? JSON.parse(cj.result_json) : cj.result_json;
                                        } catch (e) {
                                            console.error("Failed to parse clips json", e);
                                        }
                                    }

                                    return (
                                        <div 
                                            key={cj.id}
                                            className="border border-white/5 bg-white/[0.01] rounded-xl overflow-hidden"
                                        >
                                            <div 
                                                onClick={() => setExpandedClipJobId(isExpanded ? null : cj.id)}
                                                className="p-3.5 flex items-center justify-between cursor-pointer hover:bg-white/[0.03] transition-all"
                                            >
                                                <div>
                                                    <div className="flex items-center gap-2">
                                                        <span className="text-xs font-mono text-zinc-500">
                                                            {new Date(cj.created_at * 1000).toLocaleDateString()} {new Date(cj.created_at * 1000).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
                                                        </span>
                                                        <span className={`text-[10px] px-2 py-0.5 rounded-full uppercase font-bold border ${
                                                            cj.status === 'queued' || cj.status === 'processing' ? 'bg-primary/10 border-primary/20 text-primary animate-pulse' :
                                                            cj.status === 'completed' ? 'bg-green-500/10 border-green-500/20 text-green-400' :
                                                            'bg-red-500/10 border-red-500/20 text-red-400'
                                                        }`}>
                                                            {cj.status}
                                                        </span>
                                                    </div>
                                                    <div className="text-[10px] text-zinc-400 mt-1 flex items-center gap-1.5">
                                                        <span>ID: {cj.id.substring(0, 8)}</span>
                                                        <span>•</span>
                                                        <span>Clips: {cj.clip_count}</span>
                                                        {cj.video_ids && (() => {
                                                            try {
                                                                const vids = typeof cj.video_ids === 'string' ? JSON.parse(cj.video_ids) : cj.video_ids;
                                                                if (vids.length > 0) {
                                                                    const sourceNames = vids.map(vid => {
                                                                        const v = videos.find(v => v.id === vid);
                                                                        return v ? (v.source_filename || v.source_url || vid.substring(0, 8)) : vid.substring(0, 8);
                                                                    });
                                                                    return (
                                                                        <>
                                                                            <span>•</span>
                                                                            <span className="text-zinc-500">From: {sourceNames.join(', ')}</span>
                                                                        </>
                                                                    );
                                                                }
                                                            } catch (e) { return null; }
                                                            return null;
                                                        })()}
                                                    </div>
                                                </div>

                                                <div className="flex items-center gap-2 text-zinc-400 hover:text-white transition-colors">
                                                    <span className="text-xs">{isExpanded ? "Hide" : "Show Clips"}</span>
                                                    <ChevronRight size={16} className={`transition-transform duration-300 ${isExpanded ? 'rotate-90 text-primary' : ''}`} />
                                                </div>
                                            </div>

                                            {isExpanded && (
                                                <div className="border-t border-white/5 bg-black/40 p-4">
                                                    {cj.status === 'queued' || cj.status === 'processing' ? (
                                                        <div className="flex flex-col items-center justify-center py-10 space-y-4">
                                                            <div className="w-10 h-10 border-2 border-zinc-800 border-t-primary rounded-full animate-spin" />
                                                            <p className="text-xs text-zinc-500">Detecting moments & rendering clips...</p>
                                                        </div>
                                                    ) : cj.status === 'failed' ? (
                                                        <div className="text-center py-6 text-red-400">
                                                            <p className="text-xs">Clipping failed: {cj.error || "Unknown error"}</p>
                                                        </div>
                                                    ) : result && result.clips && result.clips.length > 0 ? (
                                                        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                                                            {result.clips.map((clip, idx) => (
                                                                <ResultCard
                                                                    key={idx}
                                                                    clip={clip}
                                                                    index={idx}
                                                                    jobId={cj.id}
                                                                    uploadPostKey={uploadPostKey}
                                                                    uploadUserId={uploadUserId}
                                                                    geminiApiKey={geminiApiKey}
                                                                    elevenLabsKey={elevenLabsKey}
                                                                    onPlay={onPlayClip}
                                                                    onPause={onPauseClip}
                                                                />
                                                            ))}
                                                        </div>
                                                    ) : (
                                                        <div className="text-center py-6 text-zinc-500">
                                                            <p className="text-xs">No clips found for this job.</p>
                                                        </div>
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                    );
                                })
                            )}
                        </div>
                    </div>
                </div>

                {/* Right Panel: Transcript / Dossier Viewer */}
                <div className="w-full lg:w-[420px] xl:w-[480px] bg-surface border border-white/5 rounded-2xl flex flex-col overflow-hidden min-h-[400px] lg:h-full shrink-0">
                    {selectedVideoForViewer ? (
                        <div className="flex-1 flex flex-col overflow-hidden min-h-0">
                            {/* Tabs */}
                            <div className="flex border-b border-white/5 bg-black/10 shrink-0">
                                <button
                                    onClick={() => setActiveViewerTab('transcript')}
                                    className={`flex-1 flex items-center justify-center gap-2 py-3.5 text-xs font-bold border-b-2 transition-all ${
                                        activeViewerTab === 'transcript'
                                            ? 'text-primary border-primary bg-white/[0.01]'
                                            : 'text-zinc-500 border-transparent hover:text-white'
                                    }`}
                                >
                                    <FileText size={14} /> Transcript Text
                                </button>
                                {project.dossier_enabled && (
                                    <button
                                        onClick={() => setActiveViewerTab('dossier')}
                                        className={`flex-1 flex items-center justify-center gap-2 py-3.5 text-xs font-bold border-b-2 transition-all ${
                                            activeViewerTab === 'dossier'
                                                ? 'text-primary border-primary bg-white/[0.01]'
                                                : 'text-zinc-500 border-transparent hover:text-white'
                                        }`}
                                    >
                                        <BookOpen size={14} /> Forensic Dossier
                                    </button>
                                )}
                            </div>

                            {/* Viewer Content */}
                            <div className="flex-1 overflow-y-auto p-5 custom-scrollbar min-h-0">
                                <div className="mb-4">
                                    <h3 className="text-sm font-bold text-white mb-1">
                                        {selectedVideoForViewer.source_filename || selectedVideoForViewer.source_url}
                                    </h3>
                                    <p className="text-[10px] text-zinc-500 font-mono">
                                        ID: {selectedVideoForViewer.id}
                                    </p>
                                </div>

                                {activeViewerTab === 'transcript' ? (
                                    selectedVideoForViewer.transcript ? (
                                        <div className="space-y-4">
                                            <div className="text-xs text-zinc-400 leading-relaxed bg-white/[0.01] border border-white/5 rounded-xl p-3.5">
                                                {selectedVideoForViewer.transcript.text}
                                            </div>
                                            <div className="space-y-2">
                                                <h4 className="text-xs font-bold text-zinc-400">Timestamped Segments</h4>
                                                <div className="space-y-1.5">
                                                    {selectedVideoForViewer.transcript.segments?.map((seg, i) => (
                                                        <div key={i} className="flex gap-3 text-xs bg-white/[0.01] p-2 border border-white/5 rounded-lg group">
                                                            <span className="font-mono text-primary font-semibold shrink-0 select-none">
                                                                {Math.floor(seg.start / 60)}:{String(Math.floor(seg.start % 60)).padStart(2, '0')}
                                                            </span>
                                                            <p className="text-zinc-300 group-hover:text-white transition-colors">{seg.text}</p>
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        </div>
                                    ) : (
                                        <div className="text-center py-10 text-zinc-500">
                                            <p className="text-xs">Transcript loading or empty...</p>
                                        </div>
                                    )
                                ) : (
                                    viewerLoading ? (
                                        <div className="flex flex-col items-center justify-center py-10">
                                            <div className="w-8 h-8 border-2 border-zinc-800 border-t-primary rounded-full animate-spin mb-3" />
                                            <p className="text-xs text-zinc-500">Loading dossier...</p>
                                        </div>
                                    ) : selectedVideoForViewer.dossier_text ? (
                                        <div className="prose prose-invert prose-xs text-xs text-zinc-300 leading-relaxed space-y-4 bg-white/[0.01] border border-white/5 rounded-xl p-4 overflow-x-hidden select-text">
                                            {selectedVideoForViewer.dossier_text.split('\n').map((line, i) => {
                                                if (line.startsWith('##')) {
                                                    return <h3 key={i} className="text-sm font-bold text-white mt-4 mb-2">{line.replace('##', '').trim()}</h3>;
                                                }
                                                if (line.startsWith('#')) {
                                                    return <h2 key={i} className="text-base font-extrabold text-white mt-5 mb-2">{line.replace('#', '').trim()}</h2>;
                                                }
                                                if (line.startsWith('-')) {
                                                    return <li key={i} className="ml-4 list-disc mb-1">{line.replace('-', '').trim()}</li>;
                                                }
                                                return <p key={i} className="mb-2">{line}</p>;
                                            })}
                                        </div>
                                    ) : (
                                        <div className="text-center py-10 text-zinc-500">
                                            <p className="text-xs">Forensic dossier not available for this video.</p>
                                        </div>
                                    )
                                )}
                            </div>
                        </div>
                    ) : (
                        <div className="flex-1 flex flex-col items-center justify-center text-zinc-500 p-6 text-center">
                            <BookOpen size={40} className="text-zinc-800 mb-3" />
                            <h4 className="text-sm font-bold text-zinc-400 mb-1">Intelligence Viewer</h4>
                            <p className="text-xs max-w-[240px] leading-relaxed">
                                Select a completed video from the list to inspect its transcripts and AI analysis dossier.
                            </p>
                        </div>
                    )}
                </div>

            </div>

            {/* Settings Modal */}
            {showSettings && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm" onClick={() => setShowSettings(false)}>
                    <div className="bg-zinc-900 border border-white/10 rounded-2xl p-6 w-full max-w-md shadow-2xl" onClick={e => e.stopPropagation()}>
                        <h2 className="text-xl font-black text-white mb-6">Project Settings</h2>
                        
                        <div className="space-y-4">
                            <div>
                                <label className="block text-xs font-semibold text-zinc-400 mb-1.5">Project Name</label>
                                <input
                                    type="text"
                                    value={settingsName}
                                    onChange={e => setSettingsName(e.target.value)}
                                    className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-white text-sm focus:outline-none focus:border-primary transition-colors"
                                />
                            </div>
                            
                            <div>
                                <label className="block text-xs font-semibold text-zinc-400 mb-1.5">Content Type</label>
                                <select
                                    value={settingsContentType}
                                    onChange={e => setSettingsContentType(e.target.value)}
                                    className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-white text-sm focus:outline-none focus:border-primary transition-colors"
                                >
                                    <option value="general">🎬 General</option>
                                    <option value="sports">🏆 Sports</option>
                                    <option value="podcast">🎙️ Podcast</option>
                                    <option value="lecture">🎓 Lecture / Tutorial</option>
                                    <option value="gaming">🎮 Gaming</option>
                                    <option value="interview">🎤 Interview</option>
                                </select>
                            </div>

                            <div className="flex items-center justify-between">
                                <div>
                                    <label className="block text-xs font-semibold text-zinc-400">Dossier Analysis</label>
                                    <p className="text-[10px] text-zinc-600 mt-0.5">Upload videos to Gemini for visual analysis</p>
                                </div>
                                <button
                                    onClick={() => setSettingsDossier(!settingsDossier)}
                                    className={`w-11 h-6 rounded-full p-1 transition-colors duration-300 ${settingsDossier ? 'bg-primary' : 'bg-zinc-700'}`}
                                >
                                    <div className={`bg-black w-4 h-4 rounded-full shadow-md transform transition-transform duration-300 ${settingsDossier ? 'translate-x-5' : 'translate-x-0'}`} />
                                </button>
                            </div>
                            
                            <div>
                                <label className="block text-xs font-semibold text-zinc-400 mb-1.5">File Retention</label>
                                <select
                                    value={settingsRetention}
                                    onChange={e => setSettingsRetention(e.target.value)}
                                    className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-white text-sm focus:outline-none focus:border-primary transition-colors"
                                >
                                    <option value="7">7 days</option>
                                    <option value="14">14 days</option>
                                    <option value="30">30 days</option>
                                    <option value="90">90 days</option>
                                    <option value="365">1 year</option>
                                </select>
                            </div>

                            <div>
                                <label className="block text-xs font-semibold text-zinc-400 mb-1.5">
                                    Standing Instructions
                                    <span className="ml-1 text-zinc-600 font-normal normal-case">(optional)</span>
                                </label>
                                <textarea
                                    rows={4}
                                    placeholder={`e.g. "Always include the coach's reaction. Prioritise dunks over assists. Minimum 20s clips."`}
                                    value={settingsInstructions}
                                    onChange={e => setSettingsInstructions(e.target.value)}
                                    className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-white text-sm placeholder-zinc-600 focus:outline-none focus:border-primary transition-colors resize-none"
                                />
                                <p className="text-[10px] text-zinc-500 mt-1">Auto-prepended to every clip job. Per-job prompts append after this.</p>
                            </div>
                        </div>
                        
                        <div className="flex gap-3 mt-6">
                            <button
                                onClick={() => setShowSettings(false)}
                                className="flex-1 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 text-zinc-300 text-sm font-semibold transition-colors"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={handleSaveSettings}
                                disabled={savingSettings || !settingsName.trim()}
                                className="flex-1 py-2.5 rounded-xl bg-primary hover:bg-primary/80 text-black text-sm font-bold transition-colors disabled:opacity-50"
                            >
                                {savingSettings ? 'Saving...' : 'Save Settings'}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
