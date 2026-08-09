import React, { useState, useEffect, useRef } from 'react';
import {
  Upload, FileVideo, Sparkles, Youtube, Instagram, Share2,
  ChevronDown, Check, LayoutDashboard, Settings, PlusCircle,
  X, Shield, LayoutGrid, Image, Globe, RotateCcw, AlertTriangle,
  KeyRound, Bot, Users, Smartphone, ExternalLink, Copy, CheckCircle2,
  Trash2, Clock, Menu, Activity
} from 'lucide-react';
import ThumbnailStudio from './components/ThumbnailStudio';
import SaaShortsTab from './components/SaaShortsTab';
import UGCGallery from './components/UGCGallery';
import ScheduleWeekModal from './components/ScheduleWeekModal';
import { getApiUrl } from './config';
import ProjectDetail from './components/ProjectDetail';

/* ─── Encryption ────────────────────────────────────────────────────── */
const SECRET_KEY = import.meta.env.VITE_ENCRYPTION_KEY || 'OpenShorts-Static-Salt-Change-Me';
const ENCRYPTION_PREFIX = 'ENC:';

const encrypt = (text) => {
  if (!text) return '';
  try {
    const xor = text.split('').map((c, i) =>
      String.fromCharCode(c.charCodeAt(0) ^ SECRET_KEY.charCodeAt(i % SECRET_KEY.length))
    ).join('');
    return ENCRYPTION_PREFIX + btoa(xor);
  } catch { return text; }
};

const decrypt = (text) => {
  if (!text) return '';
  if (text.startsWith(ENCRYPTION_PREFIX)) {
    try {
      const xor = atob(text.slice(ENCRYPTION_PREFIX.length));
      return xor.split('').map((c, i) =>
        String.fromCharCode(c.charCodeAt(0) ^ SECRET_KEY.charCodeAt(i % SECRET_KEY.length))
      ).join('');
    } catch { return ''; }
  }
  return text;
};

/* ─── Icons ─────────────────────────────────────────────────────────── */
const TikTokIcon = ({ size = 16, className = '' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className}>
    <path d="M19.589 6.686a4.793 4.793 0 0 1-3.77-4.245V2h-3.445v13.672a2.896 2.896 0 0 1-5.201 1.743l-.002-.001.002.001a2.895 2.895 0 0 1 3.183-4.51v-3.5a6.329 6.329 0 0 0-5.394 10.692 6.33 6.33 0 0 0 10.857-4.424V8.687a8.182 8.182 0 0 0 4.773 1.526V6.79a4.831 4.831 0 0 1-1.003-.104z" />
  </svg>
);

const GitHubIcon = ({ size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
    <path fillRule="evenodd" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
  </svg>
);

/* ─── User Profile Selector ─────────────────────────────────────────── */
const UserProfileSelector = ({ profiles, selectedUserId, onSelect }) => {
  const [isOpen, setIsOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setIsOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  if (!profiles || profiles.length === 0) return null;
  const selected = profiles.find(p => p.username === selectedUserId) || profiles[0];

  return (
    <div className="relative" ref={ref}>
      <button
        id="profile-selector"
        onClick={() => setIsOpen(!isOpen)}
        className="os-btn os-btn-secondary os-btn-sm"
        style={{ minWidth: 140, gap: 6 }}
      >
        <div style={{
          width: 18, height: 18, borderRadius: '50%',
          background: 'var(--primary)', display: 'flex', alignItems: 'center',
          justifyContent: 'center', fontSize: 9, fontWeight: 700, color: 'var(--primary-fg)',
          flexShrink: 0
        }}>
          {selected?.username?.substring(0, 1).toUpperCase() || 'U'}
        </div>
        <span style={{ fontSize: '0.8125rem', fontWeight: 500, color: 'var(--ink)', maxWidth: 100, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {selected?.username || 'Select User'}
        </span>
        <ChevronDown size={12} style={{ color: 'var(--muted)', transform: isOpen ? 'rotate(180deg)' : 'none', transition: 'transform 150ms' }} />
      </button>

      {isOpen && (
        <div style={{
          position: 'fixed', zIndex: 'var(--z-dropdown)',
          marginTop: 4, width: 240,
          background: 'var(--surface)', border: '1px solid var(--border-2)',
          borderRadius: 8, boxShadow: '0 16px 40px oklch(0 0 0 / 0.5)',
          overflow: 'hidden'
        }}
          className="os-fade-in"
        >
          <div className="os-scroll" style={{ maxHeight: 240, overflowY: 'auto' }}>
            {profiles.map((profile) => (
              <button
                key={profile.username}
                onClick={() => { onSelect(profile.username); setIsOpen(false); }}
                style={{
                  width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '0.625rem 0.875rem', background: 'transparent', border: 'none', cursor: 'pointer',
                  borderBottom: '1px solid var(--border)', textAlign: 'left',
                  transition: 'background var(--dur-fast)'
                }}
                onMouseEnter={e => e.currentTarget.style.background = 'var(--surface-2)'}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <div style={{
                    width: 28, height: 28, borderRadius: '50%',
                    background: 'oklch(0.55 0.095 170 / 0.15)', border: '1px solid var(--border-2)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 10, fontWeight: 700, color: 'var(--primary)', flexShrink: 0
                  }}>
                    {profile.username.substring(0, 2).toUpperCase()}
                  </div>
                  <div>
                    <div style={{ fontSize: '0.8125rem', fontWeight: 500, color: 'var(--ink)', lineHeight: 1.2 }}>
                      {profile.username}
                    </div>
                    <div style={{ display: 'flex', gap: 6, marginTop: 3 }}>
                      <TikTokIcon size={10} style={{ color: profile.connected.includes('tiktok') ? 'var(--ink)' : 'var(--subtle)' }} />
                      <Instagram size={10} style={{ color: profile.connected.includes('instagram') ? '#e1306c' : 'var(--subtle)' }} />
                      <Youtube size={10} style={{ color: profile.connected.includes('youtube') ? '#ff0000' : 'var(--subtle)' }} />
                    </div>
                  </div>
                </div>
                {selectedUserId === profile.username && <Check size={13} style={{ color: 'var(--primary)', flexShrink: 0 }} />}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

/* ─── Constants ─────────────────────────────────────────────────────── */
const SESSION_KEY = 'openshorts_session';
const SESSION_MAX_AGE = 3600000;
const PROJECT_KEY = 'openshorts_current_project';

const pollJob = async (jobId) => {
  const res = await fetch(getApiUrl(`/api/status/${jobId}`));
  if (!res.ok) throw new Error('Status check failed');
  return res.json();
};

/* ─── Nav Items ─────────────────────────────────────────────────────── */
const NAV_ITEMS = [
  { id: 'dashboard',  label: 'Projects',       icon: LayoutDashboard },
  { id: 'saasshorts', label: 'AI Shorts',       icon: Sparkles },
  { id: 'ai-agent',   label: 'AI Agent',        icon: Bot },
  { id: 'ugc-gallery',label: 'UGC Gallery',     icon: LayoutGrid },
  { id: 'thumbnails', label: 'YouTube Studio',  icon: Image },
  { id: 'settings',   label: 'Settings',        icon: Settings },
];

/* ─── Sidebar ───────────────────────────────────────────────────────── */
const Sidebar = ({ activeTab, setActiveTab, setCurrentProject, collapsed }) => (
  <aside
    style={{
      width: collapsed ? 'var(--sidebar-collapsed)' : 'var(--sidebar-w)',
      background: 'var(--surface)',
      borderRight: '1px solid var(--border)',
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      flexShrink: 0,
      transition: 'width var(--dur-slow) var(--ease-out-expo)',
      overflow: 'hidden',
    }}
    aria-label="Main navigation"
  >
    {/* Logo */}
    <div style={{
      height: 48, display: 'flex', alignItems: 'center',
      padding: collapsed ? '0 16px' : '0 16px',
      borderBottom: '1px solid var(--border)',
      gap: 10, flexShrink: 0,
    }}>
      <img
        src="/logo-openshorts.png"
        alt="OpenShorts"
        style={{ width: 24, height: 24, borderRadius: 4, flexShrink: 0, objectFit: 'cover' }}
      />
      {!collapsed && (
        <span style={{ fontWeight: 700, fontSize: '0.9375rem', color: 'var(--ink)', whiteSpace: 'nowrap', letterSpacing: '-0.01em' }}>
          OpenShorts
        </span>
      )}
    </div>

    {/* Nav */}
    <nav style={{ flex: 1, padding: '8px 8px', display: 'flex', flexDirection: 'column', gap: 2, overflowY: 'auto' }}>
      {NAV_ITEMS.map(({ id, label, icon: Icon }) => {
        const isActive = activeTab === id;
        return (
          <button
            key={id}
            id={`nav-${id}`}
            onClick={() => {
              setActiveTab(id);
              if (id === 'dashboard') {
                savedProjectIdRef.current = null;
                localStorage.removeItem(PROJECT_KEY);
                setCurrentProject(null);
              }
            }}
            className={`os-nav-item${isActive ? ' active' : ''}`}
            title={collapsed ? label : undefined}
            style={{ justifyContent: collapsed ? 'center' : 'flex-start' }}
          >
            <Icon size={17} style={{ flexShrink: 0 }} />
            {!collapsed && <span>{label}</span>}
          </button>
        );
      })}
    </nav>

    {/* Footer links */}
    <div style={{ borderTop: '1px solid var(--border)', padding: '8px 8px', display: 'flex', flexDirection: 'column', gap: 2, flexShrink: 0 }}>
      <a
        href="#"
        onClick={(e) => { e.preventDefault(); localStorage.removeItem('openshorts_skip_landing'); window.location.reload(); }}
        className="os-nav-item"
        title={collapsed ? 'Landing Page' : undefined}
        style={{ justifyContent: collapsed ? 'center' : 'flex-start', textDecoration: 'none' }}
      >
        <Globe size={17} style={{ flexShrink: 0 }} />
        {!collapsed && <span>Landing Page</span>}
      </a>
      <a
        href="https://github.com/mutonby/openshorts"
        target="_blank"
        rel="noopener noreferrer"
        className="os-nav-item"
        title={collapsed ? 'GitHub' : undefined}
        style={{ justifyContent: collapsed ? 'center' : 'flex-start', textDecoration: 'none' }}
      >
        <GitHubIcon size={17} />
        {!collapsed && <span>GitHub</span>}
      </a>
    </div>
  </aside>
);

/* ─── Top Header ────────────────────────────────────────────────────── */
const Header = ({ activeTab, status, handleReset, apiKey, setActiveTab, userProfiles, uploadUserId, setUploadUserId, sessionRecovered, setSessionRecovered, onToggleSidebar }) => {
  const currentNav = NAV_ITEMS.find(n => n.id === activeTab);

  return (
    <div style={{ flexShrink: 0 }}>
      <header style={{
        height: 48, display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0 16px', borderBottom: '1px solid var(--border)',
        background: 'var(--surface)', flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <button
            onClick={onToggleSidebar}
            className="os-btn os-btn-ghost os-btn-sm"
            style={{ padding: '5px', borderRadius: 5 }}
            aria-label="Toggle sidebar"
            id="sidebar-toggle"
          >
            <Menu size={16} />
          </button>
          <span style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--ink)' }}>
            {currentNav?.label || 'OpenShorts'}
          </span>
          {status === 'processing' && (
            <span className="os-chip os-chip-primary" style={{ gap: 5 }}>
              <span className="os-dot-live" />
              Processing
            </span>
          )}
          {status === 'complete' && (
            <span className="os-chip os-chip-success">Done</span>
          )}
          {status === 'error' && (
            <span className="os-chip os-chip-error">Error</span>
          )}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {userProfiles.length > 0 && (
            <UserProfileSelector
              profiles={userProfiles}
              selectedUserId={uploadUserId}
              onSelect={setUploadUserId}
            />
          )}
          {!apiKey && (
            <button
              onClick={() => setActiveTab('settings')}
              className="os-chip os-chip-warning"
              style={{ cursor: 'pointer', border: 'none', background: 'oklch(0.75 0.14 65 / 0.12)' }}
            >
              <AlertTriangle size={11} />
              Gemini key missing
            </button>
          )}
          {status !== 'idle' && (
            <button onClick={handleReset} className="os-btn os-btn-ghost os-btn-sm">
              <X size={14} />
              Reset
            </button>
          )}
        </div>
      </header>

      {/* Banners */}
      {!apiKey && activeTab !== 'settings' && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '0.625rem 1rem', gap: 12,
          background: 'oklch(0.75 0.14 65 / 0.08)', borderBottom: '1px solid oklch(0.75 0.14 65 / 0.2)',
        }}
          className="os-fade-in"
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.8125rem', color: 'var(--warning)' }}>
            <KeyRound size={14} style={{ flexShrink: 0 }} />
            <span><strong>Gemini API key required</strong> — set it in Settings to use OpenShorts.</span>
          </div>
          <button
            onClick={() => setActiveTab('settings')}
            className="os-btn os-btn-sm"
            style={{ background: 'var(--warning)', color: 'oklch(0.15 0 0)', border: 'none', flexShrink: 0 }}
          >
            Go to Settings
          </button>
        </div>
      )}

      {sessionRecovered && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '0.5rem 1rem', gap: 12,
          background: 'oklch(0.55 0.095 170 / 0.08)', borderBottom: '1px solid oklch(0.55 0.095 170 / 0.2)',
        }}
          className="os-fade-in"
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.8125rem', color: 'var(--primary)' }}>
            <RotateCcw size={14} />
            <span>Session recovered — your previous work has been restored.</span>
          </div>
          <button onClick={() => setSessionRecovered(false)} className="os-btn os-btn-ghost os-btn-sm" style={{ padding: '4px' }}>
            <X size={14} />
          </button>
        </div>
      )}
    </div>
  );
};

/* ─── Settings View ─────────────────────────────────────────────────── */
const SettingsView = ({
  apiKey, setApiKey,
  uploadPostKey, setUploadPostKey, fetchUserProfiles,
  elevenLabsKey, setElevenLabsKey,
  falKey, setFalKey,
}) => {
  const [saved, setSaved] = useState({});
  const save = (key) => {
    setSaved(s => ({ ...s, [key]: true }));
    setTimeout(() => setSaved(s => ({ ...s, [key]: false })), 2000);
  };

  const Section = ({ title, badge, children }) => (
    <section className="os-panel" style={{ padding: '1.25rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem' }}>
        <h2 style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--ink)', margin: 0 }}>{title}</h2>
        {badge && <span className={`os-chip os-chip-${badge.color}`}>{badge.label}</span>}
      </div>
      {children}
    </section>
  );

  const KeyRow = ({ label, hint, value, onChange, onSave, savedKey, placeholder, type = 'password', extra }) => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <label style={{ fontSize: '0.8125rem', fontWeight: 500, color: 'var(--muted)' }}>{label}</label>
      <div style={{ display: 'flex', gap: 8 }}>
        <input
          type={type}
          value={value}
          onChange={e => onChange(e.target.value)}
          className="os-input"
          placeholder={placeholder}
          style={{ flex: 1 }}
        />
        <button
          onClick={() => { onSave(); save(savedKey); }}
          className="os-btn os-btn-secondary os-btn-sm"
          style={{ flexShrink: 0, gap: 5 }}
        >
          {saved[savedKey] ? <><Check size={13} /> Saved</> : 'Save'}
        </button>
      </div>
      {hint && <p style={{ fontSize: '0.75rem', color: 'var(--subtle)', lineHeight: 1.5 }}>{hint}</p>}
      {extra}
    </div>
  );

  const StepLinks = ({ steps }) => (
    <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
      {steps.map(({ label, href, sub }) => (
        <a
          key={label}
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="os-panel-2"
          style={{ padding: '6px 10px', textDecoration: 'none', fontSize: '0.8125rem', color: 'var(--muted)', display: 'flex', flexDirection: 'column', gap: 2, minWidth: 100 }}
          onMouseEnter={e => e.currentTarget.style.borderColor = 'var(--border-2)'}
          onMouseLeave={e => e.currentTarget.style.borderColor = 'var(--border)'}
        >
          <span style={{ color: 'var(--ink)', fontWeight: 500, fontSize: '0.8125rem' }}>{label}</span>
          {sub && <span style={{ fontSize: '0.6875rem', color: 'var(--subtle)' }}>{sub}</span>}
        </a>
      ))}
    </div>
  );

  return (
    <div className="os-fade-in" style={{ height: '100%', overflowY: 'auto', padding: '1.5rem' }}>
      <div style={{ maxWidth: 600, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '1rem' }}>

        {/* Privacy note */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.75rem', color: 'var(--muted)', padding: '0.5rem 0' }}>
          <Shield size={13} style={{ color: 'var(--success)', flexShrink: 0 }} />
          Keys live in your browser only — sent to backend to process requests, never stored server-side.
        </div>

        {/* Gemini */}
        <Section title="Core" badge={{ label: 'Required', color: 'error' }}>
          <KeyRow
            label="Google Gemini API Key"
            placeholder="AI..."
            value={apiKey}
            type="text"
            onChange={setApiKey}
            onSave={() => { if (apiKey) localStorage.setItem('gemini_key', apiKey); }}
            savedKey="gemini"
            hint="Powers clip detection, script generation, and web research."
            extra={
              <StepLinks steps={[
                { label: '1. Open Studio', href: 'https://aistudio.google.com/app/apikey', sub: 'aistudio.google.com' },
                { label: '2. Create Key', href: 'https://aistudio.google.com/app/apikey', sub: 'Free tier available' },
              ]} />
            }
          />
        </Section>

        {/* Social */}
        <Section title="Social Publishing" badge={{ label: 'Optional', color: 'default' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <p style={{ fontSize: '0.8125rem', color: 'var(--muted)', lineHeight: 1.5, margin: 0 }}>
              Required only to publish clips directly to TikTok, Instagram Reels, and YouTube Shorts via <strong style={{ color: 'var(--ink)' }}>Upload-Post</strong>. Free tier available — no credit card.
            </p>
            <KeyRow
              label="Upload-Post API Key"
              placeholder="ey..."
              value={uploadPostKey}
              onChange={setUploadPostKey}
              onSave={fetchUserProfiles}
              savedKey="uploadpost"
              extra={
                <StepLinks steps={[
                  { label: '1. Login', href: 'https://app.upload-post.com/login', sub: 'Create account' },
                  { label: '2. Profiles', href: 'https://app.upload-post.com/manage-users', sub: 'Connect socials' },
                  { label: '3. API Key', href: 'https://app.upload-post.com/api-keys', sub: 'Generate key' },
                ]} />
              }
            />
          </div>
        </Section>

        {/* ElevenLabs */}
        <Section title="Video Translation" badge={{ label: 'Optional', color: 'default' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <p style={{ fontSize: '0.8125rem', color: 'var(--muted)', lineHeight: 1.5, margin: 0 }}>
              Translate clips to 30+ languages using <strong style={{ color: 'var(--ink)' }}>ElevenLabs</strong> AI dubbing — preserves original voice characteristics.
            </p>
            <KeyRow
              label="ElevenLabs API Key"
              placeholder="sk_..."
              value={elevenLabsKey}
              onChange={setElevenLabsKey}
              onSave={() => { if (elevenLabsKey) localStorage.setItem('elevenLabsKey_v1', encrypt(elevenLabsKey)); }}
              savedKey="elevenlabs"
              extra={
                <StepLinks steps={[
                  { label: '1. Sign up', href: 'https://elevenlabs.io/sign-up', sub: 'Free tier' },
                  { label: '2. API Key', href: 'https://elevenlabs.io/app/settings/api-keys', sub: 'Generate key' },
                ]} />
              }
            />
          </div>
        </Section>

        {/* fal.ai */}
        <Section title="AI Shorts (UGC Videos)" badge={{ label: 'Optional', color: 'default' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <p style={{ fontSize: '0.8125rem', color: 'var(--muted)', lineHeight: 1.5, margin: 0 }}>
              Generate UGC-style videos with AI actors using <strong style={{ color: 'var(--ink)' }}>fal.ai</strong>. Requires fal.ai + ElevenLabs keys.
            </p>
            <KeyRow
              label="fal.ai API Key"
              placeholder="fal_..."
              value={falKey}
              onChange={setFalKey}
              onSave={() => { if (falKey) localStorage.setItem('falKey_v1', encrypt(falKey)); }}
              savedKey="fal"
              extra={
                <StepLinks steps={[
                  { label: '1. Sign up', href: 'https://fal.ai/dashboard/keys', sub: 'fal.ai account' },
                  { label: '2. API Key', href: 'https://fal.ai/dashboard/keys', sub: 'Generate key' },
                ]} />
              }
            />
          </div>
        </Section>

      </div>
    </div>
  );
};

/* ─── AI Agent View ─────────────────────────────────────────────────── */
const AIAgentView = () => (
  <div className="os-fade-in os-scroll" style={{ height: '100%', overflowY: 'auto', padding: '1.5rem' }}>
    <div style={{ maxWidth: 680, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>

      <div>
        <span className="os-chip os-chip-success" style={{ marginBottom: 10, display: 'inline-flex' }}>
          <Bot size={11} />
          Autonomous Skill
        </span>
        <h1 style={{ fontSize: '1.375rem', fontWeight: 700, color: 'var(--ink)', margin: '0 0 8px' }}>
          Your Personal Clipping Team
        </h1>
        <p style={{ fontSize: '0.9rem', color: 'var(--muted)', lineHeight: 1.65, maxWidth: '62ch', margin: 0 }}>
          Drop your videos in a folder and a team of AI clippers picks the viral moments, edits them, and queues them for your approval — like having a 24/7 short-form editing crew on autopilot.
        </p>
      </div>

      {/* Warning */}
      <div className="os-panel" style={{
        padding: '0.875rem 1rem', display: 'flex', alignItems: 'flex-start', gap: 10,
        borderColor: 'oklch(0.75 0.14 65 / 0.3)',
        background: 'oklch(0.75 0.14 65 / 0.06)',
      }}>
        <Smartphone size={16} style={{ color: 'var(--warning)', flexShrink: 0, marginTop: 2 }} />
        <div style={{ fontSize: '0.8125rem', color: 'var(--muted)', lineHeight: 1.55 }}>
          <strong style={{ color: 'var(--warning)', display: 'block', marginBottom: 4 }}>
            Upload videos already in vertical (9:16) mobile format.
          </strong>
          The agent does not reframe horizontal footage. Make sure every source video is shot or pre-cropped to mobile/portrait format before dropping it into the input folder.
        </div>
      </div>

      {/* Workflow steps */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '0.75rem' }}>
        {[
          { icon: Upload, label: 'Drop your videos', desc: 'Put long-form vertical footage in the watched folder. The skill picks one video per run.' },
          { icon: Users, label: 'AI clippers work', desc: 'Whisper transcribes, Gemini spots viral beats, FFmpeg cuts each clip and adds a hook overlay.' },
          { icon: CheckCircle2, label: 'You validate, it ships', desc: 'Approve the candidates you like and the skill auto-publishes to TikTok, Reels, and YouTube Shorts.' },
        ].map(({ icon: Icon, label, desc }) => (
          <div key={label} className="os-panel" style={{ padding: '1rem' }}>
            <div style={{
              width: 32, height: 32, borderRadius: 6, marginBottom: 10,
              background: 'oklch(0.65 0.14 155 / 0.12)', border: '1px solid oklch(0.65 0.14 155 / 0.2)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <Icon size={15} style={{ color: 'var(--success)' }} />
            </div>
            <div style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--ink)', marginBottom: 5 }}>{label}</div>
            <p style={{ fontSize: '0.8rem', color: 'var(--muted)', lineHeight: 1.55, margin: 0 }}>{desc}</p>
          </div>
        ))}
      </div>

      {/* Repo block */}
      <div className="os-panel" style={{ padding: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, marginBottom: '1rem', flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--ink)', marginBottom: 4 }}>skill-autoshorts</div>
            <p style={{ fontSize: '0.8125rem', color: 'var(--muted)', margin: 0, lineHeight: 1.5 }}>
              The Claude Code skill that powers this workflow. Install once, trigger whenever you want a batch of clips.
            </p>
          </div>
          <a
            href="https://github.com/mutonby/skill-autoshorts"
            target="_blank"
            rel="noopener noreferrer"
            className="os-btn os-btn-secondary os-btn-sm"
            style={{ textDecoration: 'none', flexShrink: 0 }}
          >
            View on GitHub
            <ExternalLink size={12} />
          </a>
        </div>

        {/* Clone command */}
        <div className="os-log" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0.625rem 0.875rem', marginBottom: '1rem' }}>
          <span>git clone https://github.com/mutonby/skill-autoshorts</span>
          <button
            onClick={() => navigator.clipboard.writeText('git clone https://github.com/mutonby/skill-autoshorts')}
            className="os-btn os-btn-ghost os-btn-xs"
            title="Copy"
          >
            <Copy size={12} />
          </button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 6 }}>
          {[
            'Daily batch — picks one long video per run',
            'Whisper transcription with word-level timing',
            'Gemini 3.5 Flash multimodal moment detection',
            'Auto-publish to TikTok, Reels & YouTube Shorts',
          ].map(text => (
            <div key={text} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, fontSize: '0.8125rem', color: 'var(--muted)' }}>
              <Check size={14} style={{ color: 'var(--success)', flexShrink: 0, marginTop: 2 }} />
              <span>{text}</span>
            </div>
          ))}
        </div>
      </div>

    </div>
  </div>
);

/* ─── Projects View ─────────────────────────────────────────────────── */
const ProjectsView = ({ projects, projectsLoading, setCurrentProject, showNewProjectModal, setShowNewProjectModal, handleCreateProject, newProjectName, setNewProjectName, dossierEnabled, setDossierEnabled, retentionDays, setRetentionDays, newProjectContentType, setNewProjectContentType, newProjectInstructions, setNewProjectInstructions, handleDeleteProject }) => (
  <div className="os-fade-in os-scroll" style={{ height: '100%', overflowY: 'auto', padding: '1.5rem' }}>
    {/* Heading row */}
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
      <h1 style={{ fontSize: '1.125rem', fontWeight: 600, color: 'var(--ink)', margin: 0 }}>Projects</h1>
      <button
        id="new-project-btn"
        onClick={() => setShowNewProjectModal(true)}
        className="os-btn os-btn-primary os-btn-sm"
      >
        <PlusCircle size={14} />
        New Project
      </button>
    </div>

    {/* Loading state (avoids flashing the empty state on slow fetches) */}
    {projectsLoading ? (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: 320, gap: 12, color: 'var(--subtle)' }}>
        <div style={{ width: 20, height: 20, border: '2px solid var(--border-2)', borderTopColor: 'var(--primary)', borderRadius: '50%', animation: 'spin 0.6s linear infinite' }} />
        <div style={{ fontSize: '0.8125rem', color: 'var(--muted)' }}>Loading projects...</div>
      </div>
    ) : projects.length === 0 ? (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: 320, gap: 12, color: 'var(--subtle)' }}>
        <LayoutDashboard size={36} style={{ color: 'var(--border-2)' }} />
        <div style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--muted)' }}>No projects yet</div>
        <p style={{ fontSize: '0.8125rem', color: 'var(--subtle)', textAlign: 'center', maxWidth: '30ch', lineHeight: 1.5, margin: 0 }}>
          Create your first project to start analyzing videos and clipping viral moments.
        </p>
        <button onClick={() => setShowNewProjectModal(true)} className="os-btn os-btn-secondary os-btn-sm">
          Create Project
        </button>
      </div>
    ) : (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '0.75rem', paddingBottom: '2rem' }}>
        {projects.map((proj) => (
          <div
            key={proj.id}
            onClick={() => setCurrentProject(proj)}
            className="os-panel"
            style={{
              padding: '1rem', cursor: 'pointer', display: 'flex', flexDirection: 'column',
              justifyContent: 'space-between', minHeight: 140,
              transition: 'border-color var(--dur-fast) var(--ease-out-quart), background var(--dur-fast)',
            }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--border-2)'; e.currentTarget.style.background = 'var(--surface-2)'; }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.background = 'var(--surface)'; }}
          >
            <div>
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
                <h3 style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--ink)', margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '85%' }}>
                  {proj.name}
                </h3>
                <button
                  onClick={(e) => handleDeleteProject(proj.id, e)}
                  className="os-btn os-btn-danger os-btn-xs"
                  style={{ padding: '4px', flexShrink: 0, opacity: 0 }}
                  id={`delete-proj-${proj.id}`}
                  onMouseEnter={e => e.currentTarget.style.opacity = 1}
                  onMouseLeave={e => e.currentTarget.style.opacity = 0}
                >
                  <Trash2 size={12} />
                </button>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 8, fontSize: '0.75rem', color: 'var(--subtle)' }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <FileVideo size={12} /> {proj.video_count} videos
                </span>
                <span style={{ width: 3, height: 3, borderRadius: '50%', background: 'var(--subtle)' }} />
                <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <Sparkles size={12} /> {proj.clip_count} clip runs
                </span>
              </div>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingTop: 12, marginTop: 12, borderTop: '1px solid var(--border)', fontSize: '0.75rem' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: 4, color: 'var(--subtle)' }}>
                <Clock size={11} /> {proj.retention_days}d
              </span>
              <span className={`os-chip ${proj.dossier_enabled ? 'os-chip-primary' : 'os-chip-default'}`}>
                {proj.dossier_enabled ? 'Dossier' : 'Standard'}
              </span>
            </div>
          </div>
        ))}
      </div>
    )}

    {/* New Project Modal */}
    {showNewProjectModal && (
      <div className="os-modal-backdrop" onClick={() => setShowNewProjectModal(false)}>
        <div className="os-modal" onClick={e => e.stopPropagation()}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
            <h2 style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--ink)', margin: 0 }}>New Project</h2>
            <button onClick={() => setShowNewProjectModal(false)} className="os-btn os-btn-ghost os-btn-xs" style={{ padding: 5 }}>
              <X size={14} />
            </button>
          </div>

          <form onSubmit={handleCreateProject} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              <label style={{ fontSize: '0.8125rem', fontWeight: 500, color: 'var(--muted)' }}>Project Name</label>
              <input
                type="text"
                required
                placeholder="e.g. My Podcast, Tech Reviews"
                value={newProjectName}
                onChange={e => setNewProjectName(e.target.value)}
                className="os-input"
                autoFocus
              />
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              <label style={{ fontSize: '0.8125rem', fontWeight: 500, color: 'var(--muted)' }}>Content Type</label>
              <select
                value={newProjectContentType}
                onChange={e => setNewProjectContentType(e.target.value)}
                className="os-input os-select"
              >
                <option value="general">General</option>
                <option value="sports">Sports</option>
                <option value="podcast">Podcast</option>
                <option value="lecture">Lecture / Tutorial</option>
                <option value="gaming">Gaming</option>
                <option value="interview">Interview</option>
                <option value="comedy">Comedy</option>
              </select>
              <span style={{ fontSize: '0.75rem', color: 'var(--subtle)' }}>Guides Gemini's clip detection vocabulary for this content.</span>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              <label style={{ fontSize: '0.8125rem', fontWeight: 500, color: 'var(--muted)' }}>Retention Period</label>
              <select
                value={retentionDays}
                onChange={e => setRetentionDays(Number(e.target.value))}
                className="os-input os-select"
              >
                {[1, 3, 7, 14, 30].map(d => <option key={d} value={d}>{d} {d === 1 ? 'day' : 'days'}</option>)}
              </select>
              <span style={{ fontSize: '0.75rem', color: 'var(--subtle)' }}>Videos and clips are automatically deleted after this duration.</span>
            </div>

            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '0.75rem', background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 6,
            }}>
              <div>
                <div style={{ fontSize: '0.875rem', fontWeight: 500, color: 'var(--ink)' }}>Visual Dossier</div>
                <div style={{ fontSize: '0.75rem', color: 'var(--subtle)', marginTop: 2 }}>Generate a visual analysis of events &amp; people with Gemini.</div>
              </div>
              <button
                type="button"
                className="os-toggle"
                role="switch"
                aria-checked={dossierEnabled}
                onClick={() => setDossierEnabled(!dossierEnabled)}
              />
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              <label style={{ fontSize: '0.8125rem', fontWeight: 500, color: 'var(--muted)' }}>
                Standing Instructions <span style={{ color: 'var(--subtle)', fontWeight: 400 }}>(optional)</span>
              </label>
              <textarea
                rows={3}
                placeholder={`e.g. "Always include the coach's reaction. Prioritise dunks. Minimum 20s clips."`}
                value={newProjectInstructions}
                onChange={e => setNewProjectInstructions(e.target.value)}
                className="os-input os-textarea"
              />
              <span style={{ fontSize: '0.75rem', color: 'var(--subtle)' }}>Automatically appended to every clip job in this project.</span>
            </div>

            <div style={{ display: 'flex', gap: 8, paddingTop: 4, borderTop: '1px solid var(--border)' }}>
              <button
                type="button"
                onClick={() => setShowNewProjectModal(false)}
                className="os-btn os-btn-secondary"
                style={{ flex: 1 }}
              >
                Cancel
              </button>
              <button type="submit" className="os-btn os-btn-primary" style={{ flex: 1 }}>
                Create
              </button>
            </div>
          </form>
        </div>
      </div>
    )}
  </div>
);

/* ─── Key Modal ─────────────────────────────────────────────────────── */
const KeyModal = ({ show, onClose, apiKey, setApiKey, uploadPostKey, goToSettings }) => {
  if (!show) return null;
  return (
    <div className="os-modal-backdrop" onClick={onClose}>
      <div className="os-modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 440 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem' }}>
          <h2 style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--ink)', margin: 0 }}>
            {!apiKey ? 'API key required' : 'Gemini API Key'}
          </h2>
          <button onClick={onClose} className="os-btn os-btn-ghost os-btn-xs" style={{ padding: 5 }}>
            <X size={14} />
          </button>
        </div>

        <p style={{ fontSize: '0.8125rem', color: 'var(--muted)', marginBottom: '1rem', lineHeight: 1.5 }}>
          OpenShorts needs a <strong style={{ color: 'var(--ink)' }}>Gemini</strong> API key for clip detection and dossier generation.
        </p>

        {/* Gemini */}
        <div className="os-panel" style={{
          padding: '0.875rem', marginBottom: '0.75rem',
          ...(apiKey ? {} : { borderColor: 'oklch(0.55 0.095 170 / 0.35)', background: 'oklch(0.55 0.095 170 / 0.05)' })
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.8125rem', fontWeight: 500, color: 'var(--ink)', marginBottom: apiKey ? 0 : 10 }}>
            {apiKey ? <Check size={13} style={{ color: 'var(--success)' }} /> : <AlertTriangle size={13} style={{ color: 'var(--warning)' }} />}
            Gemini API Key {apiKey && <span style={{ color: 'var(--success)', fontWeight: 400 }}>— set</span>}
          </div>
          {!apiKey && (
            <input
              type="text"
              placeholder="Paste your Gemini API key…"
              className="os-input"
              style={{ marginTop: 2 }}
              onKeyDown={e => { if (e.key === 'Enter' && e.target.value.trim()) setApiKey(e.target.value.trim()); }}
            />
          )}
        </div>

        {/* Upload-Post */}
        <div className="os-panel" style={{ padding: '0.875rem', opacity: 0.7, marginBottom: '1rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.8125rem', fontWeight: 500, color: 'var(--ink)' }}>
            {uploadPostKey ? <Check size={13} style={{ color: 'var(--success)' }} /> : <span style={{ width: 13, height: 13, borderRadius: '50%', background: 'var(--subtle)', display: 'inline-block' }} />}
            Upload-Post Key
            <span style={{ fontSize: '0.75rem', color: 'var(--subtle)', fontWeight: 400 }}>(optional — auto-posting)</span>
            {uploadPostKey && <span style={{ color: 'var(--success)', fontWeight: 400 }}>— set</span>}
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={onClose} className="os-btn os-btn-secondary" style={{ flex: 1 }}>Cancel</button>
          <button onClick={() => { onClose(); goToSettings(); }} className="os-btn os-btn-primary" style={{ flex: 1 }}>Go to Settings</button>
        </div>
      </div>
    </div>
  );
};

/* ─── App ────────────────────────────────────────────────────────────── */
function App() {
  const [apiKey, setApiKey] = useState(localStorage.getItem('gemini_key') || '');
  const [uploadPostKey, setUploadPostKey] = useState(() => { const s = localStorage.getItem('uploadPostKey_v3'); return s ? decrypt(s) : ''; });
  const [elevenLabsKey, setElevenLabsKey] = useState(() => { const s = localStorage.getItem('elevenLabsKey_v1'); return s ? decrypt(s) : ''; });
  const [falKey, setFalKey] = useState(() => { const s = localStorage.getItem('falKey_v1'); return s ? decrypt(s) : ''; });
  const [uploadUserId, setUploadUserId] = useState(() => localStorage.getItem('uploadUserId') || '');
  const [userProfiles, setUserProfiles] = useState([]);
  const [showKeyModal, setShowKeyModal] = useState(false);
  const [jobId, setJobId] = useState(null);
  const [status, setStatus] = useState('idle');
  const [results, setResults] = useState(null);
  const [_logs, setLogs] = useState([]);
  const [processingMedia, setProcessingMedia] = useState(null);
  const [activeTab, setActiveTab] = useState('dashboard');

  const [projects, setProjects] = useState([]);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [currentProject, setCurrentProject] = useState(null);
  const [showNewProjectModal, setShowNewProjectModal] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [dossierEnabled, setDossierEnabled] = useState(false);
  const [retentionDays, setRetentionDays] = useState(7);
  const [newProjectContentType, setNewProjectContentType] = useState('general');
  const [newProjectInstructions, setNewProjectInstructions] = useState('');
  const [sessionRecovered, setSessionRecovered] = useState(false);
  const [showScheduleWeek, setShowScheduleWeek] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => window.innerWidth < 768);

  // Holds the saved project id from a previous session so we can restore it
  // once projects load, without relying on localStorage after effects run.
  const savedProjectIdRef = useRef(null);

  const [_syncedTime, setSyncedTime] = useState(0);
  const [_isSyncedPlaying, setIsSyncedPlaying] = useState(false);
  const [_syncTrigger, setSyncTrigger] = useState(0);

  // Responsive sidebar collapse
  useEffect(() => {
    const onResize = () => setSidebarCollapsed(window.innerWidth < 768);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  const fetchProjects = async () => {
    setProjectsLoading(true);
    try {
      const res = await fetch(getApiUrl('/api/projects'));
      if (res.ok) { const d = await res.json(); setProjects(d.projects || []); }
    } catch { /* ignore network errors */ }
    finally { setProjectsLoading(false); }
  };

  // Snapshot the saved project id at mount, before any effect can wipe it.
  useEffect(() => {
    savedProjectIdRef.current = localStorage.getItem(PROJECT_KEY) || null;
  }, []);

  // Restore the last open project once projects load (refresh persistence).
  // Uses the mount-time snapshot and clears it so back button/sidebar clicks stay on project list.
  useEffect(() => {
    if (projects.length === 0 || currentProject) return;
    const savedId = savedProjectIdRef.current;
    if (!savedId) return;
    savedProjectIdRef.current = null;
    const saved = projects.find(p => p.id === savedId);
    if (saved) setCurrentProject(saved);
  }, [projects, currentProject]);

  // Persist the currently open project (clears storage and ref when currentProject is null)
  useEffect(() => {
    if (currentProject?.id) {
      localStorage.setItem(PROJECT_KEY, currentProject.id);
    } else {
      localStorage.removeItem(PROJECT_KEY);
      savedProjectIdRef.current = null;
    }
  }, [currentProject]);

  useEffect(() => { fetchProjects(); }, []);

  const handleCreateProject = async (e) => {
    e.preventDefault();
    if (!newProjectName.trim()) return;
    try {
      const res = await fetch(getApiUrl('/api/projects'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newProjectName, dossier_enabled: dossierEnabled,
          retention_days: retentionDays, content_type: newProjectContentType,
          custom_instructions: newProjectInstructions.trim() || null
        })
      });
      if (res.ok) {
        const p = await res.json();
        setProjects(prev => [p, ...prev]);
        setNewProjectName(''); setDossierEnabled(false); setRetentionDays(7);
        setNewProjectContentType('general'); setNewProjectInstructions('');
        setShowNewProjectModal(false);
      }
    } catch { /* ignore network errors */ }
  };

  const handleDeleteProject = async (projectId, e) => {
    e.stopPropagation();
    if (!confirm('Delete this project and all its videos and clips? This is irreversible.')) return;
    try {
      const res = await fetch(getApiUrl(`/api/projects/${projectId}`), { method: 'DELETE' });
      if (res.ok) {
        setProjects(prev => prev.filter(p => p.id !== projectId));
        if (currentProject?.id === projectId) {
          localStorage.removeItem(PROJECT_KEY);
          setCurrentProject(null);
        }
      }
    } catch { /* ignore network errors */ }
  };

  // Session recovery
  useEffect(() => {
    try {
      const saved = localStorage.getItem(SESSION_KEY);
      if (!saved) return;
      const session = JSON.parse(saved);
      if (Date.now() - session.timestamp > SESSION_MAX_AGE) { localStorage.removeItem(SESSION_KEY); return; }
      if (session.jobId && session.status && session.status !== 'idle') {
        setJobId(session.jobId); setResults(session.results || null);
        if (session.processingMedia) setProcessingMedia(session.processingMedia);
        if (session.activeTab) setActiveTab(session.activeTab);
        setStatus(session.status === 'processing' ? 'processing' : session.status);
        setSessionRecovered(true);
        setTimeout(() => setSessionRecovered(false), 5000);
      }
    } catch { localStorage.removeItem(SESSION_KEY); }
  }, []);

  useEffect(() => {
    if (status === 'idle') { localStorage.removeItem(SESSION_KEY); return; }
    try {
      localStorage.setItem(SESSION_KEY, JSON.stringify({
        jobId, status, results,
        processingMedia: processingMedia?.type === 'url' ? processingMedia : null,
        activeTab, timestamp: Date.now()
      }));
    } catch { /* persist best-effort */ }
  }, [jobId, status, results, activeTab, processingMedia]);

  useEffect(() => { if (apiKey) localStorage.setItem('gemini_key', apiKey); }, [apiKey]);
  useEffect(() => { if (uploadPostKey) localStorage.setItem('uploadPostKey_v3', encrypt(uploadPostKey)); if (uploadUserId) localStorage.setItem('uploadUserId', uploadUserId); }, [uploadPostKey, uploadUserId]);
  useEffect(() => { if (elevenLabsKey) localStorage.setItem('elevenLabsKey_v1', encrypt(elevenLabsKey)); }, [elevenLabsKey]);
  useEffect(() => { if (falKey) localStorage.setItem('falKey_v1', encrypt(falKey)); }, [falKey]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (uploadPostKey && userProfiles.length === 0) fetchUserProfiles(); }, [uploadPostKey]);

  useEffect(() => {
    let interval;
    if ((status === 'processing' || status === 'completed') && jobId) {
      interval = setInterval(async () => {
        try {
          const data = await pollJob(jobId);
          if (data.result) setResults(data.result);
          if (data.status === 'completed') { setStatus('complete'); clearInterval(interval); }
          else if (data.status === 'failed') {
            setStatus('error');
            const errMsg = data.error || (data.logs?.length > 0 ? data.logs[data.logs.length - 1] : 'Process failed');
            setLogs(prev => [...prev, 'Error: ' + errMsg]);
            clearInterval(interval);
          } else { if (data.logs) setLogs(data.logs); }
        } catch { /* ignore poll errors */ }
      }, 2000);
    }
    return () => clearInterval(interval);
  }, [status, jobId]);

  const fetchUserProfiles = async () => {
    if (!uploadPostKey) return;
    try {
      const res = await fetch(getApiUrl('/api/social/user'), { headers: { 'X-Upload-Post-Key': uploadPostKey } });
      if (!res.ok) throw new Error('Failed');
      const data = await res.json();
      if (data.profiles?.length > 0) {
        setUserProfiles(data.profiles);
        if (!uploadUserId) setUploadUserId(data.profiles[0].username);
      } else { alert('No profiles found for this API Key.'); }
    } catch { alert('Error fetching User Profiles. Please check key.'); }
  };

  const handleReset = () => {
    setStatus('idle'); setJobId(null); setResults(null); setLogs([]); setProcessingMedia(null);
    localStorage.removeItem(SESSION_KEY);
  };

  const handleClipPlay = (startTime) => { setSyncedTime(startTime); setIsSyncedPlaying(true); setSyncTrigger(p => p + 1); };
  const handleClipPause = () => setIsSyncedPlaying(false);

  return (
    <div style={{
      display: 'flex', height: '100vh', background: 'var(--bg)',
      overflow: 'hidden', fontFamily: 'var(--font-sans)',
    }}>
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        setCurrentProject={setCurrentProject}
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed(c => !c)}
      />

      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden', minWidth: 0 }}>
        <Header
          activeTab={activeTab}
          status={status}
          handleReset={handleReset}
          apiKey={apiKey}
          setActiveTab={setActiveTab}
          userProfiles={userProfiles}
          uploadUserId={uploadUserId}
          setUploadUserId={setUploadUserId}
          sessionRecovered={sessionRecovered}
          setSessionRecovered={setSessionRecovered}
          onToggleSidebar={() => setSidebarCollapsed(c => !c)}
        />

        {/* Workspace */}
        <div style={{ flex: 1, overflow: 'hidden', position: 'relative' }}>

          {/* Settings */}
          {activeTab === 'settings' && (
            <SettingsView
              apiKey={apiKey} setApiKey={setApiKey}
              uploadPostKey={uploadPostKey} setUploadPostKey={setUploadPostKey}
              fetchUserProfiles={fetchUserProfiles}
              elevenLabsKey={elevenLabsKey} setElevenLabsKey={setElevenLabsKey}
              falKey={falKey} setFalKey={setFalKey}
            />
          )}

          {/* AI Shorts */}
          {activeTab === 'saasshorts' && (
            <SaaShortsTab
              geminiApiKey={apiKey} elevenLabsKey={elevenLabsKey}
              falKey={falKey} uploadPostKey={uploadPostKey} uploadUserId={uploadUserId}
            />
          )}

          {/* AI Agent */}
          {activeTab === 'ai-agent' && <AIAgentView />}

          {/* UGC Gallery */}
          {activeTab === 'ugc-gallery' && <UGCGallery />}

          {/* YouTube Studio */}
          {activeTab === 'thumbnails' && (
            <ThumbnailStudio
              geminiApiKey={apiKey} uploadPostKey={uploadPostKey} uploadUserId={uploadUserId}
              onGoToSettings={() => setActiveTab('settings')}
            />
          )}

          {/* Projects */}
          {activeTab === 'dashboard' && (
            currentProject ? (
              <ProjectDetail
                project={currentProject}
                onBack={() => { savedProjectIdRef.current = null; localStorage.removeItem(PROJECT_KEY); setCurrentProject(null); fetchProjects(); }}
                geminiApiKey={apiKey}
                uploadPostKey={uploadPostKey}
                uploadUserId={uploadUserId}
                elevenLabsKey={elevenLabsKey}
                onPlayClip={handleClipPlay}
                onPauseClip={handleClipPause}
                onProjectUpdated={(updated) => setCurrentProject(updated)}
              />
            ) : (
              <ProjectsView
                projects={projects}
                projectsLoading={projectsLoading}
                setCurrentProject={setCurrentProject}
                showNewProjectModal={showNewProjectModal}
                setShowNewProjectModal={setShowNewProjectModal}
                handleCreateProject={handleCreateProject}
                newProjectName={newProjectName}
                setNewProjectName={setNewProjectName}
                dossierEnabled={dossierEnabled}
                setDossierEnabled={setDossierEnabled}
                retentionDays={retentionDays}
                setRetentionDays={setRetentionDays}
                newProjectContentType={newProjectContentType}
                setNewProjectContentType={setNewProjectContentType}
                newProjectInstructions={newProjectInstructions}
                setNewProjectInstructions={setNewProjectInstructions}
                handleDeleteProject={handleDeleteProject}
              />
            )
          )}
        </div>
      </main>

      {/* Modals */}
      <KeyModal
        show={showKeyModal}
        onClose={() => setShowKeyModal(false)}
        apiKey={apiKey}
        setApiKey={setApiKey}
        uploadPostKey={uploadPostKey}
        setUploadPostKey={setUploadPostKey}
        goToSettings={() => setActiveTab('settings')}
      />

      <ScheduleWeekModal
        isOpen={showScheduleWeek}
        onClose={() => setShowScheduleWeek(false)}
        clips={results?.clips || []}
        jobId={jobId}
        uploadPostKey={uploadPostKey}
        uploadUserId={uploadUserId}
      />
    </div>
  );
}

export default App;
