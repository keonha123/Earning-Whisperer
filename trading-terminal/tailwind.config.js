/** @type {import('tailwindcss').Config} */
// 값의 기준은 src/renderer/styles/tokens.css 다. 여기서는 같은 값을 클래스 이름으로 노출한다.
// 예전 이름(surface · accent · buy · sell 등)은 화면 코드가 그대로 쓰도록 남기고 값만 새 토큰으로 바꿨다.
// 화면 이슈(#155~#159)에서 화면을 다시 만들 때 새 이름(ink · gold · up · down · ok · danger)으로 옮긴다.
const rgb = (v) => `rgb(${v} / <alpha-value>)`

module.exports = {
  content: ['./src/renderer/**/*.{ts,tsx,html}'],
  theme: {
    extend: {
      colors: {
        // 바탕 — 단색 #1d1e22. surface 는 바탕 위 불투명 면(목록 · 입력 · 펼침 메뉴)
        bg: {
          base: '#1d1e22',
        },
        surface: {
          0: '#212226',
          1: '#26272b',
          2: '#2d2e33',
          3: '#35363b',
        },

        // 글자 — ink-1 · ink-2(82%) · ink-3(58%) · ink-4(40%)
        ink: {
          1: '#fbfaf6',
          2: 'rgba(251,250,246,0.82)',
          3: 'rgba(251,250,246,0.58)',
          4: 'rgba(251,250,246,0.4)',
        },
        text: {
          primary: '#fbfaf6',
          secondary: 'rgba(251,250,246,0.82)',
          tertiary: 'rgba(251,250,246,0.58)',
          disabled: 'rgba(251,250,246,0.4)',
        },

        // 금 — 금테 · 포커스 · 선택 표시. 예전 accent(에메랄드) 자리를 금이 받는다
        gold: {
          hi: '#fff1c4',
          DEFAULT: '#e2bd62',
          lo: '#8a6420',
        },
        accent: {
          300: '#f3dc9a',
          400: '#ebcd7c',
          500: '#e2bd62',
          600: '#c49a43',
          700: '#a57e2f',
          800: '#8a6420',
          900: '#5e4416',
          DEFAULT: '#e2bd62',
          foreground: '#1d1e22',
        },

        // 색상 유리 — 버튼 면에만
        lapis: rgb('92 140 255'),
        olive: rgb('176 204 82'),
        porphyra: rgb('232 102 192'),

        // 가격 — 한국 관례. 매수 = 상승 빨강, 매도 = 하락 파랑
        up: '#ff5a5f',
        down: '#5b9bff',
        buy: {
          DEFAULT: '#ff5a5f',
          hover: '#ff7478',
          subtle: 'rgba(255,90,95,0.12)',
        },
        sell: {
          DEFAULT: '#5b9bff',
          hover: '#79aeff',
          subtle: 'rgba(91,155,255,0.12)',
        },

        // 상태 — 정상 · 오류 · 주의
        ok: '#b0cc52',
        danger: {
          DEFAULT: '#ff8a5c',
          subtle: 'rgba(255,138,92,0.12)',
        },
        warning: {
          DEFAULT: '#e2bd62',
          subtle: 'rgba(226,189,98,0.12)',
        },
        info: {
          DEFAULT: '#c9c8c5',
          subtle: 'rgba(201,200,197,0.12)',
        },
        neutral: {
          DEFAULT: '#9e9e9d',
          subtle: 'rgba(158,158,157,0.12)',
        },

        border: {
          DEFAULT: 'rgba(251,250,246,0.14)',
          subtle: 'rgba(251,250,246,0.08)',
          strong: 'rgba(251,250,246,0.14)',
          focus: '#fff1c4',
        },

        connected: '#b0cc52',
        connecting: '#e2bd62',
        reconnecting: '#e2bd62',
        disconnected: '#ff8a5c',
      },
      fontFamily: {
        sans: ['Pretendard Variable', '-apple-system', 'BlinkMacSystemFont', 'Apple SD Gothic Neo', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'Menlo', 'Consolas', 'monospace'],
      },
      fontSize: {
        xs: ['0.6875rem', { lineHeight: '1rem' }],
        sm: ['0.75rem', { lineHeight: '1.125rem' }],
        base: ['0.875rem', { lineHeight: '1.375rem' }],
        md: ['1rem', { lineHeight: '1.5rem' }],
        lg: ['1.125rem', { lineHeight: '1.75rem' }],
        xl: ['1.375rem', { lineHeight: '2rem' }],
        '2xl': ['1.75rem', { lineHeight: '2.25rem' }],
        '3xl': ['2.25rem', { lineHeight: '2.75rem' }],
      },
      borderRadius: {
        sm: '6px',
        DEFAULT: '8px',
        md: '8px',
        lg: '12px',
        xl: '16px',
        field: '16px',
        panel: '28px',
        sheet: '30px',
      },
      boxShadow: {
        sm: '0 1px 2px rgba(0,0,0,0.4)',
        md: '0 4px 10px rgba(0,0,0,0.45)',
        lg: '0 14px 34px -12px rgba(0,0,0,0.55)',
        xl: '0 24px 60px -16px rgba(0,0,0,0.7)',
        dialog: '0 24px 60px -16px rgba(0,0,0,0.7)',
      },
      transitionTimingFunction: {
        spring: 'cubic-bezier(0.3, 1.35, 0.5, 1)',
      },
      animation: {
        'slide-in-top': 'slideInTop 380ms cubic-bezier(0.3, 1.35, 0.5, 1)',
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
          '0%, 100%': { borderColor: 'rgba(255,138,92,0.4)' },
          '50%': { borderColor: 'rgba(255,138,92,1)' },
        },
      },
    },
  },
  plugins: [],
}
