import type { Config } from 'tailwindcss'

/**
 * Single dark theme. This app is a demo surface shown on a projector and on a
 * judge's laptop, not a consumer product that has to follow an OS preference —
 * so one deliberately-tuned theme beats two half-tuned ones.
 *
 * Semantic colour names (agent / data / ok / bad) rather than literal ones,
 * because the decision feed's whole job is to distinguish *kinds* of thing:
 * what the agent said, what a data source reported, what the chain confirmed.
 */
const config: Config = {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        base: '#08090B',
        surface: '#0E1014',
        raised: '#14171C',
        line: '#1E232B',
        'line-bright': '#2C333E',
        ink: '#E9ECF2',
        muted: '#98A2B0',
        faint: '#616B79',
        // Semantic
        agent: '#F5B833', // the curator's own voice — reasoning, mandate
        data: '#4FC3E8', // observed facts and their provenance
        ok: '#3ECF8E', // executed on-chain
        warn: '#F0A438', // degraded / held
        bad: '#F2686B', // rejected by validation, failed
      },
      fontFamily: {
        // No webfont: next/font/google fetches at build time, which would make
        // a fresh clone on the 10:00 macOS handoff depend on network access.
        sans: [
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Roboto',
          'Helvetica Neue',
          'Arial',
          'sans-serif',
        ],
        mono: [
          'ui-monospace',
          'SFMono-Regular',
          'SF Mono',
          'Menlo',
          'Consolas',
          'Liberation Mono',
          'monospace',
        ],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
      },
      keyframes: {
        'fade-up': {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'pulse-soft': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.45' },
        },
      },
      animation: {
        'fade-up': 'fade-up 320ms cubic-bezier(0.16, 1, 0.3, 1) both',
        'pulse-soft': 'pulse-soft 2s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}

export default config
