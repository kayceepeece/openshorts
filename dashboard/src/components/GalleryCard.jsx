import React, { useRef, useState, useEffect } from 'react';
import { Download, Youtube, Instagram, Video, Copy, Check, Play } from 'lucide-react';

export default function GalleryCard({ clip }) {
    const [copied, setCopied] = useState(null);
    const [isVisible, setIsVisible] = useState(false);
    const cardRef = useRef(null);
    const videoRef = useRef(null);

    // Lazy loading with IntersectionObserver
    useEffect(() => {
        const el = cardRef.current;
        if (!el) return;
        const observer = new IntersectionObserver(
            (entries) => {
                entries.forEach((entry) => {
                    if (entry.isIntersecting) {
                        setIsVisible(true);
                        // Once loaded, we don't need to observe anymore
                        observer.unobserve(entry.target);
                    }
                });
            },
            {
                rootMargin: '200px', // Start loading 200px before entering viewport
                threshold: 0.1
            }
        );

        observer.observe(el);

        return () => {
            observer.unobserve(el);
        };
    }, []);

    const handleCopy = (text, field) => {
        navigator.clipboard.writeText(text);
        setCopied(field);
        setTimeout(() => setCopied(null), 2000);
    };

    const handleDownload = async (e) => {
        e.preventDefault();
        try {
            const response = await fetch(clip.url);
            if (!response.ok) throw new Error('Download failed');
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = url;
            a.download = `clip_${clip.job_id}_${clip.index + 1}.mp4`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        } catch (err) {
            console.error('Download error:', err);
            window.open(clip.url, '_blank');
        }
    };

    return (
        <div
            ref={cardRef}
            className="os-panel os-fade-in"
            style={{ padding: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column', transition: 'border-color 300ms var(--ease-out-quart)' }}
        >
            {/* Video Player - Lazy loaded */}
            <div className="aspect-[9/16]" style={{ background: 'oklch(0 0 0)', position: 'relative' }}>
                {isVisible ? (
                    <video
                        ref={videoRef}
                        src={clip.url}
                        controls
                        className="w-full h-full object-cover"
                        playsInline
                        preload="metadata"
                    />
                ) : (
                    <div className="w-full h-full flex items-center justify-center" style={{ background: 'oklch(0.16 0.004 170)' }}>
                        <div className="w-12 h-12 rounded-full flex items-center justify-center" style={{ background: 'oklch(0.75 0 0 / 0.1)' }}>
                            <Play size={24} style={{ color: 'var(--subtle)', marginLeft: 4 }} />
                        </div>
                    </div>
                )}
                <div style={{ position: 'absolute', top: 8, left: 8 }}>
                    <span style={{ background: 'oklch(0 0 0 / 0.6)', backdropFilter: 'blur(12px)', fontSize: 10, fontWeight: 700, padding: '4px 8px', borderRadius: 6, border: '1px solid var(--border)', letterSpacing: '0.05em', color: 'var(--muted)' }}>
                        {new Date(clip.created_at).toLocaleDateString()}
                    </span>
                </div>
            </div>

            {/* Content & Details */}
            <div className="flex-1 p-4 flex flex-col min-w-0" style={{ background: 'var(--surface)' }}>
                <div className="mb-3">
                    <h3 className="text-sm font-bold leading-tight line-clamp-2 mb-2 break-words" style={{ color: 'var(--ink)' }} title={clip.title}>
                        {clip.title}
                    </h3>
                    <div className="flex flex-wrap gap-2 text-[10px]" style={{ fontFamily: 'var(--font-mono)', color: 'var(--subtle)' }}>
                        <span className="os-chip">{clip.duration.toFixed(1)}s</span>
                        <span className="os-chip truncate" style={{ maxWidth: 150 }} title={clip.job_id}>ID: {clip.job_id.substring(0, 8)}</span>
                    </div>
                </div>

                <div className="space-y-2 flex-1 overflow-y-auto os-scroll max-h-[150px] pr-1 mb-3">
                    {/* YouTube Title */}
                    <div style={{ background: 'oklch(0.75 0 0 / 0.03)', borderRadius: 8, padding: 8, border: '1px solid var(--border)', position: 'relative' }} className="group-copy">
                        <div className="flex items-center gap-1.5 text-[10px] font-bold mb-1 uppercase tracking-wider" style={{ color: 'var(--muted)' }}>
                            <Youtube size={10} className="shrink-0" style={{ color: 'var(--accent)' }} /> YouTube Title
                        </div>
                        <p className="text-xs select-all line-clamp-2 hover:line-clamp-none transition-all" style={{ color: 'var(--muted)' }}>{clip.title}</p>
                        <button
                            onClick={() => handleCopy(clip.title, 'yt')}
                            className="absolute p-1 transition-opacity"
                            style={{ top: 8, right: 8, color: 'var(--subtle)', opacity: 0 }}
                            onMouseEnter={e => e.currentTarget.style.opacity = 1}
                            onMouseLeave={e => e.currentTarget.style.opacity = 0}
                            title="Copy Title"
                        >
                            {copied === 'yt' ? <Check size={12} style={{ color: 'var(--success)' }} /> : <Copy size={12} />}
                        </button>
                    </div>

                    {/* TikTok / IG Caption */}
                    <div style={{ background: 'oklch(0.75 0 0 / 0.03)', borderRadius: 8, padding: 8, border: '1px solid var(--border)', position: 'relative' }} className="group-copy">
                        <div className="flex items-center gap-1.5 text-[10px] font-bold mb-1 uppercase tracking-wider" style={{ color: 'var(--muted)' }}>
                            <Video size={10} className="shrink-0" style={{ color: 'var(--primary)' }} />
                            <span style={{ color: 'var(--border)' }}>/</span>
                            <Instagram size={10} className="shrink-0" style={{ color: 'var(--accent)' }} /> Caption
                        </div>
                        <p className="text-xs select-all line-clamp-3 hover:line-clamp-none transition-all cursor-pointer" style={{ color: 'var(--muted)' }}>
                            {clip.tiktok_desc || clip.insta_desc}
                        </p>
                        <button
                            onClick={() => handleCopy(clip.tiktok_desc || clip.insta_desc, 'caption')}
                            className="absolute p-1 transition-opacity"
                            style={{ top: 8, right: 8, color: 'var(--subtle)', opacity: 0 }}
                            onMouseEnter={e => e.currentTarget.style.opacity = 1}
                            onMouseLeave={e => e.currentTarget.style.opacity = 0}
                            title="Copy Caption"
                        >
                            {copied === 'caption' ? <Check size={12} style={{ color: 'var(--success)' }} /> : <Copy size={12} />}
                        </button>
                    </div>
                </div>

                {/* Footer Action */}
                <button
                    onClick={handleDownload}
                    className="os-btn os-btn-secondary os-btn-sm"
                    style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, padding: '0.5rem' }}
                >
                    <Download size={14} className="shrink-0" /> Download Clip
                </button>
            </div>
        </div>
    );
}