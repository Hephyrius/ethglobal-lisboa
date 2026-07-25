import path from 'node:path'
import { fileURLToPath } from 'node:url'

const repoRoot = path.join(path.dirname(fileURLToPath(import.meta.url)), '..')

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,

  // Lets a production build run without fighting a live `next dev` for
  // `.next/trace`, which fails EPERM on Windows and reads as a code error when
  // it is a file lock. `NEXT_DIST_DIR=.next-build pnpm build` verifies the tree
  // while the demo stays up.
  distDir: process.env.NEXT_DIST_DIR || '.next',

  // @curator/schema is published as raw TypeScript (main → src/index.ts) so the
  // zod mirror stays a single source of truth with no build step. Next has to
  // compile it rather than treat it as prebuilt node_modules.
  transpilePackages: ['@curator/schema'],

  // We import the golden fixtures from packages/schema/fixtures, which lives
  // above this directory. Pointing the tracing root at the repo root keeps file
  // tracing correct in the workspace instead of guessing from the app dir.
  // (Top-level in Next 15; still under `experimental` on 14.2.)
  experimental: {
    outputFileTracingRoot: repoRoot,
  },

  webpack: (config) => {
    // wagmi/viem pull in optional React Native and WalletConnect peer modules
    // that we never load with the injected-only connector.
    config.externals.push('pino-pretty', 'lokijs', 'encoding')
    return config
  },
}

export default nextConfig
