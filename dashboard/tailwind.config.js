/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // CSS var bridge — used sparingly; prefer var(--token) in CSS classes
        'os-bg':       'var(--bg)',
        'os-surface':  'var(--surface)',
        'os-surface2': 'var(--surface-2)',
        'os-border':   'var(--border)',
        'os-border2':  'var(--border-2)',
        'os-ink':      'var(--ink)',
        'os-muted':    'var(--muted)',
        'os-subtle':   'var(--subtle)',
        'os-primary':  'var(--primary)',
        'os-accent':   'var(--accent)',
        'os-error':    'var(--error)',
        'os-warning':  'var(--warning)',
        'os-success':  'var(--success)',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
      },
      borderRadius: {
        'os': '6px',
        'os-lg': '8px',
        'os-xl': '10px',
      },
      transitionTimingFunction: {
        'out-quart': 'cubic-bezier(0.25, 1, 0.5, 1)',
        'out-expo':  'cubic-bezier(0.16, 1, 0.3, 1)',
      },
    },
  },
  plugins: [],
}
