import React, { useState, useEffect, useRef, useCallback } from 'react';
import { LayoutGrid, AlertCircle, Loader2 } from 'lucide-react';
import { getApiUrl } from '../config';
import GalleryCard from './GalleryCard';

const CLIPS_PER_PAGE = 20;

export default function Gallery() {
    const [clips, setClips] = useState([]);
    const [loading, setLoading] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);
    const [error, setError] = useState(null);
    const [hasMore, setHasMore] = useState(true);
    const [offset, setOffset] = useState(0);

    const loaderRef = useRef(null);

    const fetchClips = useCallback(async (currentOffset = 0, append = false) => {
        try {
            if (currentOffset === 0) setLoading(true);
            else setLoadingMore(true);

            const res = await fetch(
                getApiUrl(`/api/gallery/clips?limit=${CLIPS_PER_PAGE}&offset=${currentOffset}`)
            );
            if (!res.ok) throw new Error('Failed to fetch clips');
            const data = await res.json();

            const newClips = data.clips || [];

            if (append) {
                setClips(prev => [...prev, ...newClips]);
            } else {
                setClips(newClips);
            }

            setHasMore(data.has_more ?? newClips.length === CLIPS_PER_PAGE);
            setOffset(currentOffset + newClips.length);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
            setLoadingMore(false);
        }
    }, []);

    // Initial load
    useEffect(() => {
        fetchClips(0, false);
    }, [fetchClips]);

    // Infinite scroll observer
    useEffect(() => {
        if (!hasMore || loadingMore || loading) return;
        const el = loaderRef.current;
        if (!el) return;

        const observer = new IntersectionObserver(
            (entries) => {
                if (entries[0].isIntersecting && hasMore && !loadingMore) {
                    fetchClips(offset, true);
                }
            },
            { rootMargin: '200px', threshold: 0.1 }
        );

        observer.observe(el);

        return () => {
            observer.unobserve(el);
        };
    }, [hasMore, loadingMore, loading, offset, fetchClips]);

    if (loading) {
        return (
            <div className="h-full flex flex-col items-center justify-center os-fade-in" style={{ color: 'var(--muted)' }}>
                <Loader2 size={32} className="animate-spin" style={{ marginBottom: 16, color: 'var(--primary)' }} />
                <p>Loading your viral history...</p>
            </div>
        );
    }

    if (error) {
        return (
            <div className="h-full flex flex-col items-center justify-center p-6 os-fade-in" style={{ color: 'var(--error)' }}>
                <AlertCircle size={32} className="mb-4" />
                <p>Error loading gallery: {error}</p>
                <button
                    onClick={() => {
                        setError(null);
                        setOffset(0);
                        fetchClips(0, false);
                    }}
                    className="os-btn os-btn-secondary mt-4"
                >
                    Retry
                </button>
            </div>
        );
    }

    return (
        <div className="h-full overflow-y-auto os-scroll p-6 md:p-8 os-fade-in">
            <div className="flex items-center justify-between mb-8">
                <h1 className="text-2xl font-bold flex items-center gap-3" style={{ color: 'var(--ink)' }}>
                    <LayoutGrid style={{ color: 'var(--primary)' }} /> Clip Gallery
                </h1>
                <span className="os-chip" style={{ color: 'var(--ink)' }}>
                    {clips.length} {clips.length === 1 ? 'Clip' : 'Clips'}{hasMore ? '+' : ''}
                </span>
            </div>

            {clips.length === 0 ? (
                <div className="text-center py-20 os-fade-in" style={{ color: 'var(--muted)' }}>
                    <p className="text-lg mb-2" style={{ color: 'var(--ink)' }}>No clips found yet.</p>
                    <p className="text-sm">Process some videos to populate your gallery!</p>
                </div>
            ) : (
                <>
                    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-6 pb-10">
                        {clips.map((clip) => (
                            <GalleryCard key={`${clip.job_id}-${clip.index}`} clip={clip} />
                        ))}
                    </div>

                    {/* Infinite scroll loader trigger */}
                    {hasMore && (
                        <div
                            ref={loaderRef}
                            className="flex justify-center py-8"
                        >
                            {loadingMore && (
                                <div className="flex items-center gap-2" style={{ color: 'var(--muted)' }}>
                                    <Loader2 size={20} className="animate-spin" />
                                    <span className="text-sm">Loading more clips...</span>
                                </div>
                            )}
                        </div>
                    )}
                </>
            )}
        </div>
    );
}