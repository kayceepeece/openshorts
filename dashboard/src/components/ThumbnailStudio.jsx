import React, { useState, useRef, useCallback } from 'react';
import { Upload, Image, Loader2, Send, Check, Download, ArrowRight, ArrowLeft, Sparkles, Video, Type, X, Plus, MessageSquare, FileText, Youtube, AlertCircle, CheckCircle2, Settings } from 'lucide-react';
import { getApiUrl } from '../config';

const STEPS = ['Input', 'Titles', 'Generate', 'Description', 'Publish'];

function StepIndicator({ currentStep }) {
  const st = (i) => i < currentStep ? { background: 'oklch(0.65 0.14 155 / 0.10)', border: '1px solid oklch(0.65 0.14 155 / 0.25)', color: 'var(--success)' } :
    i === currentStep ? { background: 'oklch(0.55 0.095 170 / 0.10)', border: '1px solid oklch(0.55 0.095 170 / 0.3)', color: 'var(--primary)' } :
      { background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--subtle)' };
  const badge = (i) => i < currentStep ? { background: 'var(--success)', color: 'oklch(0 0 0)' } :
    i === currentStep ? { background: 'var(--primary)', color: 'var(--primary-fg)' } :
      { background: 'var(--surface-2)', color: 'var(--subtle)' };
  return (
    <div className="flex items-center gap-2 mb-8">
      {STEPS.map((label, i) => (
        <React.Fragment key={label}>
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium transition-all"
            style={st(i)}>
            <span className="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold" style={badge(i)}>
              {i < currentStep ? <Check size={10} /> : i + 1}
            </span>
            <span className="hidden sm:inline">{label}</span>
          </div>
          {i < STEPS.length - 1 && (
            <div className="w-8 h-px" style={{ background: i < currentStep ? 'oklch(0.65 0.14 155 / 0.5)' : 'var(--border)' }} />
          )}
        </React.Fragment>
      ))}
    </div>
  );
}

function DragDropZone({ label, accept, onFile, file, onClear, icon: Icon }) {
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef(null);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setIsDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) onFile(f);
  }, [onFile]);

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  if (file) {
    return (
      <div className="os-panel-2 rounded-xl" style={{ padding: '0.75rem', display: 'flex', alignItems: 'center', gap: 12 }}>
        {file.type?.startsWith('image/') ? (
          <img src={URL.createObjectURL(file)} className="w-12 h-12 rounded-lg object-cover" alt="" />
        ) : (
          <div className="w-12 h-12 rounded-lg flex items-center justify-center" style={{ background: 'var(--surface-2)' }}>
            <Icon size={20} style={{ color: 'var(--muted)' }} />
          </div>
        )}
        <div className="flex-1 min-w-0">
          <p className="text-sm truncate" style={{ color: 'var(--ink)' }}>{file.name}</p>
          <p className="text-xs" style={{ color: 'var(--subtle)' }}>{(file.size / 1024 / 1024).toFixed(1)} MB</p>
        </div>
        <button onClick={onClear} className="os-btn os-btn-ghost os-btn-xs" style={{ color: 'var(--muted)' }}>
          <X size={16} />
        </button>
      </div>
    );
  }

  return (
    <div
      onClick={() => inputRef.current?.click()}
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={() => setIsDragging(false)}
      className="text-center cursor-pointer transition-all"
      style={{
        border: `2px dashed ${isDragging ? 'oklch(0.55 0.095 170 / 0.5)' : 'var(--border)'}`,
        borderRadius: 12, padding: '1.5rem',
        background: isDragging ? 'oklch(0.55 0.095 170 / 0.05)' : 'oklch(0.75 0 0 / 0.02)',
      }}
    >
      <Icon size={24} className="mx-auto mb-2" style={{ color: 'var(--muted)' }} />
      <p className="text-sm" style={{ color: 'var(--muted)' }}>{label}</p>
      <p className="text-xs mt-1" style={{ color: 'var(--subtle)' }}>Drop or click to upload</p>
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(e) => e.target.files[0] && onFile(e.target.files[0])}
      />
    </div>
  );
}

export default function ThumbnailStudio({ geminiApiKey, uploadPostKey, uploadUserId, onGoToSettings }) {
  // Step management
  const [step, setStep] = useState(0);
  const [mode, setMode] = useState(null); // 'video' or 'manual'

  // Step 1 state
  const [videoFile, setVideoFile] = useState(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);

  // Step 2 state
  const [sessionId, setSessionId] = useState(null);
  const [titles, setTitles] = useState([]);
  const [selectedTitle, setSelectedTitle] = useState('');
  const [manualTitle, setManualTitle] = useState('');
  const [chatInput, setChatInput] = useState('');
  const [chatHistory, setChatHistory] = useState([]);
  const [isRefining, setIsRefining] = useState(false);
  const [recommended, setRecommended] = useState([]); // [{index, reason}]

  // Step 3 state
  const [faceImage, setFaceImage] = useState(null);
  const [bgImage, setBgImage] = useState(null);
  const [extraPrompt, setExtraPrompt] = useState('');
  const [thumbnailCount, setThumbnailCount] = useState(3);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generatedThumbnails, setGeneratedThumbnails] = useState([]);

  // Description state
  const [description, setDescription] = useState('');
  const [isDescribing, setIsDescribing] = useState(false);

  // Step 4 (Publish) state
  const [selectedThumbnail, setSelectedThumbnail] = useState(null);
  const [isPublishing, setIsPublishing] = useState(false);
  const [publishResult, setPublishResult] = useState(null);

  // Background preprocessing state
  const [preprocessSessionId, setPreprocessSessionId] = useState(null);
  const [isPreprocessing, setIsPreprocessing] = useState(false);

  // Inline error banner (replaces window.alert)
  const [error, setError] = useState('');

  const chatEndRef = useRef(null);

  const scrollToBottom = () => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  const notify = (msg) => {
    setError(msg);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  // --- Background Pre-upload (starts Whisper immediately) ---
  const handlePreUpload = async (file) => {
    setPreprocessSessionId(null);
    setIsPreprocessing(true);
    try {
      const formData = new FormData();
      formData.append('file', file);

      const res = await fetch(getApiUrl('/api/thumbnail/upload'), {
        method: 'POST',
        body: formData
      });

      if (res.ok) {
        const data = await res.json();
        setPreprocessSessionId(data.session_id);
        console.log(`🎙️ Background Whisper started: ${data.session_id}`);
      } else {
        notify('Failed to pre-upload video.');
      }
    } catch (e) {
      console.error('Pre-upload failed:', e);
      notify(`Pre-upload failed: ${e.message}`);
    } finally {
      setIsPreprocessing(false);
    }
  };

  // --- Step 1: Analyze Video ---
  const handleAnalyze = async () => {
    if (!geminiApiKey) return notify('Please set your Gemini API key in Settings first.');
    setIsAnalyzing(true);

    try {
      const formData = new FormData();

      if (preprocessSessionId) {
        // Use pre-uploaded session (Whisper already running/done in background)
        formData.append('session_id', preprocessSessionId);
      } else if (videoFile) {
        formData.append('file', videoFile);
      } else {
        return notify('Please upload a video file.');
      }

      const res = await fetch(getApiUrl('/api/thumbnail/analyze'), {
        method: 'POST',
        headers: { 'X-Gemini-Key': geminiApiKey },
        body: formData
      });

      if (!res.ok) {
        const err = await res.text();
        throw new Error(err);
      }

      const data = await res.json();
      setSessionId(data.session_id);
      setTitles(data.titles || []);
      setRecommended(data.recommended || []);
      setChatHistory([{
        role: 'assistant',
        content: `Here are 10 viral title suggestions based on your video. Titles marked ⭐ are my top picks. Click one to select it, or tell me how to refine them.`
      }]);
      setStep(1);
    } catch (e) {
      notify(`Analysis failed: ${e.message}`);
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleManualMode = () => {
    setMode('manual');
    setStep(1);
  };

  // --- Step 2: Title Selection / Refinement ---
  const handleSelectTitle = (title) => {
    setSelectedTitle(title);
  };

  const handleConfirmTitle = () => {
    if (mode === 'manual' && manualTitle) {
      setSelectedTitle(manualTitle);
      // Create session for manual mode
      const newSessionId = sessionId || crypto.randomUUID();
      setSessionId(newSessionId);
      fetch(getApiUrl('/api/thumbnail/titles'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Gemini-Key': geminiApiKey
        },
        body: JSON.stringify({ title: manualTitle, session_id: newSessionId })
      }).catch(() => { });
    }
    if (selectedTitle || (mode === 'manual' && manualTitle)) {
      setStep(2);
    }
  };

  const handleRefine = async () => {
    if (!chatInput.trim() || !sessionId) return;
    setIsRefining(true);

    const userMsg = chatInput.trim();
    setChatInput('');
    setChatHistory(prev => [...prev, { role: 'user', content: userMsg }]);

    try {
      const res = await fetch(getApiUrl('/api/thumbnail/titles'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Gemini-Key': geminiApiKey
        },
        body: JSON.stringify({ session_id: sessionId, message: userMsg })
      });

      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setTitles(data.titles || []);
      setChatHistory(prev => [...prev, {
        role: 'assistant',
        content: `Here are refined titles based on your feedback. Click one to select it.`
      }]);
      setTimeout(scrollToBottom, 100);
    } catch (e) {
      setChatHistory(prev => [...prev, {
        role: 'assistant',
        content: `Failed to refine: ${e.message}`
      }]);
    } finally {
      setIsRefining(false);
    }
  };

  // --- Step 3: Generate Thumbnails ---
  const handleGenerate = async () => {
    if (!geminiApiKey) return notify('Please set your Gemini API key in Settings first.');
    const finalTitle = selectedTitle || manualTitle;
    if (!finalTitle) return notify('Please select or enter a title first.');

    setIsGenerating(true);
    setGeneratedThumbnails([]);

    try {
      const formData = new FormData();
      formData.append('session_id', sessionId || 'manual');
      formData.append('title', finalTitle);
      formData.append('extra_prompt', extraPrompt);
      formData.append('count', thumbnailCount);
      if (faceImage) formData.append('face', faceImage);
      if (bgImage) formData.append('background', bgImage);

      const res = await fetch(getApiUrl('/api/thumbnail/generate'), {
        method: 'POST',
        headers: { 'X-Gemini-Key': geminiApiKey },
        body: formData
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => null);
        throw new Error(errData?.detail || `Server error ${res.status}`);
      }

      const data = await res.json();
      if (!data.thumbnails || data.thumbnails.length === 0) {
        throw new Error('No thumbnails were generated. Your Gemini API key may not have access to image generation.');
      }
      setGeneratedThumbnails(data.thumbnails);
    } catch (e) {
      notify(`Generation failed: ${e.message}`);
    } finally {
      setIsGenerating(false);
    }
  };

  const handleDownload = async (url) => {
    try {
      const response = await fetch(getApiUrl(url));
      const blob = await response.blob();
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      a.download = url.split('/').pop() || 'thumbnail.png';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(blobUrl);
    } catch {
      // Fallback: open in new tab if fetch fails
      window.open(getApiUrl(url), '_blank');
    }
  };

  // --- Description Generation ---
  const handleGenerateDescription = async () => {
    if (!geminiApiKey) return notify('Please set your Gemini API key in Settings first.');
    const finalTitle = selectedTitle || manualTitle;
    if (!finalTitle) return notify('Please select a title first.');
    if (!sessionId) return notify('No session available.');

    setIsDescribing(true);
    try {
      const res = await fetch(getApiUrl('/api/thumbnail/describe'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Gemini-Key': geminiApiKey
        },
        body: JSON.stringify({ session_id: sessionId, title: finalTitle })
      });

      if (!res.ok) {
        const err = await res.text();
        throw new Error(err);
      }

      const data = await res.json();
      setDescription(data.description || '');
    } catch (e) {
      notify(`Description generation failed: ${e.message}`);
    } finally {
      setIsDescribing(false);
    }
  };

  // --- Publish to YouTube ---
  const handlePublish = async () => {
    if (!uploadPostKey || !uploadUserId) return notify('Please configure your Upload-Post API key and user in Settings first.');
    const finalTitle = selectedTitle || manualTitle;
    if (!finalTitle) return notify('No title selected.');
    if (!selectedThumbnail) return notify('Please select a thumbnail first.');
    if (!description) return notify('Please generate or write a description first.');

    setIsPublishing(true);
    setPublishResult(null);
    try {
      const formData = new FormData();
      formData.append('session_id', sessionId);
      formData.append('title', finalTitle);
      formData.append('description', description);
      formData.append('thumbnail_url', selectedThumbnail);
      formData.append('api_key', uploadPostKey);
      formData.append('user_id', uploadUserId);

      // Submit the publish job — returns immediately with a publish_id
      const res = await fetch(getApiUrl('/api/thumbnail/publish'), {
        method: 'POST',
        body: formData
      });

      if (!res.ok) {
        const err = await res.text();
        throw new Error(err);
      }

      const { publish_id } = await res.json();

      // Poll for status every 2 seconds (upload can take minutes for large videos)
      await new Promise((resolve, reject) => {
        const interval = setInterval(async () => {
          try {
            const statusRes = await fetch(getApiUrl(`/api/thumbnail/publish/status/${publish_id}`));
            if (!statusRes.ok) { clearInterval(interval); reject(new Error('Status check failed')); return; }
            const statusData = await statusRes.json();

            if (statusData.status === 'done') {
              clearInterval(interval);
              setPublishResult({ success: true, data: statusData.result });
              resolve();
            } else if (statusData.status === 'failed') {
              clearInterval(interval);
              reject(new Error(statusData.error || 'Upload failed'));
            }
            // 'uploading' → keep polling
          } catch ( _e ) {
            clearInterval(interval);
            reject(_e);
          }
        }, 2000);
      });

    } catch (e) {
      setPublishResult({ success: false, error: e.message });
    } finally {
      setIsPublishing(false);
    }
  };

  const handleReset = () => {
    setStep(0);
    setMode(null);
    setVideoFile(null);
    setSessionId(null);
    setTitles([]);
    setSelectedTitle('');
    setManualTitle('');
    setChatInput('');
    setChatHistory([]);
    setFaceImage(null);
    setBgImage(null);
    setExtraPrompt('');
    setGeneratedThumbnails([]);
    setDescription('');
    setIsDescribing(false);
    setSelectedThumbnail(null);
    setIsPublishing(false);
    setPublishResult(null);
    setPreprocessSessionId(null);
    setIsPreprocessing(false);
    setRecommended([]);
    setError('');
  };

  return (
    <div className="h-full overflow-y-auto p-6 md:p-8 os-fade-in">
      <div className="max-w-5xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-2">
          <h1 className="text-2xl font-bold flex items-center gap-3" style={{ color: 'var(--ink)' }}>
            <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: 'linear-gradient(135deg, oklch(0.55 0.095 170), oklch(0.40 0.080 170))' }}>
              <Image size={20} style={{ color: 'var(--primary-fg)' }} />
            </div>
            YouTube Studio
          </h1>
          {step > 0 && (
            <button onClick={handleReset} className="os-btn os-btn-ghost os-btn-sm">
              <Plus size={12} /> New Project
            </button>
          )}
        </div>
        <p className="text-sm mb-6" style={{ color: 'var(--muted)' }}>Generate viral titles, AI thumbnails, descriptions and publish directly to YouTube</p>

        <StepIndicator currentStep={step} />

        {/* Inline error banner (replaces alert) */}
        {error && (
          <div className="os-chip os-chip-error mb-6" style={{ display: 'flex', alignItems: 'flex-start', gap: 8, whiteSpace: 'normal', lineHeight: 1.5, padding: '0.75rem 1rem' }}>
            <AlertCircle size={16} className="shrink-0" style={{ marginTop: 1 }} />
            <div>
              <p className="text-sm font-semibold" style={{ color: 'var(--error)' }}>Something needs attention</p>
              <p className="text-xs mt-0.5" style={{ color: 'var(--error)' }}>{error}</p>
            </div>
          </div>
        )}

        {/* Gemini API Key Warning */}
        {!geminiApiKey && (
          <div className="mb-6 p-5 rounded-xl flex items-start gap-3" style={{ background: 'oklch(0.75 0.14 65 / 0.08)', border: '1px solid oklch(0.75 0.14 65 / 0.25)' }}>
            <AlertCircle size={20} className="shrink-0 mt-0.5" style={{ color: 'var(--warning)' }} />
            <div>
              <p className="text-sm font-semibold" style={{ color: 'var(--warning)' }}>Gemini API Key Required</p>
              <p className="text-xs mt-1" style={{ color: 'oklch(0.8 0.07 65 / 0.8)' }}>YouTube Studio requires a Google Gemini API key to function. Please configure it in the <strong>Settings</strong> tab before using this feature. Gemini's free tier includes 1,500 requests per day.</p>
            </div>
          </div>
        )}

        {/* ===== STEP 0: Input Mode Selection ===== */}
        {step === 0 && (
          <div className={`grid md:grid-cols-2 gap-6 ${!geminiApiKey ? 'opacity-50 pointer-events-none select-none' : ''}`}>
            {/* Mode A: Video Analysis */}
            <div className="os-panel p-6 space-y-4">
              <div className="flex items-center gap-3 mb-2">
                <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: 'oklch(0.55 0.095 170 / 0.12)' }}>
                  <Video size={16} style={{ color: 'var(--primary)' }} />
                </div>
                <div>
                  <h3 className="text-sm font-semibold" style={{ color: 'var(--ink)' }}>Analyze Video</h3>
                  <p className="text-xs" style={{ color: 'var(--muted)' }}>AI suggests viral titles from your content</p>
                </div>
              </div>

              <DragDropZone
                label="Upload video file"
                accept="video/*"
                onFile={(f) => { setVideoFile(f); setMode('video'); handlePreUpload(f); }}
                file={videoFile}
                onClear={() => { setVideoFile(null); setPreprocessSessionId(null); }}
                icon={Video}
              />

              {isPreprocessing && (
                <div className="flex items-center gap-2 text-xs rounded-lg px-3 py-2" style={{ color: 'var(--primary)', background: 'oklch(0.55 0.095 170 / 0.08)', border: '1px solid oklch(0.55 0.095 170 / 0.2)' }}>
                  <Loader2 size={12} className="animate-spin" />
                  Pre-processing video (Whisper transcription starting)...
                </div>
              )}
              {preprocessSessionId && !isPreprocessing && (
                <div className="flex items-center gap-2 text-xs rounded-lg px-3 py-2" style={{ color: 'var(--success)', background: 'oklch(0.65 0.14 155 / 0.08)', border: '1px solid oklch(0.65 0.14 155 / 0.2)' }}>
                  <Check size={12} />
                  Video uploaded — transcription running in background
                </div>
              )}

              <button
                onClick={handleAnalyze}
                disabled={isAnalyzing || !videoFile}
                className="os-btn os-btn-primary w-full"
                style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, padding: '0.625rem', fontSize: '0.875rem', fontWeight: 600 }}
              >
                {isAnalyzing ? (
                  <>
                    <Loader2 size={16} className="animate-spin" />
                    Analyzing video...
                  </>
                ) : (
                  <>
                    <Sparkles size={16} />
                    Analyze & Get Titles
                  </>
                )}
              </button>
            </div>

            {/* Mode B: Manual Title */}
            <div className="os-panel p-6 space-y-4 flex flex-col">
              <div className="flex items-center gap-3 mb-2">
                <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: 'oklch(0.55 0.095 170 / 0.12)' }}>
                  <Type size={16} style={{ color: 'var(--primary)' }} />
                </div>
                <div>
                  <h3 className="text-sm font-semibold" style={{ color: 'var(--ink)' }}>Write Your Own</h3>
                  <p className="text-xs" style={{ color: 'var(--muted)' }}>Skip analysis, enter your video title directly</p>
                </div>
              </div>

              <div className="flex-1 flex flex-col justify-center">
                <input
                  type="text"
                  value={manualTitle}
                  onChange={(e) => setManualTitle(e.target.value)}
                  placeholder="Enter your YouTube title..."
                  className="os-input text-sm mb-4"
                  maxLength={70}
                />
                <p className="text-xs mb-4" style={{ color: 'var(--subtle)' }}>{manualTitle.length}/70 characters</p>
              </div>

              <button
                onClick={handleManualMode}
                disabled={!manualTitle.trim()}
                className="os-btn os-btn-secondary w-full"
                style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}
              >
                <ArrowRight size={16} />
                Use This Title
              </button>
            </div>
          </div>
        )}

        {/* ===== STEP 1: Title Selection ===== */}
        {step === 1 && (
          <div className="grid md:grid-cols-5 gap-6">
            {/* Left: Chat / Controls */}
            <div className="md:col-span-2 flex flex-col gap-4">
              {mode === 'manual' ? (
                <div className="os-panel p-6 space-y-4">
                  <h3 className="text-sm font-semibold" style={{ color: 'var(--ink)' }}>Your Title</h3>
                  <input
                    type="text"
                    value={manualTitle}
                    onChange={(e) => setManualTitle(e.target.value)}
                    className="os-input text-sm"
                    maxLength={70}
                  />
                  <p className="text-xs" style={{ color: 'var(--subtle)' }}>{manualTitle.length}/70 characters</p>
                  <button
                    onClick={handleConfirmTitle}
                    disabled={!manualTitle.trim()}
                    className="os-btn os-btn-primary w-full"
                    style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}
                  >
                    <ArrowRight size={16} />
                    Continue to Thumbnails
                  </button>
                </div>
              ) : (
                <div className="os-panel p-4 flex flex-col" style={{ height: 500 }}>
                  <div className="flex items-center gap-2 mb-3 pb-3" style={{ borderBottom: '1px solid var(--border)' }}>
                    <MessageSquare size={14} style={{ color: 'var(--primary)' }} />
                    <span className="text-xs font-medium" style={{ color: 'var(--muted)' }}>Title Refinement Chat</span>
                  </div>

                  {/* Chat messages */}
                  <div className="flex-1 overflow-y-auto space-y-3 os-scroll mb-3">
                    {chatHistory.map((msg, i) => (
                      <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                        <div className={`max-w-[90%] px-3 py-2 rounded-xl text-xs ${msg.role === 'user'
                          ? 'os-chip-primary'
                          : ''
                          }`}
                          style={msg.role === 'user'
                            ? { background: 'oklch(0.55 0.095 170 / 0.10)', border: '1px solid oklch(0.55 0.095 170 / 0.2)', color: 'var(--primary)' }
                            : { background: 'oklch(0.75 0 0 / 0.04)', border: '1px solid var(--border)', color: 'var(--muted)' }}
                        >
                          {msg.content}
                        </div>
                      </div>
                    ))}
                    <div ref={chatEndRef} />
                  </div>

                  {/* Chat input */}
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={chatInput}
                      onChange={(e) => setChatInput(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleRefine()}
                      placeholder="Make them more clickbait..."
                      className="os-input text-xs flex-1"
                      disabled={isRefining}
                    />
                    <button
                      onClick={handleRefine}
                      disabled={isRefining || !chatInput.trim()}
                      className="os-btn os-btn-primary"
                      style={{ padding: '0.625rem', borderRadius: 10 }}
                    >
                      {isRefining ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                    </button>
                  </div>
                </div>
              )}

              {mode !== 'manual' && selectedTitle && (
                <button
                  onClick={handleConfirmTitle}
                  className="os-btn os-btn-primary w-full"
                  style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}
                >
                  <ArrowRight size={16} />
                  Use Selected Title
                </button>
              )}
            </div>

            {/* Right: Title Cards */}
            <div className="md:col-span-3 space-y-3">
              {selectedTitle && (
                <div className="p-3 rounded-xl flex items-center gap-2 text-sm" style={{ background: 'oklch(0.65 0.14 155 / 0.08)', border: '1px solid oklch(0.65 0.14 155 / 0.2)' }}>
                  <Check size={14} className="shrink-0" style={{ color: 'var(--success)' }} />
                  <span className="font-medium truncate" style={{ color: 'var(--success)' }}>Selected: {selectedTitle}</span>
                </div>
              )}

              {titles.length > 0 && (
                <div className="space-y-2">
                  {titles.map((title, i) => {
                    const rec = recommended.find(r => r.index === i);
                    const recRank = recommended.findIndex(r => r.index === i);
                    return (
                      <button
                        key={i}
                        onClick={() => handleSelectTitle(title)}
                        className={`w-full text-left p-4 rounded-xl border transition-all text-sm ${selectedTitle === title
                          ? 'active'
                          : ''
                          }`}
                        style={{
                          borderColor: selectedTitle === title ? 'oklch(0.55 0.095 170 / 0.4)' :
                            rec ? 'oklch(0.75 0.14 65 / 0.25)' : 'var(--border)',
                          background: selectedTitle === title ? 'oklch(0.55 0.095 170 / 0.08)' :
                            rec ? 'oklch(0.75 0.14 65 / 0.05)' : 'oklch(0.75 0 0 / 0.02)',
                          color: selectedTitle === title ? 'var(--ink)' : 'var(--muted)',
                        }}
                      >
                        <div className="flex items-start gap-3">
                          <span className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 mt-0.5`}
                            style={{
                              background: selectedTitle === title ? 'var(--primary)' :
                                rec ? 'var(--warning)' : 'var(--surface-2)',
                              color: selectedTitle === title ? 'var(--primary-fg)' :
                                rec ? 'oklch(0.1 0 0)' : 'var(--muted)',
                            }}
                          >
                            {selectedTitle === title ? <Check size={10} /> : rec ? '★' : i + 1}
                          </span>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="leading-relaxed">{title}</span>
                              {rec && (
                                <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full shrink-0" style={{ background: 'oklch(0.75 0.14 65 / 0.15)', color: 'var(--warning)', border: '1px solid oklch(0.75 0.14 65 / 0.25)' }}>
                                  {recRank === 0 ? '⭐ TOP PICK' : '⭐ 2nd PICK'}
                                </span>
                              )}
                            </div>
                            {rec && (
                              <p className="text-[11px] mt-1.5 leading-relaxed italic" style={{ color: 'oklch(0.8 0.07 65 / 0.7)' }}>{rec.reason}</p>
                            )}
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}

              {isRefining && (
                <div className="flex items-center justify-center py-8" style={{ color: 'var(--muted)' }}>
                  <Loader2 size={20} className="animate-spin mr-2" />
                  <span className="text-sm">Refining titles...</span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ===== STEP 2: Thumbnail Generation ===== */}
        {step === 2 && (
          <div className="grid md:grid-cols-5 gap-6">
            {/* Left: Controls */}
            <div className="md:col-span-2 space-y-4">
              <div className="os-panel p-6 space-y-4">
                <h3 className="text-sm font-semibold mb-1" style={{ color: 'var(--ink)' }}>Selected Title</h3>
                <div className="p-3 rounded-lg text-sm" style={{ background: 'oklch(0.55 0.095 170 / 0.08)', border: '1px solid oklch(0.55 0.095 170 / 0.25)', color: 'var(--primary)' }}>
                  {selectedTitle || manualTitle}
                </div>

                <button
                  onClick={() => setStep(1)}
                  className="os-btn os-btn-ghost os-btn-xs"
                >
                  <ArrowLeft size={12} /> Change title
                </button>
              </div>

              <div className="os-panel p-6 space-y-4">
                <h3 className="text-sm font-semibold" style={{ color: 'var(--ink)' }}>Face Image <span style={{ color: 'var(--subtle)', fontWeight: 400 }}>(optional)</span></h3>
                <DragDropZone
                  label="Upload face / person photo"
                  accept="image/*"
                  onFile={setFaceImage}
                  file={faceImage}
                  onClear={() => setFaceImage(null)}
                  icon={Upload}
                />
              </div>

              <div className="os-panel p-6 space-y-4">
                <h3 className="text-sm font-semibold" style={{ color: 'var(--ink)' }}>Background Image <span style={{ color: 'var(--subtle)', fontWeight: 400 }}>(optional)</span></h3>
                <DragDropZone
                  label="Upload background image"
                  accept="image/*"
                  onFile={setBgImage}
                  file={bgImage}
                  onClear={() => setBgImage(null)}
                  icon={Image}
                />
              </div>

              <div className="os-panel p-6 space-y-4">
                <h3 className="text-sm font-semibold" style={{ color: 'var(--ink)' }}>Extra Instructions <span style={{ color: 'var(--subtle)', fontWeight: 400 }}>(optional)</span></h3>
                <textarea
                  value={extraPrompt}
                  onChange={(e) => setExtraPrompt(e.target.value)}
                  placeholder="e.g. Use red and black colors, dramatic lighting, include money emojis..."
                  className="os-input os-textarea text-sm resize-none"
                  style={{ height: 80 }}
                />
              </div>

              <div className="os-panel p-6 space-y-4">
                <h3 className="text-sm font-semibold" style={{ color: 'var(--ink)' }}>Number of Thumbnails</h3>
                <div className="flex gap-2">
                  {[1, 2, 3, 4].map(n => (
                    <button
                      key={n}
                      onClick={() => setThumbnailCount(n)}
                      className="flex-1 py-2 rounded-lg text-sm font-medium transition-all"
                      style={{
                        background: thumbnailCount === n ? 'oklch(0.55 0.095 170 / 0.12)' : 'var(--surface-2)',
                        border: `1px solid ${thumbnailCount === n ? 'oklch(0.55 0.095 170 / 0.35)' : 'var(--border)'}`,
                        color: thumbnailCount === n ? 'var(--primary)' : 'var(--muted)',
                      }}
                    >
                      {n}
                    </button>
                  ))}
                </div>
              </div>

              <button
                onClick={handleGenerate}
                disabled={isGenerating}
                className="os-btn os-btn-primary w-full"
                style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, padding: '0.875rem', fontWeight: 700 }}
              >
                {isGenerating ? (
                  <>
                    <Loader2 size={16} className="animate-spin" />
                    Generating thumbnails...
                  </>
                ) : (
                  <>
                    <Sparkles size={16} />
                    Generate Thumbnails
                  </>
                )}
              </button>

            </div>

            {/* Right: Generated Thumbnails */}
            <div className="md:col-span-3">
              {generatedThumbnails.length > 0 ? (
                <div className="space-y-4">
                  <h3 className="text-sm font-semibold" style={{ color: 'var(--muted)' }}>Generated Thumbnails — click to select for publishing</h3>
                  <div className="grid gap-4">
                    {generatedThumbnails.map((url, i) => (
                      <div
                        key={i}
                        onClick={() => setSelectedThumbnail(url)}
                        className="os-panel group relative cursor-pointer overflow-hidden transition-all"
                        style={{
                          boxShadow: selectedThumbnail === url ? '0 0 0 2px oklch(0.55 0.095 170 / 0.5)' : 'none',
                          padding: 0,
                        }}
                      >
                        <img
                          src={getApiUrl(url)}
                          alt={`Thumbnail ${i + 1}`}
                          className="w-full aspect-video object-cover"
                        />
                        <div className="absolute inset-0 flex items-center justify-center gap-3" style={{ background: 'oklch(0 0 0 / 0)', opacity: 0, transition: 'all 200ms' }}
                          onMouseEnter={(e) => { e.currentTarget.style.background = 'oklch(0 0 0 / 0.4)'; e.currentTarget.style.opacity = 1; }}
                          onMouseLeave={(e) => { e.currentTarget.style.background = 'oklch(0 0 0 / 0)'; e.currentTarget.style.opacity = 0; }}>
                          <button
                            onClick={(e) => { e.stopPropagation(); handleDownload(url); }}
                            className="os-btn os-btn-lg"
                            style={{ gap: 8, fontWeight: 600 }}
                          >
                            <Download size={14} />
                            Download
                          </button>
                        </div>
                        <div className="p-3 flex items-center justify-between">
                          <span className="text-xs flex items-center gap-2" style={{ color: 'var(--muted)' }}>
                            Thumbnail {i + 1}
                            {selectedThumbnail === url && (
                              <span className="flex items-center gap-1" style={{ color: 'var(--primary)' }}><Check size={10} /> Selected</span>
                            )}
                          </span>
                          <button
                            onClick={(e) => { e.stopPropagation(); handleDownload(url); }}
                            className="os-btn os-btn-ghost os-btn-xs text-xs flex items-center gap-1"
                          >
                            <Download size={12} /> Save
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* Regenerate */}
                  <button
                    onClick={handleGenerate}
                    disabled={isGenerating}
                    className="os-btn os-btn-secondary w-full"
                    style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}
                  >
                    {isGenerating ? (
                      <>
                        <Loader2 size={14} className="animate-spin" />
                        Regenerating...
                      </>
                    ) : (
                      <>
                        <Sparkles size={14} />
                        Regenerate
                      </>
                    )}
                  </button>

                  {/* Proceed to Description */}
                  {selectedThumbnail && (
                    <button
                      onClick={() => setStep(3)}
                      className="os-btn os-btn-primary w-full"
                      style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, fontWeight: 700 }}
                    >
                      <ArrowRight size={16} />
                      Next: Description
                    </button>
                  )}
                </div>
              ) : isGenerating ? (
                <div className="h-full flex flex-col items-center justify-center space-y-4 min-h-[400px]" style={{ color: 'var(--muted)' }}>
                  <div className="w-16 h-16 rounded-full" style={{ border: '2px solid var(--surface-2)', borderTopColor: 'var(--primary)' }} />
                  <div className="text-center">
                    <p className="text-sm font-medium" style={{ color: 'var(--muted)' }}>Generating thumbnails...</p>
                    <p className="text-xs mt-1" style={{ color: 'var(--subtle)' }}>This may take a minute per thumbnail</p>
                  </div>
                </div>
              ) : (
                <div className="h-full flex flex-col items-center justify-center space-y-4 min-h-[400px]" style={{ color: 'var(--muted)' }}>
                  <div className="w-20 h-20 rounded-2xl flex items-center justify-center" style={{ background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
                    <Image size={32} style={{ color: 'var(--subtle)' }} />
                  </div>
                  <div className="text-center">
                    <p className="text-sm" style={{ color: 'var(--muted)' }}>Your thumbnails will appear here</p>
                    <p className="text-xs mt-1" style={{ color: 'var(--subtle)' }}>Configure options and click Generate</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ===== STEP 3: YouTube Description ===== */}
        {step === 3 && (
          <div className="grid md:grid-cols-5 gap-6">
            {/* Left: Context & Controls */}
            <div className="md:col-span-2 space-y-4">
              <button
                onClick={() => setStep(2)}
                className="os-btn os-btn-ghost text-xs mb-2"
              >
                <ArrowLeft size={12} /> Back to Generate
              </button>

              {/* Selected Thumbnail Preview */}
              {selectedThumbnail && (
                <div className="os-panel overflow-hidden" style={{ padding: 0 }}>
                  <img
                    src={getApiUrl(selectedThumbnail)}
                    alt="Selected thumbnail"
                    className="w-full aspect-video object-cover"
                  />
                  <div className="p-3">
                    <span className="text-xs flex items-center gap-1" style={{ color: 'var(--success)' }}><Check size={10} /> Selected Thumbnail</span>
                  </div>
                </div>
              )}

              {/* Title */}
              <div className="os-panel p-6 space-y-3">
                <h3 className="text-sm font-semibold" style={{ color: 'var(--ink)' }}>Video Title</h3>
                <div className="p-3 rounded-lg text-sm" style={{ background: 'oklch(0.55 0.095 170 / 0.08)', border: '1px solid oklch(0.55 0.095 170 / 0.25)', color: 'var(--primary)' }}>
                  {selectedTitle || manualTitle}
                </div>
              </div>

              {/* Generate Description Button */}
              {mode === 'video' && (
                <div className="os-panel p-6 space-y-4">
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold flex items-center gap-2" style={{ color: 'var(--ink)' }}>
                      <Sparkles size={14} style={{ color: 'var(--primary)' }} />
                      AI Description
                    </h3>
                    <span className="text-[10px]" style={{ color: 'var(--subtle)' }}>with chapters</span>
                  </div>
                  <p className="text-xs" style={{ color: 'var(--muted)' }}>
                    Generate a YouTube description with chapter timestamps from your video transcript.
                  </p>
                  <button
                    onClick={handleGenerateDescription}
                    disabled={isDescribing}
                    className="os-btn os-btn-secondary w-full"
                    style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}
                  >
                    {isDescribing ? (
                      <>
                        <Loader2 size={14} className="animate-spin" />
                        Generating description...
                      </>
                    ) : (
                      <>
                        <FileText size={14} />
                        {description ? 'Regenerate Description' : 'Generate Description'}
                      </>
                    )}
                  </button>
                </div>
              )}

              {/* Next: Publish */}
              {description && (
                <button
                  onClick={() => setStep(4)}
                  className="os-btn os-btn-primary w-full"
                  style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, fontWeight: 700 }}
                >
                  <ArrowRight size={16} />
                  Next: Publish
                </button>
              )}
            </div>

            {/* Right: Editable Description */}
            <div className="md:col-span-3 space-y-4">
              <div className="os-panel p-6 space-y-4 h-full flex flex-col">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold flex items-center gap-2" style={{ color: 'var(--ink)' }}>
                    <FileText size={14} style={{ color: 'var(--error)' }} />
                    YouTube Description
                  </h3>
                  <span className="text-[10px]" style={{ color: 'var(--subtle)' }}>{description.length}/5000</span>
                </div>

                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder={mode === 'video'
                    ? "Click 'Generate Description' to auto-generate with chapters, or write your own..."
                    : "Write your YouTube video description here..."
                  }
                  className="os-input os-textarea text-sm resize-none flex-1 font-mono os-scroll"
                  style={{ minHeight: '500px' }}
                  maxLength={5000}
                />

                {!description && (
                  <p className="text-xs" style={{ color: 'var(--subtle)' }}>
                    {mode === 'video'
                      ? "AI will generate a compelling description with chapter timestamps from your video's Whisper transcript."
                      : "Write a description for your YouTube video. You can proceed to publish once you have a description."}
                  </p>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ===== STEP 4: Publish to YouTube ===== */}
        {step === 4 && (
          <div className="grid md:grid-cols-5 gap-6">
            {/* Left: Summary & Publish */}
            <div className="md:col-span-2 space-y-4">
              <button
                onClick={() => setStep(3)}
                className="os-btn os-btn-ghost text-xs mb-2"
              >
                <ArrowLeft size={12} /> Back to Description
              </button>

              {/* Selected Thumbnail Preview */}
              {selectedThumbnail && (
                <div className="os-panel overflow-hidden" style={{ padding: 0 }}>
                  <img
                    src={getApiUrl(selectedThumbnail)}
                    alt="Selected thumbnail"
                    className="w-full aspect-video object-cover"
                  />
                  <div className="p-3">
                    <span className="text-xs flex items-center gap-1" style={{ color: 'var(--success)' }}><Check size={10} /> Selected Thumbnail</span>
                  </div>
                </div>
              )}

              {/* Editable Title */}
              <div className="os-panel p-6 space-y-3">
                <h3 className="text-sm font-semibold" style={{ color: 'var(--ink)' }}>Video Title</h3>
                <input
                  type="text"
                  value={selectedTitle || manualTitle}
                  onChange={(e) => selectedTitle ? setSelectedTitle(e.target.value) : setManualTitle(e.target.value)}
                  className="os-input text-sm"
                  maxLength={100}
                />
              </div>

              {/* Publish Button */}
              {(!uploadPostKey || !uploadUserId) ? (
                <div className="os-panel p-6 space-y-3">
                  <div className="flex items-center gap-2" style={{ color: 'var(--warning)' }}>
                    <AlertCircle size={16} />
                    <span className="text-sm font-medium">Upload-Post Not Configured</span>
                  </div>
                  <p className="text-xs" style={{ color: 'var(--muted)' }}>
                    To publish directly to YouTube, configure your Upload-Post API key and connect a profile in Settings.
                  </p>
                  <button
                    onClick={onGoToSettings}
                    className="os-btn os-btn-ghost os-btn-sm"
                    style={{ color: 'var(--primary)' }}
                  >
                    <Settings size={12} /> Go to Settings
                  </button>
                </div>
              ) : (
                <button
                  onClick={handlePublish}
                  disabled={isPublishing}
                  className="os-btn os-btn-lg w-full"
                  style={{ background: 'oklch(0.62 0.18 25)', color: 'oklch(0.95 0 0)', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, fontWeight: 700 }}
                >
                  {isPublishing ? (
                    <>
                      <Loader2 size={16} className="animate-spin" />
                      Publishing to YouTube...
                    </>
                  ) : (
                    <>
                      <Youtube size={16} />
                      Publish to YouTube
                    </>
                  )}
                </button>
              )}

              {/* Publish Result */}
              {publishResult && (
                <div className={`os-panel p-4 ${publishResult.success ? 'success' : 'error'}`}
                  style={{ borderColor: publishResult.success ? 'oklch(0.65 0.14 155 / 0.3)' : 'oklch(0.62 0.18 25 / 0.3)' }}
                >
                  {publishResult.success ? (
                    <div className="flex items-center gap-2" style={{ color: 'var(--success)' }}>
                      <CheckCircle2 size={16} />
                      <div>
                        <p className="text-sm font-medium">Published successfully!</p>
                        <p className="text-xs mt-1" style={{ color: 'var(--muted)' }}>Your video is being uploaded to YouTube asynchronously.</p>
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2" style={{ color: 'var(--error)' }}>
                      <AlertCircle size={16} />
                      <div>
                        <p className="text-sm font-medium">Publish failed</p>
                        <p className="text-xs mt-1" style={{ color: 'var(--muted)' }}>{publishResult.error}</p>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Right: Description Preview (read-only feel, still editable) */}
            <div className="md:col-span-3 space-y-4">
              <div className="os-panel p-6 space-y-4 h-full flex flex-col">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold flex items-center gap-2" style={{ color: 'var(--ink)' }}>
                    <FileText size={14} style={{ color: 'var(--error)' }} />
                    YouTube Description
                  </h3>
                  <button
                    onClick={() => setStep(3)}
                    className="os-btn os-btn-ghost text-xs"
                  >
                    <ArrowLeft size={10} /> Edit
                  </button>
                </div>

                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  className="os-input os-textarea text-sm resize-none flex-1 font-mono os-scroll"
                  style={{ minHeight: '500px' }}
                  maxLength={5000}
                />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}