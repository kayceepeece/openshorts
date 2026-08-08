import React, { useState, useEffect } from 'react';
import { Globe, Sparkles, Download, Copy, Check, ChevronRight, ChevronLeft, Loader2, AlertCircle, Volume2, User, Film, Terminal, ChevronDown, RefreshCw, Zap, Target, TrendingUp, MessageSquare, Eye, Share2, Calendar, Upload } from 'lucide-react';
import { getApiUrl } from '../config';

const STYLE_OPTIONS = [
  { id: 'ugc', label: 'UGC Natural', desc: 'Authentic, talking to camera' },
  { id: 'educational', label: 'Educational', desc: 'Clear explanations' },
  { id: 'shock', label: 'Shock/Discovery', desc: 'Surprising opener' },
  { id: 'story', label: 'Storytelling', desc: 'Mini narrative arc' },
  { id: 'comparison', label: 'Before/After', desc: 'Comparison style' },
];

const CACHE_KEY = 'saasshorts_cache';
const CACHE_MAX_AGE = 24 * 60 * 60 * 1000; // 24 hours

function loadCache() {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const cache = JSON.parse(raw);
    if (Date.now() - cache.timestamp > CACHE_MAX_AGE) {
      localStorage.removeItem(CACHE_KEY);
      return null;
    }
    return cache;
  } catch { return null; }
}

function saveCache(url, analysis, webResearch, scripts) {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify({
      url, analysis, webResearch, scripts, timestamp: Date.now(),
    }));
  } catch { /* localStorage full */ }
}

const activeBorder = { borderColor: 'oklch(0.55 0.095 170 / 0.5)', background: 'oklch(0.55 0.095 170 / 0.08)', boxShadow: '0 0 0 1px oklch(0.55 0.095 170 / 0.25)' };

export default function SaaShortsTab({ geminiApiKey, elevenLabsKey, falKey, uploadPostKey, uploadUserId }) {
  // Wizard state
  const [step, setStep] = useState(() => {
    const cache = loadCache();
    return cache ? 1 : 0;
  });

  // Step 0: URL input
  const [url, setUrl] = useState(() => loadCache()?.url || '');
  const [videoMode, setVideoMode] = useState('lowcost'); // "lowcost" or "premium"
  const [description, setDescription] = useState('');
  const [style, setStyle] = useState('ugc');
  const [language, setLanguage] = useState('en');
  const [actorGender, setActorGender] = useState('female');
  const [numScripts, setNumScripts] = useState(3);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState('');
  const [fromCache, setFromCache] = useState(() => !!loadCache());

  // Step 1: Analysis results
  const [analysis, setAnalysis] = useState(() => loadCache()?.analysis || null);
  const [webResearch, setWebResearch] = useState(() => loadCache()?.webResearch || null);
  const [scripts, setScripts] = useState(() => loadCache()?.scripts || []);
  const [selectedScript, setSelectedScript] = useState(0);

  // Step 2: Configure
  const [voices, setVoices] = useState([]);
  const [selectedVoice, setSelectedVoice] = useState('21m00Tcm4TlvDq8ikWAM');
  const [actorDescription, setActorDescription] = useState('');
  const [editedNarration, setEditedNarration] = useState('');
  const [actorOptions, setActorOptions] = useState([]);
  const [selectedActor, setSelectedActor] = useState(null);
  const [generatingActors, setGeneratingActors] = useState(false);
  const [actorGallery, setActorGallery] = useState([]);
  const [loadingGallery, setLoadingGallery] = useState(false);
  const [uploadedActorPreview, setUploadedActorPreview] = useState(null); // {localPreview, serverUrl}

  // Step 3: Generate
  const [generating, setGenerating] = useState(false);
  const [jobId, setJobId] = useState(null);
  const [genLogs, setGenLogs] = useState([]);
  const [genStatus, setGenStatus] = useState('idle');
  const [genResult, setGenResult] = useState(null);
  const [genError, setGenError] = useState('');

  // Publish
  const [publishing, setPublishing] = useState(false);
  const [publishResult, setPublishResult] = useState(null);
  const [publishPlatforms, setPublishPlatforms] = useState({ tiktok: true, instagram: true, youtube: true });
  const [isScheduling, setIsScheduling] = useState(false);
  const [scheduleDate, setScheduleDate] = useState('');

  // UI
  const [copied, setCopied] = useState('');
  const [logsExpanded, setLogsExpanded] = useState(true);

  // Pre-fill from cache on mount
  useEffect(() => {
    if (fromCache && scripts.length > 0 && !actorDescription) {
      setActorDescription(scripts[0].actor_description || '');
      setEditedNarration(scripts[0].full_narration || '');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Fetch actor gallery on mount
  useEffect(() => {
    setLoadingGallery(true);
    fetch(getApiUrl('/api/saasshorts/actor-gallery'))
      .then(res => res.ok ? res.json() : { images: [] })
      .then(data => setActorGallery(data.images || []))
      .catch(() => {})
      .finally(() => setLoadingGallery(false));
  }, []);

  // Fetch voices on mount
  useEffect(() => {
    if (elevenLabsKey) {
      fetchVoices();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [elevenLabsKey]);

  // Reset selected voice when actor gender changes
  useEffect(() => {
    const genderDefaults = {
      'en-female': '21m00Tcm4TlvDq8ikWAM',  // Rachel
      'en-male': '29vD33N1CtxCmqQRPOHJ',    // Drew
      'es-female': 'EXAVITQu4vr4xnSDxMaL',  // Bella
      'es-male': 'ErXwobaYiN019PkySvjV',     // Antoni
    };
    // If we have fetched voices, pick the first matching one; otherwise use hardcoded default
    const matchingVoice = voices.find(v => (v.labels?.gender || '').toLowerCase() === actorGender);
    if (matchingVoice) {
      setSelectedVoice(matchingVoice.voice_id);
    } else {
      setSelectedVoice(genderDefaults[`${language}-${actorGender}`] || genderDefaults['en-female']);
    }
  }, [actorGender, language, voices]);

  // Poll generation status
  useEffect(() => {
    let interval;
    if (jobId && genStatus === 'processing') {
      interval = setInterval(async () => {
        try {
          const res = await fetch(getApiUrl(`/api/saasshorts/status/${jobId}`));
          if (res.status === 404) {
            // Job lost (server restart) — treat as failed so Retry appears
            setGenStatus('failed');
            setGenerating(false);
            setGenLogs((prev) => [...prev, 'Job lost after server restart. Click Retry to resume from cached assets.']);
            clearInterval(interval);
            return;
          }
          if (!res.ok) return;
          const data = await res.json();
          if (data.logs) setGenLogs(data.logs);
          if (data.status === 'completed') {
            setGenStatus('completed');
            setGenResult(data.result);
            setGenerating(false);
            setStep(4);
            clearInterval(interval);
          } else if (data.status === 'failed') {
            setGenStatus('failed');
            setGenerating(false);
            clearInterval(interval);
          }
        } catch (e) {
          console.error('Poll error:', e);
        }
      }, 2000);
    }
    return () => clearInterval(interval);
  }, [jobId, genStatus]);

  const fetchVoices = async () => {
    try {
      const res = await fetch(getApiUrl('/api/saasshorts/voices'), {
        headers: { 'X-ElevenLabs-Key': elevenLabsKey },
      });
      if (res.ok) {
        const data = await res.json();
        setVoices(data.voices || []);
      }
    } catch (e) {
      console.error('Voices fetch error:', e);
    }
  };

  const handleAnalyze = async () => {
    if (!url.trim() && !description.trim()) return;
    if (!geminiApiKey) {
      setAnalyzeError('Gemini API key required. Set it in Settings.');
      return;
    }

    setAnalyzing(true);
    setAnalyzeError('');

    try {
      const res = await fetch(getApiUrl('/api/saasshorts/analyze'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Gemini-Key': geminiApiKey,
        },
        body: JSON.stringify({
          url: url.trim() || undefined,
          description: description.trim() || undefined,
          num_scripts: numScripts,
          style,
          language,
          actor_gender: actorGender,
        }),
      });

      if (!res.ok) {
        let msg = 'Analysis failed';
        try { const err = await res.json(); msg = err.detail || msg; } catch { msg = await res.text() || msg; }
        throw new Error(msg);
      }

      const data = await res.json();
      setAnalysis(data.analysis);
      setWebResearch(data.web_research || null);
      setScripts(data.scripts);
      setSelectedScript(0);
      setFromCache(false);

      // Cache results
      saveCache(url.trim(), data.analysis, data.web_research, data.scripts);

      // Pre-fill actor description and narration from first script
      if (data.scripts.length > 0) {
        setActorDescription(data.scripts[0].actor_description || '');
        setEditedNarration(data.scripts[0].full_narration || '');
      }

      setStep(1);
    } catch (e) {
      setAnalyzeError(e.message);
    } finally {
      setAnalyzing(false);
    }
  };

  const handleSelectScript = (idx) => {
    setSelectedScript(idx);
    if (scripts[idx]) {
      setActorDescription(scripts[idx].actor_description || '');
      setEditedNarration(scripts[idx].full_narration || '');
    }
  };

  const handleGenerate = async () => {
    if (!falKey) {
      setGenError('fal.ai API key required. Set it in Settings.');
      setGenStatus('failed');
      return;
    }
    if (!elevenLabsKey) {
      setGenError('ElevenLabs API key required. Set it in Settings.');
      setGenStatus('failed');
      return;
    }

    setGenerating(true);
    setGenError('');
    setGenLogs(['Starting video generation...']);
    setGenStatus('processing');
    setGenResult(null);
    setStep(3);

    try {
      // Update script with edited narration
      const scriptToSend = { ...scripts[selectedScript] };
      scriptToSend._product_name = analysis?.product_name || analysis?.name || '';
      scriptToSend._product_url = url;
      if (editedNarration !== scriptToSend.full_narration) {
        scriptToSend.full_narration = editedNarration;
      }

      const res = await fetch(getApiUrl('/api/saasshorts/generate'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Fal-Key': falKey,
          'X-ElevenLabs-Key': elevenLabsKey,
        },
        body: JSON.stringify({
          script: scriptToSend,
          voice_id: selectedVoice,
          actor_description: actorDescription || undefined,
          selected_actor_url: selectedActor || undefined,
          video_mode: videoMode,
        }),
      });

      if (!res.ok) {
        let msg = 'Generation failed';
        try { const err = await res.json(); msg = err.detail || msg; } catch { msg = await res.text() || msg; }
        throw new Error(msg);
      }

      const data = await res.json();
      setJobId(data.job_id);
    } catch (e) {
      setGenStatus('failed');
      setGenError(e.message);
      setGenLogs((prev) => [...prev, `Error: ${e.message}`]);
      setGenerating(false);
    }
  };

  const handleRetry = async () => {
    if (!jobId) return;
    setGenerating(true);
    setGenError('');
    setGenLogs(['Retrying from cached assets...']);
    setGenStatus('processing');
    setGenResult(null);

    try {
      const scriptToSend = { ...scripts[selectedScript] };
      scriptToSend._product_name = analysis?.product_name || analysis?.name || '';
      scriptToSend._product_url = url;
      if (editedNarration !== scriptToSend.full_narration) {
        scriptToSend.full_narration = editedNarration;
      }

      const res = await fetch(getApiUrl('/api/saasshorts/generate'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Fal-Key': falKey,
          'X-ElevenLabs-Key': elevenLabsKey,
        },
        body: JSON.stringify({
          script: scriptToSend,
          voice_id: selectedVoice,
          actor_description: actorDescription || undefined,
          retry_job_id: jobId,
          video_mode: videoMode,
        }),
      });

      if (!res.ok) {
        let msg = 'Retry failed';
        try { const err = await res.json(); msg = err.detail || msg; } catch { msg = await res.text() || msg; }
        throw new Error(msg);
      }

      const data = await res.json();
      setJobId(data.job_id);
    } catch (e) {
      setGenStatus('failed');
      setGenError(e.message);
      setGenLogs((prev) => [...prev, `Retry error: ${e.message}`]);
      setGenerating(false);
    }
  };

  const handleCopy = (text, label) => {
    navigator.clipboard.writeText(text);
    setCopied(label);
    setTimeout(() => setCopied(''), 2000);
  };

  const handleReset = () => {
    setStep(0);
    setUrl('');
    setAnalyzeError('');
    setGenError('');
    setAnalysis(null);
    setWebResearch(null);
    setScripts([]);
    setFromCache(false);
    localStorage.removeItem(CACHE_KEY);
    setSelectedScript(0);
    setJobId(null);
    setGenLogs([]);
    setGenStatus('idle');
    setGenResult(null);
    setGenerating(false);
    setActorDescription('');
    setEditedNarration('');
  };

  const segColors = {
    hook: { bg: 'oklch(0.62 0.18 25 / 0.16)', color: 'var(--error)', bar: 'var(--error)' },
    problem: { bg: 'oklch(0.75 0.14 65 / 0.16)', color: 'var(--warning)', bar: 'var(--warning)' },
    solution: { bg: 'oklch(0.65 0.14 155 / 0.16)', color: 'var(--success)', bar: 'var(--success)' },
    default: { bg: 'oklch(0.55 0.095 170 / 0.16)', color: 'var(--primary)', bar: 'var(--primary)' },
  };
  const segStyle = (type) => segColors[type] || segColors.default;

  // ─── Render Steps ─────────────────────────────────────────────────

  return (
    <div className="h-full overflow-y-auto os-scroll">
      <div className="max-w-5xl mx-auto p-6 lg:p-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-3" style={{ color: 'var(--ink)' }}>
              <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: 'linear-gradient(135deg, oklch(0.55 0.095 170), oklch(0.40 0.080 170))' }}>
                <Zap size={20} style={{ color: 'var(--primary-fg)' }} />
              </div>
              AI Shorts
            </h1>
            <p className="text-sm mt-1" style={{ color: 'var(--muted)' }}>
              Generate viral UGC videos for any product or business
            </p>
          </div>
          {step > 0 && (
            <button onClick={handleReset} className="os-btn os-btn-ghost os-btn-sm">
              <RefreshCw size={14} /> Start over
            </button>
          )}
        </div>

        {/* Progress Steps */}
        <div className="flex items-center gap-2 mb-8">
          {['Setup', 'Analysis', 'Configure', 'Generate', 'Result'].map((label, i) => (
            <React.Fragment key={i}>
              {i > 0 && <div className="flex-1 h-px" style={{ background: i <= step ? 'var(--primary)' : 'var(--border)' }} />}
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium transition-all"
                style={{
                  border: i === step ? '1px solid oklch(0.55 0.095 170 / 0.3)' : 'none',
                  background: i === step ? 'oklch(0.55 0.095 170 / 0.12)' :
                              i < step ? 'oklch(0.55 0.095 170 / 0.06)' :
                              'var(--surface-2)',
                  color: i < step ? 'var(--primary)' : i === step ? 'var(--primary)' : 'var(--subtle)',
                }}
              >
                <span className="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold"
                  style={{
                    background: i < step ? 'var(--primary)' : i === step ? 'oklch(0.55 0.095 170 / 0.25)' : 'var(--surface-2)',
                    color: i < step ? 'var(--primary-fg)' : i === step ? 'var(--primary)' : 'var(--subtle)',
                  }}
                >
                  {i < step ? <Check size={10} /> : i + 1}
                </span>
                <span className="hidden sm:inline">{label}</span>
              </div>
            </React.Fragment>
          ))}
        </div>

        {/* ── Step 0: URL Input ────────────────────────────────── */}
        {step === 0 && (
          <div className="os-fade-in space-y-6">
            <div className="os-panel p-8 space-y-6">
              {/* Video Mode Selector */}
              <div>
                <label className="block text-sm font-medium mb-3" style={{ color: 'var(--ink)' }}>Video Mode</label>
                <div className="grid grid-cols-2 gap-3">
                  <button
                    onClick={() => setVideoMode('lowcost')}
                    className="text-left transition-all"
                    style={{
                      padding: 16, borderRadius: 12, border: '1px solid',
                      ...(videoMode === 'lowcost' ? { ...activeBorder } : { borderColor: 'var(--border)', background: 'var(--surface-2)' }),
                    }}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className={`text-sm font-semibold ${videoMode === 'lowcost' ? '' : ''}`} style={{ color: videoMode === 'lowcost' ? 'var(--success)' : 'var(--ink)' }}>Low Cost</span>
                      <span className="text-xs font-mono px-2 py-0.5 rounded-full os-chip-success">~$0.80</span>
                    </div>
                    <p className="text-[11px] leading-relaxed" style={{ color: 'var(--muted)' }}>Hailuo 2.3 img2video + VEED Lipsync. Good movement + lip-sync. Recommended.</p>
                  </button>
                  <button
                    onClick={() => setVideoMode('premium')}
                    className="text-left transition-all"
                    style={{
                      padding: 16, borderRadius: 12, border: '1px solid',
                      ...(videoMode === 'premium' ? activeBorder : { borderColor: 'var(--border)', background: 'var(--surface-2)' }),
                    }}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-sm font-semibold" style={{ color: videoMode === 'premium' ? 'var(--primary)' : 'var(--ink)' }}>Premium</span>
                      <span className="text-xs font-mono px-2 py-0.5 rounded-full os-chip">~$2.00</span>
                    </div>
                    <p className="text-[11px] leading-relaxed" style={{ color: 'var(--muted)' }}>Kling Avatar v2 Standard. Full integrated movement. Best quality.</p>
                  </button>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium mb-2" style={{ color: 'var(--ink)' }}>Website URL <span style={{ color: 'var(--subtle)' }}>(optional)</span></label>
                <div className="flex gap-3">
                  <div className="relative flex-1">
                    <Globe size={16} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: 'var(--muted)' }} />
                    <input
                      type="url"
                      value={url}
                      onChange={(e) => setUrl(e.target.value)}
                      placeholder="https://your-website.com"
                      className="os-input"
                      style={{ paddingLeft: '2.5rem' }}
                      onKeyDown={(e) => e.key === 'Enter' && handleAnalyze()}
                    />
                  </div>
                </div>
                <p className="text-[10px] mt-1" style={{ color: 'var(--subtle)' }}>If provided, we&apos;ll scrape and research your site automatically</p>
              </div>

              <div>
                <label className="block text-sm font-medium mb-2" style={{ color: 'var(--ink)' }}>
                  {url.trim() ? 'Extra context' : 'Describe your product/business'} <span style={{ color: 'var(--subtle)' }}>{url.trim() ? '(optional)' : '(required if no URL)'}</span>
                </label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={2}
                  className="os-input os-textarea resize-none text-sm"
                  placeholder="e.g. Pizzería artesanal en Madrid, Coach de productividad, Tienda de ropa deportiva, App de meditación..."
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-3" style={{ color: 'var(--ink)' }}>Language</label>
                <div className="flex gap-2 mb-6">
                  {[
                    { id: 'en', label: 'English', flag: '🇺🇸' },
                    { id: 'es', label: 'Español', flag: '🇪🇸' },
                  ].map((l) => (
                    <button
                      key={l.id}
                      onClick={() => setLanguage(l.id)}
                      className="flex-1 p-3 text-center transition-all"
                      style={{
                        borderRadius: 12, border: '1px solid',
                        ...(language === l.id ? activeBorder : { borderColor: 'var(--border)', background: 'var(--surface-2)', color: 'var(--muted)' }),
                      }}
                    >
                      <span className="text-lg">{l.flag}</span>
                      <div className={`text-xs font-medium mt-1 ${language === l.id ? '' : ''}`} style={{ color: language === l.id ? 'var(--primary)' : 'var(--muted)' }}>{l.label}</div>
                    </button>
                  ))}
                </div>

                <label className="block text-sm font-medium mb-3" style={{ color: 'var(--ink)' }}>Actor</label>
                <div className="flex gap-2 mb-6">
                  {[
                    { id: 'female', label: 'Woman', icon: '👩' },
                    { id: 'male', label: 'Man', icon: '👨' },
                  ].map((g) => (
                    <button
                      key={g.id}
                      onClick={() => setActorGender(g.id)}
                      className="flex-1 p-3 text-center transition-all"
                      style={{
                        borderRadius: 12, border: '1px solid',
                        ...(actorGender === g.id ? activeBorder : { borderColor: 'var(--border)', background: 'var(--surface-2)', color: 'var(--muted)' }),
                      }}
                    >
                      <span className="text-lg">{g.icon}</span>
                      <div className="text-xs font-medium mt-1" style={{ color: actorGender === g.id ? 'var(--primary)' : 'var(--muted)' }}>{g.label}</div>
                    </button>
                  ))}
                </div>

                <label className="block text-sm font-medium mb-3" style={{ color: 'var(--ink)' }}>Video Style</label>
                <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
                  {STYLE_OPTIONS.map((s) => (
                    <button
                      key={s.id}
                      onClick={() => setStyle(s.id)}
                      className="p-3 rounded-xl border text-left transition-all"
                      style={{
                        ...(style === s.id ? activeBorder : { borderColor: 'var(--border)', background: 'var(--surface-2)' }),
                      }}
                    >
                      <div className="text-xs font-medium" style={{ color: style === s.id ? 'var(--primary)' : 'var(--ink)' }}>{s.label}</div>
                      <div className="text-[10px] mt-0.5" style={{ color: 'var(--muted)' }}>{s.desc}</div>
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium mb-2" style={{ color: 'var(--ink)' }}>Number of Scripts</label>
                <div className="flex gap-2">
                  {[1, 2, 3, 5].map((n) => (
                    <button
                      key={n}
                      onClick={() => setNumScripts(n)}
                      className="px-4 py-2 rounded-lg text-sm font-medium transition-all"
                      style={{
                        border: '1px solid',
                        ...(numScripts === n ? activeBorder : { borderColor: 'var(--border)', background: 'var(--surface-2)', color: 'var(--muted)' }),
                      }}
                    >
                      {n}
                    </button>
                  ))}
                </div>
              </div>

              {analyzeError && (
                <div className="flex items-center gap-2 text-sm os-chip os-chip-error" style={{ display: 'flex', padding: '0.625rem 0.75rem', whiteSpace: 'normal', lineHeight: 1.5 }}>
                  <AlertCircle size={14} className="shrink-0" />
                  {analyzeError}
                </div>
              )}

              <button
                onClick={handleAnalyze}
                disabled={analyzing || (!url.trim() && !description.trim())}
                className="os-btn os-btn-primary w-full"
                style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, padding: '0.625rem', fontSize: '0.875rem', fontWeight: 600 }}
              >
                {analyzing ? (
                  <>
                    <Loader2 size={16} className="animate-spin" />
                    {url.trim() ? 'Scraping + Researching web + Generating scripts... (45-90s)' : 'Generating scripts... (20-40s)'}
                  </>
                ) : (
                  <>
                    <Sparkles size={16} />
                    {url.trim() ? 'Research & Generate Scripts' : 'Generate Scripts'}
                  </>
                )}
              </button>
            </div>

            {/* Info cards */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="os-panel os-panel-2 p-4">
                <Target size={16} style={{ color: 'var(--primary)', marginBottom: 8 }} />
                <h3 className="text-sm font-medium" style={{ color: 'var(--ink)' }}>Deep Research</h3>
                <p className="text-xs mt-1" style={{ color: 'var(--muted)' }}>AI analyzes your product via URL scraping + web research, or generates directly from your description.</p>
              </div>
              <div className="os-panel os-panel-2 p-4">
                <MessageSquare size={16} style={{ color: 'var(--primary)', marginBottom: 8 }} />
                <h3 className="text-sm font-medium" style={{ color: 'var(--ink)' }}>Pain Point Scripts</h3>
                <p className="text-xs mt-1" style={{ color: 'var(--muted)' }}>Generates hook-problem-solution scripts targeting your audience&apos;s real pain points.</p>
              </div>
              <div className="os-panel os-panel-2 p-4">
                <Film size={16} style={{ color: 'var(--primary)', marginBottom: 8 }} />
                <h3 className="text-sm font-medium" style={{ color: 'var(--ink)' }}>AI Actor Videos</h3>
                <p className="text-xs mt-1" style={{ color: 'var(--muted)' }}>Realistic AI-generated actors with lip-sync, b-roll, and viral subtitles. From ~$0.50/video.</p>
              </div>
            </div>
          </div>
        )}

        {/* ── Step 1: Analysis Results ─────────────────────────── */}
        {step === 1 && analysis && (
          <div className="os-fade-in space-y-6">
            {/* Analysis Summary */}
            <div className="os-panel p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold flex items-center gap-2" style={{ color: 'var(--ink)' }}>
                  <Eye size={18} style={{ color: 'var(--primary)' }} />
                  {analysis.product_name || 'Analysis'}
                </h2>
                <div className="flex items-center gap-2">
                  {fromCache && (
                    <span className="os-chip os-chip-warning flex items-center gap-1">
                      Cached
                      <button onClick={() => { setStep(0); setFromCache(false); }} className="hover:opacity-80 ml-0.5" title="Re-analyze">
                        <RefreshCw size={9} />
                      </button>
                    </span>
                  )}
                  <span className="os-chip os-chip-primary">{analysis.industry}</span>
                </div>
              </div>
              <p className="text-sm mb-4" style={{ color: 'var(--muted)' }}>{analysis.one_liner}</p>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <h3 className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--subtle)' }}>Pain Points</h3>
                  <div className="space-y-1.5">
                    {(analysis.pain_points || []).map((pp, i) => (
                      <div key={i} className="flex items-start gap-2 text-sm">
                        <span className="mt-0.5 w-2 h-2 rounded-full shrink-0" style={{
                          background: pp.intensity === 'high' ? 'var(--error)' : pp.intensity === 'medium' ? 'var(--warning)' : 'var(--success)',
                        }} />
                        <div>
                          <span style={{ color: 'var(--muted)' }}>{pp.pain}</span>
                          {pp.source && pp.source !== 'website' && (
                            <span className="ml-1.5 text-[9px] os-chip os-chip-primary" style={{ padding: '1px 4px', borderRadius: 3 }}>{pp.source}</span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
                <div>
                  <h3 className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--subtle)' }}>Emotional Hooks</h3>
                  <div className="space-y-1.5">
                    {(analysis.emotional_hooks || []).map((h, i) => (
                      <div key={i} className="text-sm flex items-start gap-2" style={{ color: 'var(--muted)' }}>
                        <TrendingUp size={12} className="mt-1 shrink-0" style={{ color: 'var(--primary)' }} />
                        {h}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            {/* Web Research Results */}
            {webResearch && (
              <div className="os-panel p-6">
                <h3 className="text-sm font-semibold mb-3 flex items-center gap-2" style={{ color: 'var(--ink)' }}>
                  <Globe size={14} style={{ color: 'var(--primary)' }} />
                  Web Research (Google Search)
                  {webResearch.grounding_sources && (
                    <span className="os-chip os-chip-primary" style={{ marginLeft: 'auto' }}>
                      {webResearch.grounding_sources.length} sources
                    </span>
                  )}
                </h3>

                {webResearch.real_reviews && webResearch.real_reviews.length > 0 && (
                  <div className="mb-4">
                    <h4 className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--subtle)' }}>Real User Reviews</h4>
                    <div className="space-y-2">
                      {webResearch.real_reviews.slice(0, 5).map((review, i) => (
                        <div key={i} className="text-xs os-panel os-panel-2 rounded-lg p-2.5">
                          <p className="italic" style={{ color: 'var(--muted)' }}>&quot;{review.quote}&quot;</p>
                          <div className="flex items-center gap-2 mt-1">
                            <span style={{ color: 'var(--subtle)' }}>{review.source}</span>
                            <span className="px-1.5 py-0.5 rounded text-[9px] os-chip"
                              style={{
                                ...(review.sentiment === 'positive' ? { background: 'oklch(0.65 0.14 155 / 0.1)', color: 'var(--success)' } :
                                  review.sentiment === 'negative' ? { background: 'oklch(0.62 0.18 25 / 0.1)', color: 'var(--error)' } :
                                  { background: 'var(--surface-2)', color: 'var(--muted)' }),
                              }}
                            >{review.sentiment}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {webResearch.competitors && webResearch.competitors.length > 0 && (
                  <div className="mb-4">
                    <h4 className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--subtle)' }}>Competitors</h4>
                    <div className="flex flex-wrap gap-2">
                      {webResearch.competitors.map((c, i) => (
                        <span key={i} className="text-xs px-2 py-1 rounded-lg os-chip" style={{ color: 'var(--muted)' }} title={c.comparison}>
                          {c.name}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {webResearch.grounding_sources && webResearch.grounding_sources.length > 0 && (
                  <div>
                    <h4 className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--subtle)' }}>Sources</h4>
                    <div className="flex flex-wrap gap-1.5">
                      {webResearch.grounding_sources.slice(0, 8).map((src, i) => (
                        <a
                          key={i}
                          href={src.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="os-chip os-chip-primary"
                          style={{ fontSize: 10, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', textDecoration: 'none' }}
                          title={src.title}
                        >
                          {src.title || (() => { try { return new URL(src.url).hostname; } catch { return src.url; } })()}
                        </a>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Scripts */}
            <div>
              <h2 className="text-lg font-semibold mb-4 flex items-center gap-2" style={{ color: 'var(--ink)' }}>
                <Sparkles size={18} style={{ color: 'var(--primary)' }} />
                Generated Scripts
                <span className="os-chip" style={{ marginLeft: 'auto' }}>{scripts.length} scripts</span>
              </h2>

              <div className="grid grid-cols-1 gap-4">
                {scripts.map((script, i) => (
                  <div
                    key={i}
                    onClick={() => handleSelectScript(i)}
                    className="os-panel os-panel-2 p-5 cursor-pointer transition-all os-fade-in"
                    style={{
                      borderColor: selectedScript === i ? 'oklch(0.55 0.095 170 / 0.45)' : undefined,
                      boxShadow: selectedScript === i ? '0 0 0 1px oklch(0.55 0.095 170 / 0.2)' : undefined,
                      background: selectedScript === i ? 'oklch(0.55 0.095 170 / 0.04)' : 'var(--surface)',
                    }}
                  >
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-3">
                        <span className="w-7 h-7 rounded-lg flex items-center justify-center text-xs font-bold" style={{
                          background: selectedScript === i ? 'var(--primary)' : 'var(--surface-2)',
                          color: selectedScript === i ? 'var(--primary-fg)' : 'var(--muted)',
                        }}>
                          {i + 1}
                        </span>
                        <div>
                          <h3 className="text-sm font-semibold" style={{ color: 'var(--ink)' }}>{script.title}</h3>
                          <span className="text-[10px]" style={{ color: 'var(--subtle)' }}>{script.duration_seconds}s &middot; {script.style} &middot; {script.target_platform}</span>
                        </div>
                      </div>
                      {selectedScript === i && (
                        <span className="os-chip os-chip-primary">Selected</span>
                      )}
                    </div>

                    {/* Segments preview */}
                    <div className="flex gap-1 mb-3">
                      {(script.segments || []).map((seg, j) => (
                        <div
                          key={j}
                          className="h-1.5 rounded-full"
                          style={{ background: segStyle(seg.type).bar, flex: (seg.end - seg.start) }}
                          title={`${seg.type}: ${seg.start}s-${seg.end}s`}
                        />
                      ))}
                    </div>

                    <div className="space-y-2">
                      {(script.segments || []).map((seg, j) => (
                        <div key={j} className="flex gap-3 text-xs">
                          <span className="shrink-0 px-1.5 py-0.5 rounded font-mono uppercase tracking-wider" style={{ background: segStyle(seg.type).bg, color: segStyle(seg.type).color }}>
                            {seg.type}
                          </span>
                          <span className="leading-relaxed" style={{ color: 'var(--muted)' }}>{seg.narration}</span>
                        </div>
                      ))}
                    </div>

                    {/* Hook text & hashtags */}
                    <div className="mt-3 pt-3 flex items-center gap-3 flex-wrap" style={{ borderTop: '1px solid var(--border)' }}>
                      <span className="text-[10px] os-chip os-chip-error" style={{ whiteSpace: 'normal', lineHeight: 1.4 }}>
                        Hook: &quot;{script.hook_text}&quot;
                      </span>
                      {(script.hashtags || []).slice(0, 4).map((tag, j) => (
                        <span key={j} className="text-[10px]" style={{ color: 'var(--subtle)' }}>{tag}</span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="flex justify-between">
              <button onClick={() => setStep(0)} className="os-btn os-btn-secondary">
                <ChevronLeft size={14} /> Back
              </button>
              <button onClick={() => setStep(2)} className="os-btn os-btn-primary">
                Configure Video <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}

        {/* ── Step 2: Configure ────────────────────────────────── */}
        {step === 2 && scripts[selectedScript] && (
          <div className="os-fade-in space-y-6">
            <div className="os-panel p-6 space-y-5">
              <h2 className="text-lg font-semibold" style={{ color: 'var(--ink)' }}>Configure Video</h2>
              <p className="text-sm" style={{ color: 'var(--muted)' }}>
                Script: <strong style={{ color: 'var(--ink)' }}>{scripts[selectedScript].title}</strong>
              </p>

              {/* Voice Selection */}
              <div>
                <label className="block text-sm font-medium mb-2 flex items-center gap-2" style={{ color: 'var(--ink)' }}>
                  <Volume2 size={14} /> Voice {language === 'es' ? '(Spanish)' : '(English)'}
                </label>
                {(() => {
                  // Filter voices by gender and sort by accent
                  const filtered = voices.length > 0
                    ? voices.filter((v) => (v.labels?.gender || '').toLowerCase() === actorGender)
                      .sort((a, b) => {
                        const aAccent = (a.labels?.accent || '').toLowerCase();
                        const bAccent = (b.labels?.accent || '').toLowerCase();
                        if (language === 'es') {
                          const aScore = (aAccent.includes('spanish') || aAccent.includes('latin')) ? 0 : 1;
                          const bScore = (bAccent.includes('spanish') || bAccent.includes('latin')) ? 0 : 1;
                          return aScore - bScore;
                        }
                        const aScore = (aAccent.includes('american') || aAccent.includes('british')) ? 0 : 1;
                        const bScore = (bAccent.includes('american') || bAccent.includes('british')) ? 0 : 1;
                        return aScore - bScore;
                      })
                    : [];

                  if (filtered.length > 0) {
                    return (
                      <div className="space-y-1.5 max-h-48 overflow-y-auto os-scroll">
                        {filtered.map((v) => (
                          <button
                            key={v.voice_id}
                            onClick={() => setSelectedVoice(v.voice_id)}
                            className="w-full flex items-center gap-3 p-2.5 rounded-lg border text-left transition-all"
                            style={{
                              borderColor: selectedVoice === v.voice_id ? 'oklch(0.55 0.095 170 / 0.5)' : 'var(--border)',
                              background: selectedVoice === v.voice_id ? 'oklch(0.55 0.095 170 / 0.08)' : 'var(--surface-2)',
                            }}
                          >
                            <div className="flex-1 min-w-0">
                              <div className="text-sm font-medium truncate" style={{ color: 'var(--ink)' }}>{v.name}</div>
                              <div className="text-[10px]" style={{ color: 'var(--subtle)' }}>
                                {v.labels?.accent || ''} {v.labels?.gender || ''} {v.category ? `· ${v.category}` : ''}
                              </div>
                            </div>
                            {v.preview_url && (
                              <button
                                onClick={(e) => { e.stopPropagation(); new Audio(v.preview_url).play(); }}
                                className="shrink-0 w-7 h-7 rounded-full flex items-center justify-center transition-colors"
                                style={{ background: 'var(--surface-2)', color: 'var(--muted)' }}
                                title="Preview voice"
                              >
                                <Volume2 size={12} />
                              </button>
                            )}
                            {selectedVoice === v.voice_id && <Check size={14} className="shrink-0" style={{ color: 'var(--primary)' }} />}
                          </button>
                        ))}
                      </div>
                    );
                  }

                  const defaults = {
                    'en-female': [
                      { id: '21m00Tcm4TlvDq8ikWAM', name: 'Rachel (calm)' },
                      { id: 'EXAVITQu4vr4xnSDxMaL', name: 'Bella (soft)' },
                    ],
                    'en-male': [
                      { id: '29vD33N1CtxCmqQRPOHJ', name: 'Drew (confident)' },
                      { id: 'TxGEqnHWrfWFTfGW9XjX', name: 'Josh (deep)' },
                      { id: 'yoZ06aMxZJJ28mfd3POQ', name: 'Sam (raspy)' },
                    ],
                    'es-female': [
                      { id: 'EXAVITQu4vr4xnSDxMaL', name: 'Bella (suave)' },
                      { id: '21m00Tcm4TlvDq8ikWAM', name: 'Rachel (calmada)' },
                    ],
                    'es-male': [
                      { id: 'ErXwobaYiN019PkySvjV', name: 'Antoni (cálido)' },
                      { id: '29vD33N1CtxCmqQRPOHJ', name: 'Drew (confiado)' },
                    ],
                  };
                  const key = `${language}-${actorGender}`;
                  const opts = defaults[key] || defaults['en-female'];
                  return (
                    <select value={selectedVoice} onChange={(e) => setSelectedVoice(e.target.value)} className="os-input os-select">
                      {opts.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
                    </select>
                  );
                })()}
                <p className="text-[10px] mt-1" style={{ color: 'var(--subtle)' }}>
                  {language === 'es'
                    ? `Voces ${actorGender === 'female' ? 'femeninas' : 'masculinas'} · Todas hablan español con modelo multilingual · Click altavoz para preview`
                    : `${actorGender === 'female' ? 'Female' : 'Male'} voices · Click speaker to preview`}
                </p>
              </div>

              {/* Actor Selection: Gallery + Generate New */}
              <div>
                <label className="block text-sm font-medium mb-2 flex items-center gap-2" style={{ color: 'var(--ink)' }}>
                  <User size={14} /> AI Actor — Choose Your Actor
                </label>

                {actorGallery.length > 0 && (
                  <div className="mb-4">
                    <p className="text-xs mb-2" style={{ color: 'var(--muted)' }}>Previously generated actors (click to select):</p>
                    <div className="grid grid-cols-4 sm:grid-cols-6 gap-2 max-h-48 overflow-y-auto os-scroll pr-1">
                      {actorGallery.map((img, i) => (
                        <button
                          key={img.url}
                          onClick={() => setSelectedActor(img.url)}
                          className="relative rounded-lg overflow-hidden transition-all aspect-[3/4]"
                          style={{
                            border: `2px solid ${selectedActor === img.url ? 'var(--primary)' : 'var(--border)'}`,
                            boxShadow: selectedActor === img.url ? '0 0 0 2px oklch(0.55 0.095 170 / 0.25)' : 'none',
                            transform: selectedActor === img.url ? 'scale(1.02)' : 'none',
                          }}
                        >
                          <img src={img.url} alt={`Actor ${i+1}`} className="w-full h-full object-cover" />
                          {selectedActor === img.url && (
                            <div className="absolute top-1 right-1 w-5 h-5 rounded-full flex items-center justify-center" style={{ background: 'var(--primary)', boxShadow: '0 4px 12px oklch(0 0 0 / 0.4)' }}>
                              <Check size={10} style={{ color: 'var(--primary-fg)' }} />
                            </div>
                          )}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {loadingGallery && (
                  <p className="text-xs mb-3 flex items-center gap-1" style={{ color: 'var(--muted)' }}><Loader2 size={12} className="animate-spin" /> Loading actor gallery...</p>
                )}

                {/* Upload Custom Actor */}
                <div className="mb-4">
                  <div className="flex items-center gap-3">
                    <label className="flex-1 flex items-center justify-center gap-2 text-sm cursor-pointer transition-colors os-input"
                      style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, padding: '0.75rem 1rem', borderStyle: 'dashed', color: 'var(--muted)' }}
                    >
                      <Upload size={14} />
                      <span>Upload your own photo</span>
                      <input
                        type="file"
                        accept="image/*"
                        className="hidden"
                        onChange={async (e) => {
                          const file = e.target.files?.[0];
                          if (!file) return;
                          const localPreview = URL.createObjectURL(file);
                          setUploadedActorPreview({ localPreview, serverUrl: null });
                          setSelectedActor(null);
                          const formData = new FormData();
                          formData.append('file', file);
                          try {
                            const res = await fetch(getApiUrl('/api/saasshorts/actor-upload'), {
                              method: 'POST',
                              body: formData,
                            });
                            if (res.ok) {
                              const data = await res.json();
                              if (data.url) {
                                setUploadedActorPreview({ localPreview, serverUrl: data.url });
                                setSelectedActor(data.url);
                              }
                            }
                          } catch (err) { console.error('Upload failed:', err); }
                          e.target.value = '';
                        }}
                      />
                    </label>
                    {uploadedActorPreview && (
                      <button
                        onClick={() => {
                          if (uploadedActorPreview.serverUrl) {
                            setSelectedActor(uploadedActorPreview.serverUrl);
                          }
                        }}
                        className="relative w-16 h-20 rounded-lg overflow-hidden transition-all flex-shrink-0"
                        style={{
                          border: `2px solid ${selectedActor === uploadedActorPreview.serverUrl ? 'var(--primary)' : 'var(--border)'}`,
                          boxShadow: selectedActor === uploadedActorPreview.serverUrl ? '0 0 0 2px oklch(0.55 0.095 170 / 0.25)' : 'none',
                        }}
                      >
                        <img src={uploadedActorPreview.localPreview} alt="Uploaded" className="w-full h-full object-cover" />
                        {selectedActor === uploadedActorPreview.serverUrl && (
                          <div className="absolute top-1 right-1 w-4 h-4 rounded-full flex items-center justify-center" style={{ background: 'var(--primary)' }}>
                            <Check size={8} style={{ color: 'var(--primary-fg)' }} />
                          </div>
                        )}
                        {!uploadedActorPreview.serverUrl && (
                          <div className="absolute inset-0 flex items-center justify-center" style={{ background: 'oklch(0 0 0 / 0.5)' }}>
                            <Loader2 size={12} className="animate-spin" style={{ color: '#fff' }} />
                          </div>
                        )}
                      </button>
                    )}
                  </div>
                </div>

                {/* Generate New Actors */}
                <p className="text-xs mb-2" style={{ color: 'var(--muted)' }}>{actorGallery.length > 0 ? 'Or generate new actors:' : 'Or describe your actor:'}</p>
                <textarea
                  value={actorDescription}
                  onChange={(e) => { setActorDescription(e.target.value); setActorOptions([]); }}
                  rows={2}
                  className="os-input os-textarea resize-none text-sm"
                  placeholder="e.g. A young woman in her late 20s, dark hair, casual outfit..."
                />

                <button
                  onClick={async () => {
                    if (!falKey || !actorDescription) return;
                    setGeneratingActors(true);
                    setActorOptions([]);
                    setSelectedActor(null);
                    try {
                      const res = await fetch(getApiUrl('/api/saasshorts/actor-options'), {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-Fal-Key': falKey },
                        body: JSON.stringify({ actor_description: actorDescription, num_options: 3 }),
                      });
                      if (res.ok) {
                        const data = await res.json();
                        setActorOptions(data.images || []);
                        const galRes = await fetch(getApiUrl('/api/saasshorts/actor-gallery'));
                        if (galRes.ok) {
                          const galData = await galRes.json();
                          setActorGallery(galData.images || []);
                        }
                      }
                    } catch (e) { console.error(e); }
                    finally { setGeneratingActors(false); }
                  }}
                  disabled={generatingActors || !falKey || !actorDescription}
                  className="os-btn os-btn-secondary mt-2 w-full"
                  style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, fontWeight: 500 }}
                >
                  {generatingActors ? <><Loader2 size={14} className="animate-spin" /> Generating 3 actors...</> : <><User size={14} /> {actorOptions.length > 0 ? 'Regenerate Actors' : 'Generate 3 New Actors'} (~$0.06)</>}
                </button>

                {/* Newly Generated Actor Options */}
                {actorOptions.length > 0 && (
                  <div className="mt-3">
                    <p className="text-xs mb-2" style={{ color: 'var(--muted)' }}>New actors (select one):</p>
                    <div className="grid grid-cols-3 gap-3">
                      {actorOptions.map((imgUrl, i) => (
                        <button
                          key={imgUrl}
                          onClick={() => setSelectedActor(imgUrl)}
                          className="relative rounded-xl overflow-hidden transition-all aspect-[9/16]"
                          style={{
                            border: `2px solid ${selectedActor === imgUrl ? 'var(--primary)' : 'var(--border)'}`,
                            boxShadow: selectedActor === imgUrl ? '0 0 0 2px oklch(0.55 0.095 170 / 0.25)' : 'none',
                            transform: selectedActor === imgUrl ? 'scale(1.02)' : 'none',
                          }}
                        >
                          <img src={imgUrl} alt={`New ${i+1}`} className="w-full h-full object-cover" />
                          {selectedActor === imgUrl && (
                            <div className="absolute top-2 right-2 w-6 h-6 rounded-full flex items-center justify-center" style={{ background: 'var(--primary)', boxShadow: '0 4px 12px oklch(0 0 0 / 0.4)' }}>
                              <Check size={12} style={{ color: 'var(--primary-fg)' }} />
                            </div>
                          )}
                          <div className="absolute bottom-0 inset-x-0 p-2" style={{ background: 'linear-gradient(to top, oklch(0 0 0 / 0.6), transparent)' }}>
                            <span className="text-[10px]" style={{ color: 'oklch(0.9 0 0 / 0.8)' }}>New {i+1}</span>
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {!selectedActor && (actorOptions.length > 0 || actorGallery.length > 0) && (
                  <p className="text-xs mt-2 flex items-center gap-1 os-chip os-chip-warning" style={{ whiteSpace: 'normal', lineHeight: 1.4 }}><AlertCircle size={12} className="shrink-0" /> Select an actor to continue</p>
                )}
              </div>

              {/* Narration Edit */}
              <div>
                <label className="block text-sm font-medium mb-2 flex items-center gap-2" style={{ color: 'var(--ink)' }}>
                  <MessageSquare size={14} /> Narration Script
                </label>
                <textarea
                  value={editedNarration}
                  onChange={(e) => setEditedNarration(e.target.value)}
                  rows={5}
                  className="os-input os-textarea resize-none font-mono text-xs"
                />
                <p className="text-[10px] mt-1" style={{ color: 'var(--subtle)' }}>{editedNarration.length} chars &middot; ~{Math.round(editedNarration.split(' ').length / 2.5)}s speech</p>
              </div>

              {/* Cost Estimate */}
              <div className="os-panel os-panel-2 p-3">
                <div className="flex items-center justify-between text-sm">
                  <span style={{ color: 'var(--muted)' }}>Estimated cost</span>
                  <span className="font-semibold" style={{ color: 'var(--success)' }}>~${videoMode === 'lowcost' ? '0.65' : '2.50'}</span>
                </div>
                <div className="text-[10px] mt-1" style={{ color: 'var(--subtle)' }}>
                  {videoMode === 'lowcost'
                    ? 'Flux image ($0.05) + ElevenLabs voice ($0.10) + Hailuo 2.3 img2video ($0.19) + VEED Lipsync ($0.20) + Flux b-roll ($0.10)'
                    : 'Flux image ($0.05) + ElevenLabs voice ($0.10) + Kling avatar ($1.69) + Kling b-roll ($0.10)'
                  }
                </div>
              </div>

              {/* Missing keys warning */}
              {(!falKey || !elevenLabsKey) && (
                <div className="os-chip os-chip-warning flex items-center gap-2 text-sm" style={{ display: 'flex', alignItems: 'center', whiteSpace: 'normal', lineHeight: 1.5, padding: '0.75rem' }}>
                  <AlertCircle size={14} className="shrink-0" />
                  <span>{!falKey && 'fal.ai API key missing. '}{!elevenLabsKey && 'ElevenLabs API key missing. '} Set them in Settings.</span>
                </div>
              )}
            </div>

            <div className="flex justify-between">
              <button onClick={() => setStep(1)} className="os-btn os-btn-secondary">
                <ChevronLeft size={14} /> Back
              </button>
              <button
                onClick={handleGenerate}
                disabled={!falKey || !elevenLabsKey || !selectedActor || generating}
                className="os-btn os-btn-primary"
              >
                {generating ? (
                  <><Loader2 size={14} className="animate-spin" /> Generating...</>
                ) : !selectedActor ? (
                  <><User size={14} /> Select an actor first</>
                ) : (
                  <><Film size={14} /> Generate Video (~${videoMode === 'lowcost' ? '0.65' : '2.00'})</>
                )}
              </button>
            </div>
          </div>
        )}

        {/* ── Step 3: Generation Progress ──────────────────────── */}
        {step === 3 && (
          <div className="os-fade-in space-y-6">
            <div className="os-panel p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold flex items-center gap-2" style={{ color: 'var(--ink)' }}>
                  <Film size={18} style={{
                    color: genStatus === 'processing' ? 'var(--primary)' : genStatus === 'completed' ? 'var(--success)' : 'var(--error)',
                  }} />
                  Video Generation
                </h2>
                <span className="os-chip"
                  style={{
                    background: genStatus === 'processing' ? 'oklch(0.55 0.095 170 / 0.1)' : genStatus === 'completed' ? 'oklch(0.65 0.14 155 / 0.1)' : 'oklch(0.62 0.18 25 / 0.1)',
                    borderColor: genStatus === 'processing' ? 'oklch(0.55 0.095 170 / 0.25)' : genStatus === 'completed' ? 'oklch(0.65 0.14 155 / 0.25)' : 'oklch(0.62 0.18 25 / 0.25)',
                    color: genStatus === 'processing' ? 'var(--primary)' : genStatus === 'completed' ? 'var(--success)' : 'var(--error)',
                  }}
                >
                  {genStatus.toUpperCase()}
                </span>
              </div>

              {/* genError inline (replaces alert) */}
              {genError && (
                <div className="os-chip os-chip-error mb-4" style={{ display: 'flex', alignItems: 'center', gap: 8, whiteSpace: 'normal', lineHeight: 1.5, padding: '0.625rem 0.75rem' }}>
                  <AlertCircle size={14} className="shrink-0" />
                  {genError}
                </div>
              )}

              {/* Progress steps */}
              <div className="space-y-2 mb-4">
                {[
                  'Generating actor image + voiceover',
                  'Creating talking head video (2-5 min)',
                  'Generating b-roll clips',
                  'Compositing final video',
                ].map((label, i) => {
                  const logStr = genLogs.join(' ').toLowerCase();
                  const stepDone =
                    i === 0 ? logStr.includes('[2/6]') || logStr.includes('[3/6]') :
                    i === 1 ? logStr.includes('[3/6]') && (logStr.includes('[4/6]') || logStr.includes('talking head ready')) :
                    i === 2 ? logStr.includes('[5/6]') || logStr.includes('[6/6]') :
                    genStatus === 'completed';
                  const stepActive =
                    i === 0 ? logStr.includes('[1/6]') && !stepDone :
                    i === 1 ? (logStr.includes('[3/6]') && !logStr.includes('[4/6]')) :
                    i === 2 ? (logStr.includes('[4/6]') && !logStr.includes('[5/6]') && !logStr.includes('[6/6]')) :
                    logStr.includes('[6/6]') && genStatus !== 'completed';

                  return (
                    <div key={i} className="flex items-center gap-3 text-sm">
                      {stepDone ? (
                        <Check size={14} style={{ color: 'var(--success)' }} />
                      ) : stepActive ? (
                        <Loader2 size={14} className="animate-spin" style={{ color: 'var(--primary)' }} />
                      ) : (
                        <div className="w-3.5 h-3.5 rounded-full" style={{ border: '1px solid var(--border-2)' }} />
                      )}
                      <span style={{ color: stepDone ? 'var(--muted)' : stepActive ? 'var(--ink)' : 'var(--subtle)' }}>
                        {label}
                      </span>
                    </div>
                  );
                })}
              </div>

              {/* Logs Terminal */}
              <div className="rounded-xl border overflow-hidden" style={{ borderColor: 'var(--border)', background: 'oklch(0.06 0.004 170)' }}>
                <div className="px-4 py-2 flex items-center justify-between" style={{ borderBottom: '1px solid var(--border)', background: 'oklch(0.10 0.004 170)' }}>
                  <span className="text-xs font-mono flex items-center gap-2" style={{ color: 'var(--muted)' }}>
                    <Terminal size={12} /> Generation Logs
                  </span>
                  <button onClick={() => setLogsExpanded(!logsExpanded)} style={{ color: 'var(--subtle)' }}>
                    <ChevronDown size={14} className={logsExpanded ? '' : 'rotate-180'} />
                  </button>
                </div>
                {logsExpanded && (
                  <div className="p-4 max-h-64 overflow-y-auto font-mono text-xs space-y-1 os-scroll">
                    {genLogs.map((log, i) => (
                      <div key={i} style={{ color: log.toLowerCase().includes('error') ? 'var(--error)' : log.includes('✅') ? 'var(--success)' : 'var(--muted)' }}>
                        {log}
                      </div>
                    ))}
                    {genStatus === 'processing' && (
                      <div className="animate-pulse" style={{ color: 'oklch(0.55 0.095 170 / 0.7)' }}>_</div>
                    )}
                  </div>
                )}
              </div>

              {/* Retry button when failed */}
              {genStatus === 'failed' && (
                <div className="mt-4 p-4 rounded-xl space-y-3" style={{ background: 'oklch(0.62 0.18 25 / 0.05)', border: '1px solid oklch(0.62 0.18 25 / 0.2)' }}>
                  <div className="flex items-center gap-2">
                    <AlertCircle size={16} className="shrink-0" style={{ color: 'var(--error)' }} />
                    <span className="text-sm" style={{ color: 'var(--error)' }}>Generation failed. You can retry or go back to change settings.</span>
                  </div>
                  <div className="flex gap-3">
                    <button
                      onClick={() => { setStep(2); setGenStatus('idle'); setGenerating(false); }}
                      className="os-btn os-btn-secondary"
                    >
                      <ChevronLeft size={14} /> Change Voice/Settings
                    </button>
                    <button
                      onClick={handleRetry}
                      disabled={generating}
                      className="os-btn os-btn-primary"
                    >
                      <RefreshCw size={14} /> Retry
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── Step 4: Results ──────────────────────────────────── */}
        {step === 4 && genResult && (
          <div className="os-fade-in space-y-6">
            <div className="os-panel p-6">
              <h2 className="text-lg font-semibold mb-4 flex items-center gap-2" style={{ color: 'var(--ink)' }}>
                <Sparkles size={18} style={{ color: 'var(--primary)' }} />
                Your SaaS Short is Ready!
              </h2>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Video Player */}
                <div className="aspect-[9/16] max-h-[500px] rounded-xl overflow-hidden relative" style={{ background: 'oklch(0 0 0)' }}>
                  <video
                    src={getApiUrl(genResult.video_url)}
                    controls
                    className="w-full h-full object-contain"
                    autoPlay
                  />
                </div>

                {/* Details */}
                <div className="space-y-4">
                  <div>
                    <h3 className="text-sm font-medium mb-1" style={{ color: 'var(--ink)' }}>{genResult.script?.title}</h3>
                    <p className="text-xs" style={{ color: 'var(--muted)' }}>{genResult.duration?.toFixed(1)}s &middot; 9:16 vertical</p>
                  </div>

                  {/* Cost breakdown */}
                  {genResult.cost_estimate && (
                    <div className="os-panel os-panel-2 p-3 space-y-1">
                      <div className="text-xs font-semibold mb-2" style={{ color: 'var(--ink)' }}>Cost Breakdown</div>
                      {Object.entries(genResult.cost_estimate).filter(([k]) => k !== 'total').map(([k, v]) => (
                        <div key={k} className="flex justify-between text-xs">
                          <span style={{ color: 'var(--muted)' }}>{k.replace(/_/g, ' ')}</span>
                          <span style={{ color: 'var(--muted)' }}>${v}</span>
                        </div>
                      ))}
                      <div className="flex justify-between text-sm font-semibold pt-1 mt-1" style={{ borderTop: '1px solid var(--border)' }}>
                        <span style={{ color: 'var(--ink)' }}>Total</span>
                        <span style={{ color: 'var(--success)' }}>${genResult.cost_estimate.total}</span>
                      </div>
                    </div>
                  )}

                  {/* Caption */}
                  {genResult.script?.caption && (
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-medium" style={{ color: 'var(--muted)' }}>Caption</span>
                        <button
                          onClick={() => handleCopy(genResult.script.caption, 'caption')}
                          className="os-btn os-btn-ghost os-btn-xs text-xs flex items-center gap-1"
                        >
                          {copied === 'caption' ? <Check size={10} /> : <Copy size={10} />}
                          {copied === 'caption' ? 'Copied' : 'Copy'}
                        </button>
                      </div>
                      <p className="text-xs os-panel os-panel-2 p-2 rounded-lg" style={{ color: 'var(--muted)' }}>{genResult.script.caption}</p>
                    </div>
                  )}

                  {/* Hashtags */}
                  {genResult.script?.hashtags && (
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-medium" style={{ color: 'var(--muted)' }}>Hashtags</span>
                        <button
                          onClick={() => handleCopy(genResult.script.hashtags.join(' '), 'hashtags')}
                          className="os-btn os-btn-ghost os-btn-xs flex items-center gap-1"
                        >
                          {copied === 'hashtags' ? <Check size={10} /> : <Copy size={10} />}
                          {copied === 'hashtags' ? 'Copied' : 'Copy'}
                        </button>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {genResult.script.hashtags.map((tag, i) => (
                          <span key={i} className="text-[10px] os-chip os-chip-primary">{tag}</span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Actions */}
                  <div className="flex gap-3 pt-2">
                    <a
                      href={getApiUrl(genResult.video_url)}
                      download
                      className="os-btn os-btn-primary"
                    >
                      <Download size={14} /> Download
                    </a>
                    <button
                      onClick={handleReset}
                      className="os-btn os-btn-secondary"
                    >
                      <RefreshCw size={14} /> New Video
                    </button>
                  </div>

                  {/* Publish to Social Media */}
                  <div className="os-panel os-panel-2 rounded-xl space-y-3 mt-2 p-4">
                    <h3 className="text-sm font-semibold flex items-center gap-2" style={{ color: 'var(--ink)' }}>
                      <Share2 size={14} /> Publish to Social Media
                    </h3>

                    {!uploadPostKey ? (
                      <p className="text-xs" style={{ color: 'var(--muted)' }}>Set your Upload-Post API key in Settings to enable publishing.</p>
                    ) : (
                      <>
                        {/* Platform checkboxes */}
                        <div className="flex gap-4">
                          {[
                            { id: 'tiktok', label: 'TikTok', icon: '🎵' },
                            { id: 'instagram', label: 'Instagram', icon: '📸' },
                            { id: 'youtube', label: 'YouTube', icon: '▶️' },
                          ].map((p) => (
                            <label key={p.id} className="flex items-center gap-2 text-xs cursor-pointer" style={{ color: 'var(--muted)' }}>
                              <input
                                type="checkbox"
                                checked={publishPlatforms[p.id]}
                                onChange={(e) => setPublishPlatforms({ ...publishPlatforms, [p.id]: e.target.checked })}
                                className="os-checkbox"
                              />
                              <span>{p.icon}</span> {p.label}
                            </label>
                          ))}
                        </div>

                        {/* Schedule toggle */}
                        <div className="flex items-center gap-3">
                          <label className="flex items-center gap-2 text-xs cursor-pointer" style={{ color: 'var(--muted)' }}>
                            <input
                              type="checkbox"
                              checked={isScheduling}
                              onChange={(e) => setIsScheduling(e.target.checked)}
                              className="os-checkbox"
                            />
                            <Calendar size={12} /> Schedule
                          </label>
                          {isScheduling && (
                            <input
                              type="datetime-local"
                              value={scheduleDate}
                              onChange={(e) => setScheduleDate(e.target.value)}
                              className="os-input text-xs py-1 px-2 w-auto"
                              style={{ colorScheme: 'dark' }}
                            />
                          )}
                        </div>

                        {/* Publish button */}
                        <button
                          onClick={async () => {
                            const selected = Object.keys(publishPlatforms).filter(k => publishPlatforms[k]);
                            if (selected.length === 0) { setPublishResult({ ok: false, msg: 'Select at least one platform' }); return; }
                            if (isScheduling && !scheduleDate) { setPublishResult({ ok: false, msg: 'Select a date' }); return; }

                            setPublishing(true);
                            setPublishResult(null);
                            try {
                              const payload = {
                                job_id: jobId,
                                api_key: uploadPostKey,
                                user_id: uploadUserId,
                                platforms: selected,
                                title: genResult.script?.title,
                                description: genResult.script?.caption || genResult.script?.full_narration,
                              };
                              if (isScheduling && scheduleDate) {
                                payload.scheduled_date = new Date(scheduleDate).toISOString();
                                payload.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
                              }
                              const res = await fetch(getApiUrl('/api/saasshorts/post'), {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(payload),
                              });
                              if (!res.ok) {
                                const err = await res.json().catch(() => ({ detail: 'Failed' }));
                                throw new Error(err.detail || 'Failed');
                              }
                              setPublishResult({ ok: true, msg: isScheduling ? 'Scheduled!' : 'Published!' });
                            } catch (e) {
                              setPublishResult({ ok: false, msg: e.message });
                            } finally {
                              setPublishing(false);
                            }
                          }}
                          disabled={publishing}
                          className="os-btn os-btn-primary w-full"
                          style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}
                        >
                          {publishing ? (
                            <><Loader2 size={14} className="animate-spin" /> {isScheduling ? 'Scheduling...' : 'Publishing...'}</>
                          ) : (
                            <><Share2 size={14} /> {isScheduling ? 'Schedule Post' : 'Publish Now'}</>
                          )}
                        </button>

                        {publishResult && (
                          <p className="text-xs" style={{ color: publishResult.ok ? 'var(--success)' : 'var(--error)' }}>
                            {publishResult.msg}
                          </p>
                        )}
                      </>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}