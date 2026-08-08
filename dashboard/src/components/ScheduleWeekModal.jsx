import React, { useState, useMemo } from 'react';
import { Loader2, Calendar, Clock, CheckCircle, AlertCircle, Video, Instagram, Youtube, ChevronLeft, ChevronRight, Globe, ExternalLink } from 'lucide-react';
import { getApiUrl } from '../config';
import ModalShell from './ModalShell';

const DAYS = ['Dom', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb'];
const MONTHS = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'];

const TIMEZONES = [
    { value: 'Pacific/Midway', label: '(GMT-11:00) Midway' },
    { value: 'Pacific/Honolulu', label: '(GMT-10:00) Honolulu' },
    { value: 'America/Anchorage', label: '(GMT-09:00) Alaska' },
    { value: 'America/Los_Angeles', label: '(GMT-08:00) Los Ángeles' },
    { value: 'America/Denver', label: '(GMT-07:00) Denver' },
    { value: 'America/Mexico_City', label: '(GMT-06:00) Ciudad de México' },
    { value: 'America/Chicago', label: '(GMT-06:00) Chicago' },
    { value: 'America/New_York', label: '(GMT-05:00) Nueva York' },
    { value: 'America/Bogota', label: '(GMT-05:00) Bogotá' },
    { value: 'America/Caracas', label: '(GMT-04:00) Caracas' },
    { value: 'America/Santiago', label: '(GMT-04:00) Santiago' },
    { value: 'America/Argentina/Buenos_Aires', label: '(GMT-03:00) Buenos Aires' },
    { value: 'America/Sao_Paulo', label: '(GMT-03:00) São Paulo' },
    { value: 'Atlantic/Azores', label: '(GMT-01:00) Azores' },
    { value: 'UTC', label: '(GMT+00:00) UTC' },
    { value: 'Europe/London', label: '(GMT+00:00) Londres' },
    { value: 'Europe/Madrid', label: '(GMT+01:00) Madrid' },
    { value: 'Europe/Paris', label: '(GMT+01:00) París' },
    { value: 'Europe/Berlin', label: '(GMT+01:00) Berlín' },
    { value: 'Europe/Rome', label: '(GMT+01:00) Roma' },
    { value: 'Africa/Lagos', label: '(GMT+01:00) Lagos' },
    { value: 'Europe/Istanbul', label: '(GMT+03:00) Estambul' },
    { value: 'Asia/Dubai', label: '(GMT+04:00) Dubái' },
    { value: 'Asia/Kolkata', label: '(GMT+05:30) India' },
    { value: 'Asia/Bangkok', label: '(GMT+07:00) Bangkok' },
    { value: 'Asia/Shanghai', label: '(GMT+08:00) Shanghái' },
    { value: 'Asia/Tokyo', label: '(GMT+09:00) Tokio' },
    { value: 'Australia/Sydney', label: '(GMT+10:00) Sídney' },
    { value: 'Pacific/Auckland', label: '(GMT+12:00) Auckland' },
];

function getDayLabel(date) {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const tomorrow = new Date(today);
    tomorrow.setDate(tomorrow.getDate() + 1);
    const target = new Date(date);
    target.setHours(0, 0, 0, 0);

    if (target.getTime() === today.getTime()) return 'Hoy';
    if (target.getTime() === tomorrow.getTime()) return 'Mañana';
    return DAYS[target.getDay()];
}

function formatDate(date) {
    return `${date.getDate()} ${MONTHS[date.getMonth()]}`;
}

function detectTimezone() {
    try {
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        if (TIMEZONES.find(t => t.value === tz)) return tz;
        return 'UTC';
    } catch {
        return 'UTC';
    }
}

const FIELD_LABEL = {
    fontSize: '0.75rem', fontWeight: 500, color: 'var(--muted)',
    display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6,
};

export default function ScheduleWeekModal({ isOpen, onClose, clips, jobId, uploadPostKey, uploadUserId }) {
    const [time, setTime] = useState('12:00');
    const [timezone, setTimezone] = useState(detectTimezone);
    const [platforms, setPlatforms] = useState({ tiktok: true, instagram: true, youtube: true });
    const [startOffset, setStartOffset] = useState(1);

    const schedule = useMemo(() => {
        if (!clips) return [];
        return clips.map((clip, i) => {
            const date = new Date();
            date.setDate(date.getDate() + startOffset + i);
            date.setHours(0, 0, 0, 0);
            return { clip, index: i, date };
        });
    }, [clips, startOffset]);

    const [scheduling, setScheduling] = useState(false);
    const [progress, setProgress] = useState({ current: 0, total: 0, results: [] });
    const [done, setDone] = useState(false);

    const prevOpen = React.useRef(false);
    React.useEffect(() => {
        if (isOpen && !prevOpen.current) {
            setScheduling(false);
            setDone(false);
            setProgress({ current: 0, total: 0, results: [] });
        }
        prevOpen.current = isOpen;
    }, [isOpen]);

    if (!isOpen) return null;

    const selectedPlatforms = Object.keys(platforms).filter(k => platforms[k]);

    const handleScheduleAll = async () => {
        if (!uploadPostKey || !uploadUserId) return;
        if (selectedPlatforms.length === 0) return;

        setScheduling(true);
        setDone(false);
        const total = schedule.length;
        setProgress({ current: 0, total, results: [] });

        const results = [];
        for (let i = 0; i < schedule.length; i++) {
            const { clip, index, date } = schedule[i];

            const pad = (n) => String(n).padStart(2, '0');
            const scheduledDate = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${time}:00`;

            const payload = {
                job_id: jobId,
                clip_index: index,
                api_key: uploadPostKey,
                user_id: uploadUserId,
                platforms: selectedPlatforms,
                title: clip.video_title_for_youtube_short || 'Viral Short',
                description: clip.video_description_for_instagram || clip.video_description_for_tiktok || '',
                scheduled_date: scheduledDate,
                timezone
            };

            try {
                const res = await fetch(getApiUrl('/api/social/post'), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                if (!res.ok) {
                    const errText = await res.text();
                    throw new Error(errText);
                }

                results.push({ index: i, success: true });
            } catch (e) {
                results.push({ index: i, success: false, error: e.message });
            }

            setProgress({ current: i + 1, total, results: [...results] });
        }

        setDone(true);
        setScheduling(false);
    };

    const successCount = progress.results.filter(r => r.success).length;
    const failCount = progress.results.filter(r => !r.success).length;

    const platformBtn = ({ key, label, icon: Icon, active, onToggle }) => (
        <button
            key={key}
            type="button"
            onClick={onToggle}
            disabled={scheduling}
            aria-pressed={active}
            className="os-btn os-btn-sm"
            style={{
                flex: 1, justifyContent: 'center', gap: 6,
                background: active ? 'oklch(0.55 0.095 170 / 0.1)' : 'transparent',
                borderColor: active ? 'oklch(0.55 0.095 170 / 0.4)' : 'var(--border)',
                color: active ? 'var(--primary)' : 'var(--muted)',
            }}
        >
            <Icon size={13} /> {label}
        </button>
    );

    return (
        <ModalShell
            isOpen={isOpen}
            onClose={onClose}
            title="Programar Semana"
            subtitle={`${clips?.length || 0} clips · 1 por día`}
            icon={<Calendar size={14} style={{ color: 'var(--primary)', flexShrink: 0 }} />}
            maxWidth={480}
        >
            {!uploadPostKey && (
                <div className="os-chip os-chip-warning" style={{ display: 'flex', alignItems: 'flex-start', gap: 6, marginBottom: '0.875rem', padding: '0.5rem 0.625rem', whiteSpace: 'normal', lineHeight: 1.5 }}>
                    <AlertCircle size={13} className="shrink-0" style={{ marginTop: 1 }} />
                    <span>Configura tu API Key de Upload-Post en Settings primero.</span>
                </div>
            )}

            {/* Time + Timezone */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: '0.875rem' }}>
                <div>
                    <label style={FIELD_LABEL}><Clock size={13} /> Hora</label>
                    <input
                        type="time"
                        value={time}
                        onChange={(e) => setTime(e.target.value)}
                        disabled={scheduling}
                        className="os-input"
                        style={{ colorScheme: 'dark' }}
                    />
                </div>
                <div>
                    <label style={FIELD_LABEL}><Globe size={13} /> Zona horaria</label>
                    <select
                        value={timezone}
                        onChange={(e) => setTimezone(e.target.value)}
                        disabled={scheduling}
                        className="os-input os-select"
                    >
                        {TIMEZONES.map(tz => (
                            <option key={tz.value} value={tz.value}>{tz.label}</option>
                        ))}
                    </select>
                </div>
            </div>

            {/* Start day offset */}
            <div className="os-panel-2" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0.5rem 0.75rem', marginBottom: '0.875rem' }}>
                <span style={{ fontSize: '0.75rem', fontWeight: 500, color: 'var(--muted)' }}>Empezar desde</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <button
                        onClick={() => setStartOffset(Math.max(1, startOffset - 1))}
                        disabled={startOffset <= 1 || scheduling}
                        className="os-btn os-btn-ghost os-btn-xs"
                        style={{ padding: 5 }}
                        aria-label="Previous day"
                    >
                        <ChevronLeft size={15} />
                    </button>
                    <span style={{ fontSize: '0.8125rem', fontWeight: 500, color: 'var(--ink)', minWidth: 90, textAlign: 'center' }}>
                        {(() => {
                            const d = new Date();
                            d.setDate(d.getDate() + startOffset);
                            return `${getDayLabel(d)} ${formatDate(d)}`;
                        })()}
                    </span>
                    <button
                        onClick={() => setStartOffset(startOffset + 1)}
                        disabled={scheduling}
                        className="os-btn os-btn-ghost os-btn-xs"
                        style={{ padding: 5 }}
                        aria-label="Next day"
                    >
                        <ChevronRight size={15} />
                    </button>
                </div>
            </div>

            {/* Calendar grid */}
            <div className="os-scroll" style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 240, overflowY: 'auto', marginBottom: '0.875rem', paddingRight: 2 }}>
                {schedule.map(({ clip, index, date }) => (
                    <div key={index} className="os-panel-2" style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '0.625rem 0.75rem', background: 'var(--surface)' }}>
                        <div style={{ width: 52, flexShrink: 0, textAlign: 'center' }}>
                            <div style={{ fontSize: '0.625rem', fontWeight: 700, color: 'var(--primary)', textTransform: 'uppercase' }}>{getDayLabel(date)}</div>
                            <div style={{ fontSize: '1.125rem', fontWeight: 700, color: 'var(--ink)', lineHeight: 1.2 }}>{date.getDate()}</div>
                            <div style={{ fontSize: '0.625rem', color: 'var(--subtle)' }}>{MONTHS[date.getMonth()]}</div>
                        </div>

                        <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--ink)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                Clip {index + 1}
                            </div>
                            <div style={{ fontSize: '0.6875rem', color: 'var(--subtle)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                {clip.title || clip.video_title_for_youtube_short || 'Viral Short'}
                            </div>
                            <div style={{ fontSize: '0.6875rem', color: 'var(--subtle)', marginTop: 2 }}>
                                {time}h · {TIMEZONES.find(t => t.value === timezone)?.label || timezone}
                            </div>
                        </div>

                        <div style={{ flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', width: 20 }}>
                            {progress.results[index]?.success === true && <CheckCircle size={17} style={{ color: 'var(--success)' }} />}
                            {progress.results[index]?.success === false && <AlertCircle size={17} style={{ color: 'var(--error)' }} />}
                            {scheduling && progress.current - 1 === index && <Loader2 size={17} className="animate-spin" style={{ color: 'var(--primary)' }} />}
                            {!scheduling && progress.results[index] === undefined && <div style={{ width: 14, height: 14, borderRadius: '50%', border: '2px solid var(--border)' }} />}
                        </div>
                    </div>
                ))}
            </div>

            {/* Platforms */}
            <div style={{ marginBottom: '0.875rem' }}>
                <label style={FIELD_LABEL}>Plataformas</label>
                <div style={{ display: 'flex', gap: 6 }}>
                    {platformBtn({ key: 'tiktok', label: 'TikTok', icon: Video, active: platforms.tiktok, onToggle: () => setPlatforms(p => ({ ...p, tiktok: !p.tiktok })) })}
                    {platformBtn({ key: 'instagram', label: 'Instagram', icon: Instagram, active: platforms.instagram, onToggle: () => setPlatforms(p => ({ ...p, instagram: !p.instagram })) })}
                    {platformBtn({ key: 'youtube', label: 'YouTube', icon: Youtube, active: platforms.youtube, onToggle: () => setPlatforms(p => ({ ...p, youtube: !p.youtube })) })}
                </div>
            </div>

            {/* Progress bar */}
            {(scheduling || done) && (
                <div style={{ marginBottom: '0.875rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.75rem', color: 'var(--muted)', marginBottom: 6 }}>
                        <span>{scheduling ? 'Programando...' : 'Completado'}</span>
                        <span>{progress.current}/{progress.total}</span>
                    </div>
                    <div className="os-progress" style={{ height: 6 }}>
                        <div
                            className="os-progress-bar"
                            style={{
                                width: `${(progress.current / progress.total) * 100}%`,
                                background: done && failCount > 0 ? 'var(--warning)' : done && failCount === 0 ? 'var(--success)' : 'var(--primary)',
                            }}
                        />
                    </div>
                    {done && (
                        <div style={{ marginTop: 8, fontSize: '0.75rem', textAlign: 'center', color: failCount === 0 ? 'var(--success)' : 'var(--warning)', fontWeight: 500 }}>
                            {failCount === 0 ? 'Todos los clips programados correctamente' : `${successCount} programados, ${failCount} fallidos`}
                        </div>
                    )}
                </div>
            )}

            {/* Actions */}
            <div style={{ display: 'flex', gap: 8 }}>
                <button
                    onClick={onClose}
                    disabled={scheduling}
                    className="os-btn os-btn-secondary"
                    style={{ flex: 1 }}
                >
                    {done ? 'Cerrar' : 'Cancelar'}
                </button>
                {!done ? (
                    <button
                        onClick={handleScheduleAll}
                        disabled={scheduling || !uploadPostKey || selectedPlatforms.length === 0}
                        className="os-btn os-btn-primary"
                        style={{ flex: 1, justifyContent: 'center', gap: 6 }}
                    >
                        {scheduling ? (
                            <>
                                <Loader2 size={13} className="animate-spin" />
                                Programando...
                            </>
                        ) : (
                            <>
                                <Calendar size={13} />
                                Programar {clips?.length || 0} Clips
                            </>
                        )}
                    </button>
                ) : (
                    <a
                        href="https://app.upload-post.com/calendar"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="os-btn os-btn-secondary"
                        style={{ flex: 1, justifyContent: 'center', gap: 6, textDecoration: 'none' }}
                    >
                        <ExternalLink size={13} />
                        Ver Calendario
                    </a>
                )}
            </div>
        </ModalShell>
    );
}