/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/renderer/**/*.{ts,tsx,html}'],
  theme: {
    extend: {
      colors: {
        bg: {
          base: '#0a0c0f',
        },
        surface: {
          0: '#0f1215',
          1: '#161b22',
          2: '#1c2330',
          3: '#232d3f',
        },
        border: {
          DEFAULT: '#2a3344',
          subtle: '#1e2738',
          focus: '#3b82f6',
        },
        text: {
          primary: '#e2e8f0',
          secondary: '#94a3b8',
          disabled: '#4a5568',
        },
        brand: {
          DEFAULT: '#3b82f6',
          hover: '#2563eb',
        },
        buy: {
          DEFAULT: '#22c55e',
          hover: '#16a34a',
          subtle: 'rgba(34,197,94,0.12)',
        },
        sell: {
          DEFAULT: '#ef4444',
          hover: '#dc2626',
          subtle: 'rgba(239,68,68,0.12)',
        },
        connected: '#22c55e',
        connecting: '#f59e0b',
        reconnecting: '#f97316',
        disconnected: '#ef4444',
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'Consolas', 'monospace'],
      },
      fontSize: {
        xs: ['0.625rem', { lineHeight: '1rem' }],
        sm: ['0.75rem', { lineHeight: '1.125rem' }],
        base: ['0.875rem', { lineHeight: '1.375rem' }],
        md: ['1rem', { lineHeight: '1.5rem' }],
        lg: ['1.125rem', { lineHeight: '1.75rem' }],
        xl: ['1.375rem', { lineHeight: '2rem' }],
        '2xl': ['1.75rem', { lineHeight: '2.25rem' }],
        '3xl': ['2.25rem', { lineHeight: '2.75rem' }],
      },
      borderRadius: {
        sm: '4px',
        DEFAULT: '6px',
        md: '6px',
        lg: '8px',
        xl: '12px',
      },
      boxShadow: {
        sm: '0 1px 2px rgba(0,0,0,0.4)',
        md: '0 4px 6px rgba(0,0,0,0.5)',
        lg: '0 8px 24px rgba(0,0,0,0.6)',
        xl: '0 16px 48px rgba(0,0,0,0.75)',
        dialog: '0 20px 60px rgba(0,0,0,0.8), 0 0 0 1px rgba(239,68,68,0.3)',
      },
      animation: {
        'slide-in-top': 'slideInTop 200ms ease',
        'fade-in': 'fadeIn 150ms ease',
        'border-pulse': 'borderPulse 500ms ease infinite',
      },
      keyframes: {
        slideInTop: {
          '0%': { transform: 'translateY(-8px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        borderPulse: {
          '0%, 100%': { borderColor: 'rgba(239,68,68,0.4)' },
          '50%': { borderColor: 'rgba(239,68,68,1)' },
        },
      },
    },
  },
  plugins: [],
}
