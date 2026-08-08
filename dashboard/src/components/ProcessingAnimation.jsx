import React, { useEffect, useState, useRef } from 'react';
import { Scan, Scissors, Activity, Radio, CheckCircle } from 'lucide-react';

const ProcessingAnimation = ({ media, isComplete, syncedTime, isSyncedPlaying, syncTrigger }) => {
  const [videoSrc, setVideoSrc] = useState(null);
  const [isYouTube, setIsYouTube] = useState(false);
  const videoRef = useRef(null);
  const iframeRef = useRef(null);

  useEffect(() => {
    if (!media) return;

    if (media.type === 'file') {
      const url = URL.createObjectURL(media.payload);
      setVideoSrc(url);
      return () => URL.revokeObjectURL(url);
    } else if (media.type === 'url') {
      setIsYouTube(true);
      const videoId = getYouTubeId(media.payload);
      setVideoSrc(videoId);
    }
  }, [media]);

  // Handle Sync Playback for Local Video
  useEffect(() => {
    if (!isYouTube && videoRef.current) {
      if (isSyncedPlaying) {
        videoRef.current.currentTime = syncedTime;
        videoRef.current.play().catch(e => console.log("Auto-play prevented", e));
        videoRef.current.loop = false;
        videoRef.current.muted = true;
      } else {
        videoRef.current.pause();
        if (isComplete) {
          videoRef.current.loop = true;
          videoRef.current.play().catch(e => console.log("Ambient play prevented", e));
        }
      }
    }
  }, [syncedTime, isSyncedPlaying, isYouTube, isComplete, syncTrigger]);

  // Handle Sync Playback for YouTube (Basic Iframe Control via PostMessage)
  useEffect(() => {
    if (isYouTube && iframeRef.current && videoSrc) {
        const iframeWindow = iframeRef.current.contentWindow;
        if (isSyncedPlaying) {
          iframeWindow.postMessage(JSON.stringify({ event: 'command', func: 'seekTo', args: [syncedTime, true] }), '*');
          iframeWindow.postMessage(JSON.stringify({ event: 'command', func: 'playVideo', args: [] }), '*');
        } else {
          iframeWindow.postMessage(JSON.stringify({ event: 'command', func: 'pauseVideo', args: [] }), '*');
        }
    }
  }, [syncedTime, isSyncedPlaying, isYouTube, videoSrc, syncTrigger]);

  const getYouTubeId = (url) => {
    const regExp = /^.*(youtu.be\/|v\/|u\/\w\/|embed\/|watch\?v=|&v=)([^#&?]*).*/;
    const match = url.match(regExp);
    return (match && match[2].length === 11) ? match[2] : null;
  };

  const containerClasses = {
    position: 'relative',
    width: '100%',
    aspectRatio: '16 / 9',
    borderRadius: 12,
    overflow: 'hidden',
    background: 'oklch(0 0 0)',
    border: isSyncedPlaying ? '1px solid var(--primary)' : '1px solid var(--border)',
    boxShadow: isSyncedPlaying ? '0 0 0 3px oklch(0.55 0.095 170 / 0.25), 0 24px 48px oklch(0 0 0 / 0.5)' : '0 24px 48px oklch(0 0 0 / 0.5)',
    marginBottom: '2rem',
    animation: 'os-fade-in 0.5s var(--ease-out-quart) both',
    transition: 'filter 500ms var(--ease-out-quart), opacity 500ms var(--ease-out-quart), border-color 500ms var(--ease-out-quart)',
    filter: isComplete && !isSyncedPlaying ? 'grayscale(1) brightness(0.5)' : 'none',
  };

  const getVideoOpacityStyle = () => {
    if (isSyncedPlaying) return { opacity: 1 };
    if (isComplete) return { opacity: 0.3 };
    return { opacity: 0.4, filter: 'grayscale(1)' };
  };

  return (
    <div style={containerClasses}>
      {/* Video Layer */}
      <div style={{ position: 'absolute', inset: 0, transition: 'all 700ms var(--ease-out-quart)', ...getVideoOpacityStyle() }}>
        {isYouTube && videoSrc ? (
            <iframe
            ref={iframeRef}
            style={{ width: '100%', height: '100%', pointerEvents: isSyncedPlaying ? 'auto' : 'none', transform: isSyncedPlaying ? 'none' : 'scale(1.1)' }}
            src={`https://www.youtube.com/embed/${videoSrc}?autoplay=1&mute=1&controls=0&loop=1&playlist=${videoSrc}&modestbranding=1&showinfo=0&rel=0&enablejsapi=1`}
            title="Processing Video"
            frameBorder="0"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          />
        ) : videoSrc ? (
          <video
            ref={videoRef}
            src={videoSrc}
            style={{ width: '100%', height: '100%', objectFit: 'cover' }}
            autoPlay
            muted
            loop
            playsInline
          />
        ) : (
          <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'oklch(0.16 0.004 170)' }}>
            <div style={{ width: 48, height: 48, border: '4px solid var(--surface-2)', borderTopColor: 'var(--muted)', borderRadius: '50%', animation: 'dot-pulse 1s linear infinite' }} />
          </div>
        )}
      </div>

      {/* Overlays - Hide when synced playing so user sees clean video */}
      {!isSyncedPlaying && !isComplete && (
        <>
            <div style={{ position: 'absolute', inset: 0, backgroundImage: 'linear-gradient(oklch(0.75 0 0 / 0.04) 1px, transparent 1px), linear-gradient(90deg, oklch(0.75 0 0 / 0.04) 1px, transparent 1px)', backgroundSize: '40px 40px', zIndex: 10, pointerEvents: 'none' }} />
            <div style={{ position: 'absolute', left: 0, right: 0, height: 2, background: 'var(--primary)', boxShadow: '0 0 15px 2px oklch(0.55 0.095 170 / 0.5)', animation: 'os-scan 2.5s linear infinite', zIndex: 20, pointerEvents: 'none' }} />
            <div style={{ position: 'absolute', left: 0, right: 0, height: '15%', background: 'linear-gradient(to bottom, transparent, oklch(0.55 0.095 170 / 0.05), transparent)', animation: 'os-scan 2.5s linear infinite', zIndex: 10, pointerEvents: 'none' }} />
        </>
      )}

      {/* HUD Elements - Hide when synced playing */}
      {!isSyncedPlaying && (
        <div style={{
          position: 'absolute',
          top: 16,
          left: 16,
          zIndex: 30,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '6px 12px',
          backdropFilter: 'blur(12px)',
          borderRadius: 8,
          border: isComplete ? '1px solid oklch(0.65 0.14 155 / 0.25)' : '1px solid oklch(0.55 0.095 170 / 0.3)',
          background: isComplete ? 'oklch(0.65 0.14 155 / 0.10)' : 'oklch(0 0 0 / 0.6)',
          fontSize: '0.75rem',
          fontFamily: 'var(--font-mono)',
          fontWeight: 700,
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
          transition: 'all 500ms var(--ease-out-quart)',
          color: isComplete ? 'var(--success)' : 'var(--primary)',
          animation: isComplete ? 'none' : 'dot-pulse 1.8s ease-in-out infinite',
        }}>
          {isComplete ? (
              <>
                  <CheckCircle size={14} /> Analysis Complete
              </>
          ) : (
              <>
                  <Scan size={14} /> Scanning Content...
              </>
          )}
        </div>
      )}

      {!isSyncedPlaying && !isComplete && (
        <div style={{ position: 'absolute', top: 16, right: 16, zIndex: 30, display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px', background: 'oklch(0 0 0 / 0.6)', backdropFilter: 'blur(12px)', borderRadius: 8, border: '1px solid var(--border)', fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--subtle)' }}>
          AI_MODEL: GEMINI-2.5-PRO
        </div>
      )}

      {/* Visual Flair */}
      {!isSyncedPlaying && !isComplete && (
        <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 20, overflow: 'hidden' }}>
          <div style={{ position: 'absolute', top: 0, bottom: 0, left: '35%', width: 1, background: 'oklch(0.75 0.14 65 / 0.2)', borderRight: '1px dashed oklch(0.75 0.14 65 / 0.4)' }} />
          <div style={{ position: 'absolute', top: 0, bottom: 0, right: '35%', width: 1, background: 'oklch(0.75 0.14 65 / 0.2)', borderLeft: '1px dashed oklch(0.75 0.14 65 / 0.4)' }} />
          <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', width: 48, height: 48, border: '1px solid oklch(0.75 0 0 / 0.2)', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <div style={{ width: 4, height: 4, background: 'var(--accent)', borderRadius: '50%', animation: 'dot-pulse 1.2s ease-in-out infinite' }} />
          </div>
          <div style={{ position: 'absolute', bottom: '33%', left: '50%', transform: 'translateX(-50%)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 8, opacity: 0.6 }}>
            <Scissors size={24} style={{ color: 'oklch(0.75 0 0 / 0.2)' }} />
          </div>
        </div>
      )}

      {/* Synced Playing Indicator */}
      {isSyncedPlaying && (
        <div style={{ position: 'absolute', top: 16, right: 16, zIndex: 30, display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px', background: 'oklch(0.62 0.18 25 / 0.9)', color: '#fff', borderRadius: 8, boxShadow: '0 8px 24px oklch(0 0 0 / 0.4)', animation: 'dot-pulse 1.8s ease-in-out infinite', fontWeight: 700, fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em', border: '1px solid oklch(0.75 0 0 / 0.2)', backdropFilter: 'blur(12px)' }}>
          <Scissors size={12} /> Live Sync
        </div>
      )}

      {/* Bottom Info Bar */}
      {!isSyncedPlaying && !isComplete && (
        <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, padding: 16, background: 'linear-gradient(to top, oklch(0 0 0 / 0.9), transparent)', zIndex: 30, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', borderTop: '1px solid oklch(0.75 0 0 / 0.05)', fontFamily: 'var(--font-mono)', fontSize: 10 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, color: 'oklch(0.70 0.040 170 / 0.8)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <Activity size={10} style={{ animation: 'dot-pulse 1s ease-in-out infinite' }} /> &gt; ANALYSIS_THREAD_01: ACTIVE
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <Radio size={10} /> &gt; AUDIO_TRANSCRIPT: PROCESSING
            </div>
          </div>
          <div style={{ display: 'flex', gap: 4, alignItems: 'flex-end' }}>
            {[0.4, 0.6, 0.3, 0.8, 0.5].map((o, i) => (
              <div key={i} style={{ width: 4, height: [12, 20, 8, 16, 12][i], background: `oklch(0.55 0.095 170 / ${o})`, animation: 'dot-pulse 0.6s ease-in-out infinite', animationDelay: `${i * 0.1}s` }} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default ProcessingAnimation;