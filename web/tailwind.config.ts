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
        raised: '#F6F5F9', // insets, table stripes
        line: '#E7E5EE', // hairline rules
        'line-bright': '#CBC7D8',
        ink: '#17161D', // near-black, violet undertone
        muted: '#575366',
        faint: '#86818F',

        // ── The curator's voice ───────────────────────────────────────────
        // Deep violet: mystical in hue, institutional in depth. Chosen dark
        // enough (~9:1 on white) to serve as body-weight text AND as a solid
        // button ground with white type, because it is used both ways. A
        // brighter violet would have forced a second colour for one of them.
        agent: '#4A3B8C',
        'agent-soft': '#6F5FB8', // borders, hover, secondary marks
        'agent-tint': '#F1EFF9', // wash backgrounds

        // ── Highlight ─────────────────────────────────────────────────────
        // Antique gold. Decorative and structural only — rules, active
        // underlines, the one figure on a page that should be looked at
        // first. Deliberately yellower than `warn` below: gold must never be
        // mistaken for a warning in a UI where colour carries meaning.
        gold: '#A8801F',
        'gold-bright': '#D9A93C', // hairline rules, underlines
        'gold-tint': '#FAF4E6', // wash backgrounds

        // ── Semantic ──────────────────────────────────────────────────────
        data: '#156E6A', // observed facts and their provenance
        ok: '#136B3E', // executed on-chain
        warn: '#B45309', // degraded / held / fixture mode — orange, not gold
        bad: '#A32B21', // rejected by validation, failed
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
        //
        // Ordered for a higher-contrast, older-cut face first: Hoefler Text and
        // Baskerville are the transitional serifs a private bank's letterhead
        // would use, and both ship on macOS. Iowan and Palatino are humanist
        // and warmer — kept as the next rung because they are the best that
        // Windows offers before Georgia. The visual jump from Georgia up to
        // Baskerville is most of what makes this read "traditional" rather
        // than "website".
        serif: [
          'Hoefler Text',
          'Baskerville',
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
