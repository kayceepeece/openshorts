import React from 'react';
import { Sparkles, Zap, Globe, FileVideo, Subtitles, Languages, Type, Upload, Scissors, Shield, Monitor, Cpu, Github, ArrowRight, Play, Check, ChevronDown, Youtube, Instagram } from 'lucide-react';

const TikTokIcon = ({ size = 16, className = "" }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className}>
    <path d="M19.589 6.686a4.793 4.793 0 0 1-3.77-4.245V2h-3.445v13.672a2.896 2.896 0 0 1-5.201 1.743l-.002-.001.002.001a2.895 2.895 0 0 1 3.183-4.51v-3.5a6.329 6.329 0 0 0-5.394 10.692 6.33 6.33 0 0 0 10.857-4.424V8.687a8.182 8.182 0 0 0 4.773 1.526V6.79a4.831 4.831 0 0 1-1.003-.104z" />
  </svg>
);

const prim = (a) => `oklch(0.55 0.095 170 / ${a})`;

const FeatureCard = ({ icon: Icon, title, description }) => (
  <div className="group rounded-2xl p-6 transition-all duration-300"
    style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12 }}
  >
    <div className="w-12 h-12 rounded-xl flex items-center justify-center mb-4 transition-colors" style={{ background: prim(0.1) }}>
      <Icon size={24} style={{ color: 'var(--primary)' }} />
    </div>
    <h3 className="text-lg font-semibold mb-2" style={{ color: 'var(--ink)' }}>{title}</h3>
    <p className="text-sm leading-relaxed" style={{ color: 'var(--muted)' }}>{description}</p>
  </div>
);

const StepCard = ({ number, title, description }) => (
  <div className="flex gap-4">
    <div className="flex-shrink-0 w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm"
      style={{ background: prim(0.15), border: '1px solid ' + prim(0.35), color: 'var(--primary)' }}
    >
      {number}
    </div>
    <div>
      <h3 className="font-semibold mb-1" style={{ color: 'var(--ink)' }}>{title}</h3>
      <p className="text-sm leading-relaxed" style={{ color: 'var(--muted)' }}>{description}</p>
    </div>
  </div>
);

const ComparisonRow = ({ feature, openshorts, competia, kapwing }) => (
  <tr style={{ borderBottom: '1px solid var(--border)' }}>
    <td className="py-3 px-4 text-sm" style={{ color: 'var(--muted)' }}>{feature}</td>
    <td className="py-3 px-4 text-center">{openshorts}</td>
    <td className="py-3 px-4 text-center">{competia}</td>
    <td className="py-3 px-4 text-center">{kapwing}</td>
  </tr>
);

const FAQItem = ({ question, answer, isOpen, onClick }) => (
  <div className="rounded-xl overflow-hidden" style={{ border: '1px solid var(--border)', background: 'var(--surface)' }}>
    <button
      onClick={onClick}
      className="w-full flex items-center justify-between px-6 py-4 text-left transition-colors"
    >
      <span className="font-medium pr-4" style={{ color: 'var(--ink)' }}>{question}</span>
      <ChevronDown size={18} className={`flex-shrink-0 transition-transform ${isOpen ? 'rotate-180' : ''}`} style={{ color: 'var(--muted)' }} />
    </button>
    {isOpen && (
      <div className="px-6 pb-5">
        <p className="text-sm leading-relaxed" style={{ color: 'var(--muted)' }}>{answer}</p>
      </div>
    )}
  </div>
);

const CtaButton = ({ onClick, children, icon }) => (
  <button
    onClick={onClick}
    className="flex items-center justify-center gap-2 rounded-xl font-medium transition-all"
    style={{ background: 'var(--primary)', color: 'var(--primary-fg)', padding: '0.875rem 2rem', fontSize: '1.0625rem', boxShadow: '0 16px 40px ' + prim(0.2) }}
  >
    {children}
    {icon && <ArrowRight size={20} />}
  </button>
);

const GhostButton = ({ href, children, icon, external }) => (
  <a
    href={href}
    {...(external ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
    className="flex items-center gap-2 rounded-xl transition-all"
    style={{ background: prim(0.06), border: '1px solid var(--border-2)', color: 'var(--ink)', padding: '0.875rem 1.5rem', fontSize: '1.0625rem', fontWeight: 500 }}
  >
    {icon}
    {children}
  </a>
);

const CheckItem = ({ children }) => (
  <li className="flex items-center gap-2 text-xs" style={{ color: 'var(--muted)' }}>
    <Check size={12} className="shrink-0" style={{ color: 'var(--success)' }} />{children}
  </li>
);

export default function Landing({ onLaunchApp }) {
  const [openFaq, setOpenFaq] = React.useState(null);

  const features = [
    {
      icon: Sparkles,
      title: "AI Viral Moment Detection",
      description: "Google Gemini 3.0 Flash analyzes your video transcript and scene boundaries to detect the 3-15 most engaging moments. Each clip is scored for viral potential based on emotional impact, hook strength, and shareability."
    },
    {
      icon: Scissors,
      title: "Smart 9:16 Vertical Cropping",
      description: "Dual-mode AI reframing: TRACK mode follows subjects with MediaPipe face detection + YOLOv8 fallback. GENERAL mode creates blurred backgrounds for group shots and landscapes."
    },
    {
      icon: Subtitles,
      title: "Automatic Subtitle Generation",
      description: "Powered by faster-whisper with word-level timestamps. According to Verizon Media research, 80% of viewers are more likely to watch a video to completion when captions are available."
    },
    {
      icon: Languages,
      title: "AI Voice Dubbing in 30+ Languages",
      description: "ElevenLabs AI integration translates and dubs your video audio while preserving the original speaker's voice. 76% of consumers prefer content in their native language — dubbing unlocks global audiences."
    },
    {
      icon: Type,
      title: "Hook Text Overlays",
      description: "Add attention-grabbing text overlays with styled fonts. AI-generated hook titles capture viewers in the first 3 seconds — critical for TikTok and Reels engagement."
    },
    {
      icon: Zap,
      title: "AI Video Effects",
      description: "Google Gemini generates dynamic FFmpeg filters for professional video effects — color grading, transitions, and visual enhancements applied automatically."
    },
    {
      icon: Upload,
      title: "Local Video Upload",
      description: "Upload your long-form videos — podcasts, webinars, livestreams, vlogs — at full original resolution and audio quality. Process content you own or have rights to."
    },
    {
      icon: Shield,
      title: "100% Self-Hosted & Private",
      description: "Deploy with Docker on your own machine. Your videos never leave your infrastructure. API keys are encrypted client-side and never stored on the server."
    },
    {
      icon: Monitor,
      title: "Free AI YouTube Studio",
      description: "Free AI YouTube thumbnail generator, AI title suggestions (10 viral options with a refinement chat), and auto-generated descriptions with chapter timestamps — all free. Publish directly to YouTube from one workflow."
    },
    {
      icon: Globe,
      title: "Direct Social Publishing",
      description: "Post directly to TikTok, Instagram Reels, and YouTube Shorts from the dashboard. Async uploads with progress tracking and S3 cloud backup."
    },
    {
      icon: Zap,
      title: "AI UGC Video Generator",
      description: "Generate marketing videos with AI actors for any product or business. Paste a URL or describe your product — AI writes the script, creates a talking avatar with lip-sync, adds b-roll, subtitles, and hooks. From $0.65/video."
    },
    {
      icon: FileVideo,
      title: "AI Actors & Lip-Sync",
      description: "Choose from a gallery of AI-generated actors or upload your own photo. UGC pipeline produces a talking head video with natural movement and lip-synced voiceover in English or Spanish."
    }
  ];

  const steps = [
    { title: "Upload a Long-Form Video", description: "Drop any video file you own — podcasts, webinars, livestreams, interviews. OpenShorts supports all common formats and resolutions." },
    { title: "AI Detects the Best Viral Moments", description: "Google Gemini 3.0 Flash transcribes, analyzes scene boundaries, and identifies 3-15 high-potential clips of 15-60 seconds each." },
    { title: "Smart Cropping to Vertical 9:16", description: "AI reframes each clip to vertical format with subject tracking. Subjects stay centered with stabilized camera movement — no manual positioning." },
    { title: "Add Subtitles, Hooks & Effects", description: "Auto-generate styled subtitles, add hook text overlays, and apply AI video effects. Optionally dub into 30+ languages." },
    { title: "Download or Post to Social Media", description: "Export your viral-ready clips or post directly to TikTok, Instagram Reels, and YouTube Shorts from the dashboard." }
  ];

  const faqs = [
    {
      question: "What is OpenShorts and how does it work?",
      answer: "OpenShorts is a free, open source AI clip generator that transforms your long-form videos — podcasts, webinars, livestreams, vlogs, interviews — into viral-ready short clips in 9:16 vertical format. It uses a multi-step AI pipeline: faster-whisper for transcription with word-level timestamps, PySceneDetect for scene boundary detection, and Google Gemini 3.0 Flash AI for identifying the most engaging viral moments."
    },
    {
      question: "Is OpenShorts really free? What's the catch?",
      answer: "OpenShorts is 100% free and open source. You self-host it using Docker on your own machine or server. It uses three external APIs — all with free tiers. Google Gemini API (required) powers the AI analysis and image generation — its free tier includes 1,500 requests per day. ElevenLabs API (optional) enables AI voice dubbing in 30+ languages. Upload-Post API (optional) enables direct publishing — 10 free uploads/month. There are no watermarks, no usage limits, and no subscriptions — unlike Opus Clip ($15-228/month) or Kapwing ($24-79/month)."
    },
    {
      question: "How does OpenShorts compare to Opus Clip?",
      answer: "OpenShorts is a free, self-hosted alternative to Opus Clip. Both offer AI viral moment detection and smart vertical cropping. Key differences: OpenShorts is completely free vs Opus Clip's $15-228/month pricing. OpenShorts runs on your infrastructure (full data privacy) vs cloud-only. OpenShorts adds AI voice dubbing in 30+ languages, AI video effects, and hook text overlays. The trade-off is that OpenShorts requires Docker self-hosting, while Opus Clip is a ready-to-use cloud service."
    },
    {
      question: "How do I turn a long-form video into TikTok or Reels clips?",
      answer: "Upload your long-form video into OpenShorts, enter your free Gemini API key, and click Process. The AI transcribes it with faster-whisper, detects the best viral moments using Google Gemini 3.0 Flash, and crops them to 9:16 vertical format with face tracking. Repurposed short-form clips drive significantly more engagement than original content."
    },
    {
      question: "What AI does OpenShorts use for viral moment detection?",
      answer: "OpenShorts uses Google Gemini 3.0 Flash for viral moment detection and title generation. The AI receives a transcript with timestamps, scene boundary data from PySceneDetect, and analyzes engagement patterns to identify the 3-15 most shareable moments — similar to how platforms like TikTok and YouTube rank content."
    },
    {
      question: "Can OpenShorts translate and dub videos into other languages?",
      answer: "Yes. OpenShorts integrates with ElevenLabs AI dubbing to translate your video audio into over 30 languages while preserving the original speaker's voice. After dubbing, the system automatically re-transcribes the new audio and generates subtitles in the target language."
    },
    {
      question: "How does the smart vertical cropping work?",
      answer: "OpenShorts offers two intelligent cropping modes. TRACK mode follows a single subject with smooth, stabilized camera movement. GENERAL mode handles group shots and landscapes by creating a blurred background layout. A speaker tracker prevents rapid subject switching and handles temporary occlusions."
    },
    {
      question: "Can OpenShorts generate YouTube thumbnails and titles for free?",
      answer: "Yes. OpenShorts includes a free AI YouTube thumbnail generator, AI title generator, and AI description generator — all powered by Google Gemini 3.0 Flash. Upload your video and the AI suggests 10 viral title options with an interactive refinement chat, generates thumbnail designs, and auto-builds descriptions with chapter timestamps."
    },
    {
      question: "What are the system requirements to run OpenShorts?",
      answer: "OpenShorts runs on any system with Docker installed. The recommended setup is 8GB+ RAM and a modern multi-core CPU. GPU acceleration (NVIDIA CUDA) is optional but speeds up video processing significantly. It works on Linux, macOS, and Windows (via WSL2/Docker Desktop)."
    },
    {
      question: "Is there a free open source clip generator?",
      answer: "Yes — OpenShorts is a 100% free, open source clip generator. It also includes a free AI YouTube thumbnail generator, AI title suggester, and AI description generator — features that other clip tools charge extra for. You self-host with Docker for full privacy and control."
    },
    {
      question: "What is the AI UGC Video Generator?",
      answer: "OpenShorts includes an AI UGC (User Generated Content) video creator. You describe your product or paste a website URL — the AI writes a viral script, generates a realistic AI actor with lip-synced voiceover, adds b-roll visuals, TikTok-style subtitles, and hook overlays. Two cost modes: Low Cost (~$0.65/video) and Premium (~$2/video)."
    },
    {
      question: "How much does it cost to generate an AI UGC video?",
      answer: "OpenShorts itself is free, but the AI Shorts feature uses external paid APIs. Low Cost mode costs ~$0.65 per video. Premium mode costs ~$2.00 per video. Both are far cheaper than hiring UGC creators ($50-500/video) or using other avatar platforms."
    },
    {
      question: "Can I use the AI UGC Video Generator for any type of business?",
      answer: "Yes. The AI Shorts generator works for any product, service, or business. Just describe your business (e.g. 'Artisan pizza restaurant in Madrid') or paste your website URL, and the AI generates viral marketing scripts tailored to your business."
    }
  ];

  const checkIcon = <Check size={16} className="mx-auto" style={{ color: 'var(--success)' }} />;
  const xIcon = <span className="text-sm" style={{ color: 'var(--subtle)' }}>Paid</span>;
  const noIcon = <span className="text-sm" style={{ color: 'var(--subtle)' }}>No</span>;
  const limitedIcon = <span className="text-sm" style={{ color: 'var(--subtle)' }}>Limited</span>;

  return (
    <div className="min-h-screen" style={{ background: 'var(--bg)' }}>
      {/* Navigation */}
      <nav className="fixed top-0 w-full z-50 border-b"
        style={{ background: 'oklch(0.06 0.004 170 / 0.85)', backdropFilter: 'blur(12px)', borderColor: 'var(--border)' }}
      >
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <img src="/logo-openshorts.png" alt="OpenShorts logo" className="w-8 h-8" />
            <span className="text-lg font-bold" style={{ color: 'var(--ink)' }}>OpenShorts</span>
          </div>
          <div className="hidden md:flex items-center gap-8 text-sm" style={{ color: 'var(--muted)' }}>
            <a href="#features" style={{ color: 'inherit' }}>Features</a>
            <a href="#how-it-works" style={{ color: 'inherit' }}>How It Works</a>
            <a href="#comparison" style={{ color: 'inherit' }}>Comparison</a>
            <a href="#faq" style={{ color: 'inherit' }}>FAQ</a>
          </div>
          <div className="flex items-center gap-3">
            <a
              href="https://github.com/mutonby/openshorts"
              target="_blank"
              rel="noopener noreferrer"
              className="hidden sm:flex items-center gap-2 text-sm"
              style={{ color: 'var(--muted)' }}
            >
              <Github size={18} />
              <span>GitHub</span>
            </a>
            <button
              onClick={onLaunchApp}
              className="rounded-xl px-5 py-2 text-sm font-medium transition-all"
              style={{ background: 'var(--primary)', color: 'var(--primary-fg)', boxShadow: '0 8px 24px ' + prim(0.2) }}
            >
              Launch App
            </button>
          </div>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="pt-32 pb-20 px-6">
        <div className="max-w-5xl mx-auto text-center">
          <div className="inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-sm mb-8"
            style={{ background: prim(0.1), border: '1px solid ' + prim(0.25), color: 'var(--primary)' }}
          >
            <Sparkles size={14} />
            <span>Free & Open Source AI Clip Generator + UGC Video Creator</span>
          </div>

          <h1 className="text-4xl md:text-6xl lg:text-7xl font-bold leading-tight mb-6 tracking-tight" style={{ color: 'var(--ink)' }}>
            Free Open Source
            <span style={{ background: 'linear-gradient(90deg, var(--primary), var(--accent), var(--primary))', WebkitBackgroundClip: 'text', backgroundClip: 'text', color: 'transparent' }}> Clip Generator </span>
            &amp; AI UGC Video Creator
          </h1>

          <p className="text-lg md:text-xl max-w-3xl mx-auto mb-10 leading-relaxed" style={{ color: 'var(--muted)' }}>
            Three tools in one. <strong style={{ color: 'var(--ink)' }}>Clip Generator:</strong> turn your long-form videos into viral shorts with AI moment detection, smart 9:16 crop, and auto subtitles. <strong style={{ color: 'var(--ink)' }}>AI Shorts:</strong> generate UGC marketing videos with AI actors for any business. <strong style={{ color: 'var(--ink)' }}>YouTube Studio:</strong> free AI thumbnail generator, viral title suggestions, and auto descriptions. Self-hosted, open source.
          </p>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-12">
            <button
              onClick={onLaunchApp}
              className="flex items-center gap-2 rounded-xl font-medium transition-all"
              style={{ background: 'var(--primary)', color: 'var(--primary-fg)', padding: '0.875rem 2rem', fontSize: '1.0625rem', boxShadow: '0 16px 40px ' + prim(0.2) }}
            >
              Get Started Free
              <ArrowRight size={20} />
            </button>
            <a
              href="https://github.com/mutify/openshorts"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 rounded-xl px-8 py-3.5 transition-all text-lg"
              style={{ background: prim(0.06), border: '1px solid var(--border-2)', color: 'var(--ink)', fontWeight: 500 }}
            >
              <Github size={20} />
              View on GitHub
            </a>
          </div>

          {/* Platform Icons */}
          <div className="flex items-center justify-center gap-6" style={{ color: 'var(--muted)' }}>
            <span className="text-sm">Export to:</span>
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-1.5" style={{ color: 'var(--muted)' }}>
                <TikTokIcon size={18} />
                <span className="text-sm">TikTok</span>
              </div>
              <div className="flex items-center gap-1.5" style={{ color: 'var(--muted)' }}>
                <InstagramNoIcon size={18} />
                <span className="text-sm">Reels</span>
              </div>
              <div className="flex items-center gap-1.5" style={{ color: 'var(--muted)' }}>
                <YoutubeNoIcon size={18} />
                <span className="text-sm">Shorts</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Stats Bar */}
      <section style={{ border: '1px solid var(--border)', borderLeft: 'none', borderRight: 'none', background: 'oklch(0.10 0.004 170 / 0.5)' }}>
        <div className="max-w-5xl mx-auto px-6 py-10 grid grid-cols-2 md:grid-cols-4 gap-8 text-center">
          <div>
            <div className="text-3xl font-bold" style={{ color: 'var(--ink)' }}>100%</div>
            <div className="text-sm mt-1" style={{ color: 'var(--muted)' }}>Free &amp; Open Source</div>
          </div>
          <div>
            <div className="text-3xl font-bold" style={{ color: 'var(--ink)' }}>3</div>
            <div className="text-sm mt-1" style={{ color: 'var(--muted)' }}>Tools in One</div>
          </div>
          <div>
            <div className="text-3xl font-bold" style={{ color: 'var(--ink)' }}>30+</div>
            <div className="text-sm mt-1" style={{ color: 'var(--muted)' }}>Dubbing Languages</div>
          </div>
          <div>
            <div className="text-3xl font-bold" style={{ color: 'var(--ink)' }}>$0</div>
            <div className="text-sm mt-1" style={{ color: 'var(--muted)' }}>No Watermarks</div>
          </div>
        </div>
      </section>

      {/* 3 Tools in 1 Section */}
      <section className="py-20 px-6">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="text-3xl md:text-4xl font-bold mb-4" style={{ color: 'var(--ink)' }}>3 Free Tools in 1 Platform</h2>
            <p className="max-w-2xl mx-auto" style={{ color: 'var(--muted)' }}>Everything you need to create, optimize, and publish short-form video content — free and open source.</p>
          </div>
          <div className="grid md:grid-cols-3 gap-6">
            <div className="rounded-xl p-8 relative overflow-hidden" style={{ background: 'var(--surface)', border: '1px solid ' + prim(0.2) }}>
              <div className="absolute top-0 right-0 w-32 h-32 rounded-full -translate-y-1/2 translate-x-1/2" style={{ background: prim(0.05) }} />
              <Scissors size={28} className="mb-4" style={{ color: 'var(--primary)' }} />
              <h3 className="text-xl font-bold mb-2" style={{ color: 'var(--ink)' }}>Clip Generator</h3>
              <p className="text-sm leading-relaxed mb-4" style={{ color: 'var(--muted)' }}>Turn your long-form videos into viral-ready 9:16 shorts. AI detects the best moments, and adds subtitles automatically.</p>
              <ul className="space-y-1.5">
                {['AI viral moment detection', 'Smart tracking crop', 'Auto subtitles + hook overlays', 'AI dubbing in 30+ languages'].map((f, i) => (
                  <CardItem key={i} children={f} />
                ))}
              </ul>
            </div>
            <div className="rounded-xl p-8 relative overflow-hidden" style={{ background: 'var(--surface)', border: '1px solid ' + prim(0.2) }}>
              <div className="absolute top-0 right-0 w-32 h-32 rounded-full -translate-y-1/2 translate-x-1/2" style={{ background: prim(0.05) }} />
              <Zap size={28} className="mb-4" style={{ color: 'var(--primary)' }} />
              <h3 className="text-xl font-bold mb-2" style={{ color: 'var(--ink)' }}>AI Shorts</h3>
              <p className="text-sm leading-relaxed mb-4" style={{ color: 'var(--muted)' }}>Generate UGC marketing videos with AI actors for any product. Just describe your product and get a viral-ready video.</p>
              <ul className="space-y-1.5">
                {['AI actor generation + lip-sync', 'Script writing from URL or description', 'TikTok-style subtitles', 'From $0.65 per video'].map((f, i) => (
                  <CardItem key={i} children={f} />
                ))}
              </ul>
            </div>
            <div className="rounded-xl p-8 relative overflow-hidden" style={{ background: 'var(--surface)', border: '1px solid ' + prim(0.2) }}>
              <div className="absolute top-0 right-0 w-32 h-32 rounded-full -translate-y-1/2 translate-x-1/2" style={{ background: prim(0.05) }} />
              <Monitor size={28} className="mb-4" style={{ color: 'var(--primary)' }} />
              <h3 className="text-xl font-bold mb-2" style={{ color: 'var(--ink)' }}>YouTube Studio</h3>
              <p className="text-sm leading-relaxed mb-4" style={{ color: 'var(--muted)' }}>Complete free AI YouTube toolkit. Generate thumbnails, get viral title suggestions, and auto-generate descriptions with timestamps.</p>
              <ul className="space-y-1.5">
                {['AI thumbnail generator', '10 viral title suggestions + chat', 'Auto descriptions with chapters', 'Direct publish to YouTube'].map((f, i) => (
                  <CardItem key={i} children={f} />
                ))}
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section id="features" className="py-20 px-6">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="text-3xl md:text-4xl font-bold mb-4" style={{ color: 'var(--ink)' }}>Free AI Clip Generator + UGC Video Creator</h2>
            <p className="max-w-2xl mx-auto" style={{ color: 'var(--muted)' }}>Three tools in one: clip long videos into viral shorts, generate UGC marketing videos with AI actors, and a complete YouTube Studio.</p>
          </div>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-5">
            {features.map((feature, i) => (
              <FeatureCard key={i} {...feature} />
            ))}
          </div>
        </div>
      </section>

      {/* API Keys Section */}
      <section className="py-20 px-6" style={{ background: 'oklch(0.10 0.004 170 / 0.4)' }}>
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="text-3xl md:text-4xl font-bold mb-4" style={{ color: 'var(--ink)' }}>All APIs Have Free Tiers</h2>
            <p className="max-w-2xl mx-auto" style={{ color: 'var(--muted)' }}>OpenShorts uses three external APIs — all with generous free tiers. Only Gemini is required. Your API keys are encrypted client-side and never stored on the server.</p>
          </div>
          <div className="grid md:grid-cols-3 gap-5">
            <ApiCard required label="REQUIRED" icon={<Cpu size={24} style={{ color: 'var(--primary)' }} />} title="Google Gemini API" chip="Free tier: 1,500 req/day" color="primary">
              Powers all AI features: viral moment detection, title generation, video effects, thumbnail creation, and description writing.
            </ApiCard>
            <ApiCard label="OPTIONAL" icon={<Languages size={24} style={{ color: 'var(--primary)' }} />} title="ElevenLabs API" chip="Free tier included" color="primary" desc="Enables AI voice dubbing and translation in 30+ languages while preserving the speaker's voice." />
            <ApiCard label="OPTIONAL" icon={<Globe size={24} style={{ color: 'var(--primary)' }} />} title="Upload-Post API" chip="Free tier included" color="primary"
              desc={
                <>Enables direct publishing to YouTube, TikTok, and Instagram Reels from the dashboard. <a href="https://www.upload-post.com" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent)', textDecoration: 'underline' }}>Social media API</a>.</>
              } />
          </div>
          <div className="grid md:grid-cols-2 gap-5 mt-5">
            <ApiCard label="AI SHORTS" icon={<Zap size={24} style={{ color: 'var(--accent)' }} />} title="fal.ai API" chip="Pay-per-use from $0.04" desc="Powers AI Shorts: generates actor images, talking head videos, and lip-sync. Required only for the AI UGC video generator." />
            <ApiCard label="AI SHORTS" icon={<Languages size={24} style={{ color: 'var(--accent)' }} />} title="ElevenLabs TTS" chip="Free tier included" desc="Generates natural voiceovers for AI Shorts from the script. Multiple voices in English and Spanish." />
          </div>
        </div>
      </section>

      {/* How It Works Section */}
      <section id="how-it-works" className="py-20 px-6">
        <div className="max-w-4xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="text-3xl md:text-4xl font-bold mb-4" style={{ color: 'var(--ink)' }}>How It Works</h2>
            <p className="max-w-2xl mx-auto" style={{ color: 'var(--muted)' }}>From a long-form video to viral-ready clips in 5 automated steps. The pipeline runs on your machine with AI doing the heavy lifting.</p>
          </div>
          <div className="space-y-8">
            {steps.map((step, i) => (
              <StepCard key={i} number={i + 1} {...step} />
            ))}
          </div>
        </div>
      </section>

      {/* Tech Stack */}
      <section className="py-20 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="text-3xl md:text-4xl font-bold mb-4" style={{ color: 'var(--ink)' }}>Built with Proven Technology</h2>
            <p className="max-w-2xl mx-auto" style={{ color: 'var(--muted)' }}>OpenShorts combines industry-leading AI models and open source tools into a production-ready video pipeline.</p>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { name: "Google Gemini 3.0", desc: "AI Analysis" },
              { name: "faster-whisper", desc: "Transcription" },
              { name: "YOLOv8", desc: "Object Detection" },
              { name: "MediaPipe", desc: "Tracking" },
              { name: "FFmpeg", desc: "Video Processing" },
              { name: "ElevenLabs", desc: "Voice & TTS" },
              { name: "fal.ai", desc: "AI Video Gen" },
              { name: "React + Vite", desc: "Dashboard" },
              { name: "Docker", desc: "Deployment" }
            ].map((tech, i) => (
              <div key={i} className="rounded-xl p-4 text-center" style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
                <div className="text-sm font-medium" style={{ color: 'var(--ink)' }}>{tech.name}</div>
                <div className="text-xs mt-1" style={{ color: 'var(--subtle)' }}>{tech.desc}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Comparison Table */}
      <section id="comparison" className="py-20 px-6" style={{ background: 'oklch(0.10 0.004 170 / 0.4)' }}>
        <div className="max-w-4xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="text-3xl md:text-4xl font-bold mb-4" style={{ color: 'var(--ink)' }}>Free Clip Generator vs Paid Alternatives</h2>
            <p className="max-w-2xl mx-auto" style={{ color: 'var(--muted)' }}>Why pay $15-228/month for an AI clip generator when you can self-host the same capabilities for free? OpenShorts includes a free YouTube thumbnail studio and AI title suggestions.</p>
          </div>
          <div className="overflow-x-auto" style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
            <table className="w-full">
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)' }}>
                  <th className="py-3 px-4 text-left text-sm font-medium" style={{ color: 'var(--muted)' }}>Feature</th>
                  <th className="py-3 px-4 text-center text-sm font-medium" style={{ color: 'var(--primary)' }}>OpenShorts</th>
                  <th className="py-3 px-4 text-center text-sm font-medium" style={{ color: 'var(--muted)' }}>Opus Clip</th>
                  <th className="py-3 px-4 text-center text-sm font-medium" style={{ color: 'var(--muted)' }}>Kapwing</th>
                </tr>
              </thead>
              <tbody>
                <ComparisonRow feature="Price" openshorts={<span className="font-semibold" style={{ color: 'var(--success)' }}>$0 Free</span>} competia={xIcon} kapwing={xIcon} />
                <ComparisonRow feature="AI Viral Moment Detection" openshorts={checkIcon} competia={checkIcon} kapwing={checkIcon} />
                <ComparisonRow feature="Smart Vertical Cropping" openshorts={checkIcon} competia={checkIcon} kapwing={checkIcon} />
                <ComparisonRow feature="Auto Subtitles" openshorts={checkIcon} competia={checkIcon} kapwing={checkIcon} />
                <ComparisonRow feature="AI Voice Dubbing" openshorts={checkIcon} competia={limitedIcon} kapwing={noIcon} />
                <ComparisonRow feature="AI Video Effects" openshorts={checkIcon} competia={noIcon} kapwing={checkIcon} />
                <ComparisonRow feature="Hook Text Overlays" openshorts={checkIcon} competia={checkIcon} kapwing={checkIcon} />
                <ComparisonRow feature="Self-Hosted / Privacy" openshorts={checkIcon} competia={<span className="text-sm" style={{ color: 'var(--subtle)' }}>Cloud only</span>} kapwing={<span className="text-sm" style={{ color: 'var(--subtle)' }}>Cloud only</span>} />
                <ComparisonRow feature="No Watermark" openshorts={checkIcon} competia={<span className="text-sm" style={{ color: 'var(--subtle)' }}>Free tier only</span>} kapwing={xIcon} />
                <ComparisonRow feature="Open Source" openshorts={checkIcon} competia={noIcon} kapwing={noIcon} />
                <ComparisonRow feature="AI YouTube Thumbnail Generator" openshorts={checkIcon} competia={noIcon} kapwing={xIcon} />
                <ComparisonRow feature="AI Title & Description Generator" openshorts={checkIcon} competia={limitedIcon} kapwing={xIcon} />
                <ComparisonRow feature="AI UGC Video Generator" openshorts={checkIcon} competia={noIcon} kapwing={noIcon} />
                <ComparisonRow feature="AI Actors with Lip-Sync" openshorts={checkIcon} competia={noIcon} kapwing={noIcon} />
                <ComparisonRow feature="Usage Limits" openshorts={<span className="text-sm" style={{ color: 'var(--success)' }}>Unlimited</span>} competia={<span className="text-sm" style={{ color: 'var(--subtle)' }}>Per plan</span>} kapwing={<span className="text-sm" style={{ color: 'var(--subtle)' }}>Per plan</span>} />
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* Use Cases */}
      <section className="py-20 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="text-3xl md:text-4xl font-bold mb-4" style={{ color: 'var(--ink)' }}>Who Uses OpenShorts?</h2>
            <p className="max-w-2xl mx-auto" style={{ color: 'var(--muted)' }}>Content creators, marketers, and agencies use OpenShorts to scale short-form video production.</p>
          </div>
          <div className="grid md:grid-cols-3 gap-5">
            {[
              { title: "Content Creators", description: "Repurpose your long-form videos into TikTok and Reels clips automatically.", icon: Youtube },
              { title: "Social Media Managers", description: "Scale short-form content production for multiple clients and publish from one dashboard.", icon: Instagram },
              { title: "Podcasters & Educators", description: "Extract the most engaging moments from podcast episodes and lessons.", icon: FileVideo },
              { title: "Businesses & Brands", description: "Generate UGC-style marketing videos with AI actors. No camera, no studio, no influencer budget.", icon: Zap }
            ].map((useCase, i) => (
              <div key={i} className="rounded-2xl p-6" style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
                <useCase.icon size={24} className="mb-4" style={{ color: 'var(--primary)' }} />
                <h3 className="text-lg font-semibold mb-2" style={{ color: 'var(--ink)' }}>{useCase.title}</h3>
                <p className="text-sm leading-relaxed" style={{ color: 'var(--muted)' }}>{useCase.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* FAQ Section */}
      <section id="faq" className="py-20 px-6" style={{ background: 'oklch(0.10 0.004 170 / 0.4)' }}>
        <div className="max-w-3xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="text-3xl md:text-4xl font-bold mb-4" style={{ color: 'var(--ink)' }}>Frequently Asked Questions</h2>
            <p className="mb-4" style={{ color: 'var(--muted)' }}>Everything you need to know about OpenShorts, from setup to features.</p>
          </div>
          <div className="space-y-3">
            {faqs.map((faq, i) => (
              <FAQItem
                key={i}
                question={faq.question}
                answer={faq.answer}
                isOpen={openFaq === i}
                onClick={() => setOpenFaq(openFaq === i ? null : i)}
              />
            ))}
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-20 px-6">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="text-3xl md:text-4xl font-bold mb-4" style={{ color: 'var(--ink)' }}>Start Creating Viral Videos for Free</h2>
          <p className="mb-8 max-w-xl mx-auto" style={{ color: 'var(--muted)' }}>No sign-up, no credit card, no watermarks. Generate viral clips from long videos or create AI UGC marketing videos. Self-host with Docker.</p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <CtaButton onClick={onLaunchApp} icon
              children="Launch OpenShorts"
            />
            <a
              href="https://github.com/mutonby/openshorts"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 text-sm"
              style={{ color: 'var(--muted)' }}
            >
              <Github size={18} />
              Star on GitHub
            </a>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t py-10 px-6" style={{ borderColor: 'var(--border)' }}>
        <div className="max-w-5xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <img src="/logo-openshorts.png" alt="OpenShorts" className="w-6 h-6" />
            <span className="text-sm" style={{ color: 'var(--muted)' }}>OpenShorts — Free Open Source Clip Generator &amp; AI UGC Video Creator</span>
          </div>
          <div className="flex items-center gap-6 text-sm" style={{ color: 'var(--subtle)' }}>
            <a href="https://github.com/mutify/openshorts" target="_blank" rel="noopener noreferrer" style={{ color: 'inherit' }}>GitHub</a>
            <a href="#features" style={{ color: 'inherit' }}>Features</a>
            <a href="#faq" style={{ color: 'inherit' }}>FAQ</a>
            <a href="#legal" style={{ color: 'inherit' }}>Terms &amp; Privacy</a>
          </div>
        </div>
      </footer>
    </div>
  );
}

const InstagramNoIcon = ({ size = 18, className = "" }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
    <rect x="2" y="2" width="20" height="20" rx="5" ry="5"></rect>
    <path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"></path>
    <line x1="17.5" y1="6.5" x2="17.51" y2="6.5"></line>
  </svg>
);

const YoutubeNoIcon = ({ size = 18, className = "" }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d="M22.54 6.42a2.78 2.78 0 0 0-1.94-2C18.88 4 12 4 12 4s-6.88 0-8.6.46a2.78 2.78 0 0 0-1.94 2A29 29 0 0 0 1 11.75a29 29 0 0 0 .46 5.33A2.78 2.78 0 0 0 3.4 19c1.72.46 8.6.46 8.6.46s6.88 0 8.6-.46a2.78 2.78 0 0 0 1.94-2 29 29 0 0 0 .46-5.25 29 29 0 0 0-.46-5.33z"></path>
    <polygon points="9.75 15.02 15.5 11.75 9.75 8.48 9.75 15.02"></polygon>
  </svg>
);

const CardItem = ({ children }) => (
  <li className="flex items-center gap-2 text-xs" style={{ color: 'var(--muted)' }}>
    <Check size={12} className="shrink-0" style={{ color: 'var(--success)' }} />{children}
  </li>
);

const ApiCard = ({ label, icon, title, chip, desc }) => (
  <div className="rounded-2xl p-6 relative" style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
    <div className="absolute top-4 right-4 rounded-full px-2 py-0.5 text-[10px] font-bold"
      style={{ background: prim(0.15), color: 'var(--primary)', border: '1px solid ' + prim(0.3) }}
    >{label}</div>
    <div className="w-12 h-12 rounded-xl flex items-center justify-center mb-4" style={{ background: prim(0.1) }}>
      {icon}
    </div>
    <h3 className="text-lg font-semibold mb-1" style={{ color: 'var(--ink)' }}>{title}</h3>
    <span className="inline-block mb-3 rounded-full px-2 py-0.5 text-xs"
      style={{ background: 'oklch(0.65 0.14 155 / 0.10)', border: '1px solid oklch(0.65 0.14 155 / 0.2)', color: 'var(--success)' }}>
      {chip}
    </span>
    <p className="text-sm leading-relaxed" style={{ color: 'var(--muted)' }}>{desc}</p>
  </div>
);