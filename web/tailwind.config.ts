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
        // ── Ground ────────────────────────────────────────────────────────
        // White, not paper. The ground carries no colour of its own; every
        // tint below leans a few degrees violet so the surface reads as one
        // family rather than as grey with a purple accent bolted on.
        //
        // NAMED `canvas`, NOT `base`. A colour called `base` collides with
        // Tailwind's font-size step `text-base`: the utility becomes ambiguous
        // and Tailwind emits BOTH, so every `text-base` element silently also
        // gets `color: <that colour>`. It was survivable while the ground was
        // warm paper — the header wordmark just looked washed out — and became
        // invisible white-on-white the moment the ground went pure white.
        // Do not reintroduce a colour token whose name is a font-size step.
        canvas: '#FFFFFF',
        surface: '#FFFFFF',
        raised: '#F1F2F3', // insets, table stripes
        line: '#E6E9EC', // hairline rules
        'line-bright': '#ACB1B9',
        ink: '#141A1F', // near-black with a cool blue cast
        muted: '#5E676E',
        faint: '#939A9F',

        // ── The curator's voice ───────────────────────────────────────────
        // The blue family. #005BCC is the workhorse: ~6.3:1 on white, so it
        // carries body-weight text AND a solid button ground with white type,
        // which is what `agent` is used for (16x and 12x respectively).
        agent: '#005BCC',
        'agent-deep': '#003D99', // pressed states, higher-emphasis text
        'agent-bright': '#008CFF', // rules, underlines, the accent
        'agent-tint': '#F2FAFF', // wash backgrounds

        // ── Semantic ──────────────────────────────────────────────────────
        // The reference palette is essentially monochrome — near-black, white
        // and blues. It carries no green and no amber, so these three are an
        // extension, desaturated to sit beside the blue rather than compete
        // with it. Only `bad` is drawn from the source, which uses a pure red.
        data: '#0F6E8C', // observed facts and their provenance — steel cyan
        ok: '#0F7A43', // executed on-chain
        warn: '#B45309', // degraded / held / fixture mode
        bad: '#CC0000', // rejected by validation, failed
      },
      fontFamily: {
        // No webfont: next/font/google fetches at build time, which would make a
        // fresh clone on the 10:00 macOS handoff depend on network access.
        // These stacks resolve to something appropriate on macOS and Windows.
        // One family for everything, which is how the reference site is set:
        // no serif anywhere, hierarchy carried by size, weight and tracking.
        //
        // The reference uses a proprietary custom face (`rippleFont`); its own
        // declared fallback is Helvetica/Arial, so that is what is reproduced
        // here. Helvetica Neue leads because it is the closest neo-grotesque
        // that macOS ships, and no webfont is fetched — a fresh clone must
        // still build without network access.
        sans: [
          'Helvetica Neue',
          'Helvetica',
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Roboto',
          'Arial',
          'sans-serif',
        ],
        // Deliberately points at the same grotesque as `sans`. The reference
        // site sets one family across every surface, so `font-serif` must not
        // introduce a second voice. Kept as a key rather than deleted because
        // six call sites still use it, and a token that quietly resolves to
        // the house family is safer than six edits that can be missed — but
        // treat it as deprecated: new work should not reach for `font-serif`.
        serif: [
          'Helvetica Neue',
          'Helvetica',
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
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
