import React from 'react';

/**
 * Shared segmented control built on the os-* design system.
 * A mutually-exclusive group of buttons (position, size, animation, etc).
 */
export default function Segmented({ options, value, onChange, columns = 2, size = 'sm', label }) {
    const pad = size === 'md' ? '0.5rem' : '0.375rem';
    const fontSize = size === 'md' ? '0.8125rem' : '0.75rem';
    return (
        <div>
            {label && <label style={{ fontSize: '0.75rem', fontWeight: 500, color: 'var(--muted)', display: 'block', marginBottom: 6 }}>{label}</label>}
            <div style={{ display: 'grid', gridTemplateColumns: `repeat(${columns}, 1fr)`, gap: 4 }}>
            {options.map((opt) => {
                const isActive = value === opt.value;
                return (
                    <button
                        key={opt.value}
                        type="button"
                        onClick={() => onChange(opt.value)}
                        aria-pressed={isActive}
                        style={{
                            padding: `${pad} 0.5rem`,
                            borderRadius: 5,
                            fontSize,
                            fontWeight: 500,
                            fontFamily: 'var(--font-sans)',
                            border: `1px solid ${isActive ? 'var(--primary)' : 'var(--border)'}`,
                            background: isActive ? 'oklch(0.55 0.095 170 / 0.10)' : 'transparent',
                            color: isActive ? 'var(--primary)' : 'var(--muted)',
                            cursor: 'pointer',
                            whiteSpace: 'nowrap',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            transition: 'border-color var(--dur-fast), background var(--dur-fast), color var(--dur-fast)',
                        }}
                        onMouseEnter={e => {
                            if (!isActive) {
                                e.currentTarget.style.borderColor = 'var(--border-2)';
                                e.currentTarget.style.color = 'var(--ink)';
                            }
                        }}
                        onMouseLeave={e => {
                            if (!isActive) {
                                e.currentTarget.style.borderColor = 'var(--border)';
                                e.currentTarget.style.color = 'var(--muted)';
                            }
                        }}
                    >
                        {opt.label}
                    </button>
                );
            })}
            </div>
        </div>
    );
}