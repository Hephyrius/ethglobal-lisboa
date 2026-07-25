import type { Config } from 'tailwindcss'

/**
 * Visual language: institutional finance, not crypto-native.
 *
 * The reference points are a research note and an asset-manager dashboard —
 * warm paper ground, hairline rules, tabular figures, one sober accent, colour
 * used only where it carries meaning. Deliberately *not* the dark-with-neon
 * convention of most DeFi front-ends: this product's claim is that an agent can
 * do a job real allocators do, and it should look like it belongs in that world.
 *
 * Colour names stay semantic (agent / data / ok / bad) rather than literal,
 * because the decision feed's job is to distinguish *kinds* of thing: what the
 * curator said, what a data source reported, what the chain confirmed.
 */
const config: Config = {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        base: '#FAF9F7', // warm paper
        surface: '#FFFFFF',
        raised: '#F4F2EE', // insets, table stripes
        line: '#E4E0D9', // hairline rules
        'line-bright': '#CFC9BF',
        ink: '#14181D',
        muted: '#5B646F',
        faint: '#8A9099',
        // Semantic
        agent: '#1D3B6B', // the curator's voice — reasoning, mandate, primary action
        data: '#1B6A66', // observed facts and their provenance
        ok: '#146B3C', // executed on-chain
        warn: '#8A5209', // degraded / held / fixture mode
        bad: '#9E2B20', // rejected by validation, failed
      },
      fontFamily: {
        // No webfont: next/font/google fetches at build time, which would make a
        // fresh clone on the 10:00 macOS handoff depend on network access.
        // These stacks resolve to something appropriate on macOS and Windows.
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
        // Serif headings do most of the work of reading "financial" rather than
        // "web3", and cost nothing — every target OS ships one of these.
        serif: [
          'Iowan Old Style',
          'Palatino Linotype',
          'Palatino',
          'Georgia',
          'Times New Roman',
          'serif',
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
      borderRadius: {
        // Tight corners read institutional; pill shapes read consumer crypto.
        DEFAULT: '3px',
        md: '4px',
        lg: '5px',
        xl: '6px',
      },
      boxShadow: {
        card: '0 1px 2px rgba(20, 24, 29, 0.04)',
        raised: '0 2px 8px rgba(20, 24, 29, 0.06)',
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
