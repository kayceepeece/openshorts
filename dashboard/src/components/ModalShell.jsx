import React, { useCallback, useEffect, useRef } from 'react';
import { X } from 'lucide-react';

/**
 * Shared modal shell built on the os-* design system.
 * Handles backdrop, Escape-to-close, focus trap, and dialog semantics.
 */
export default function ModalShell({
    isOpen,
    onClose,
    title,
    icon,
    subtitle,
    maxWidth = 480,
    children,
    showCloseButton = true,
}) {
    const containerRef = useRef(null);
    const previousFocus = useRef(null);

    const handleKeyDown = useCallback((e) => {
        if (e.key === 'Escape') onClose?.();
        if (e.key === 'Tab') {
            const container = containerRef.current;
            if (!container) return;
            const focusables = Array.from(
                container.querySelectorAll(
                    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
                )
            ).filter((el) => !el.hasAttribute('disabled') && el.getAttribute('aria-hidden') !== 'true');
            if (focusables.length === 0) return;
            const first = focusables[0];
            const last = focusables[focusables.length - 1];
            if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        }
    }, [onClose]);

    useEffect(() => {
        if (!isOpen) return;
        previousFocus.current = document.activeElement;
        const container = containerRef.current;
        const focusables = container?.querySelectorAll(
            'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        const first = focusables?.[0];
        // Delay so the modal is in the DOM when we focus it
        requestAnimationFrame(() => first?.focus?.() || container?.focus?.());
        document.addEventListener('keydown', handleKeyDown);
        // Prevent background scroll while open
        const prevOverflow = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        return () => {
            document.removeEventListener('keydown', handleKeyDown);
            document.body.style.overflow = prevOverflow;
            previousFocus.current?.focus?.();
        };
    }, [isOpen, handleKeyDown]);

    if (!open) return null;

    return (
        <div
            className="os-modal-backdrop"
            onClick={onClose}
            role="presentation"
        >
            <div
                className="os-modal"
                role="dialog"
                aria-modal="true"
                aria-label={title || undefined}
                ref={containerRef}
                tabIndex={-1}
                onClick={(e) => e.stopPropagation()}
                style={{ maxWidth }}
            >
                {(title || showCloseButton) && (
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem', gap: 8 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                            {icon}
                            {title && (
                                <h2 style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--ink)', margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                    {title}
                                </h2>
                            )}
                        </div>
                        {showCloseButton && (
                            <button
                                onClick={onClose}
                                className="os-btn os-btn-ghost os-btn-xs"
                                style={{ padding: 5, flexShrink: 0 }}
                                aria-label="Close dialog"
                            >
                                <X size={14} />
                            </button>
                        )}
                    </div>
                )}
                {subtitle && (
                    <p style={{ fontSize: '0.8125rem', color: 'var(--muted)', margin: '0 0 1rem', lineHeight: 1.5 }}>
                        {subtitle}
                    </p>
                )}
                {children}
            </div>
        </div>
    );
}