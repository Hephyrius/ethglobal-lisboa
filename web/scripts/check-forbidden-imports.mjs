#!/usr/bin/env node
/**
 * Fail the build on imports this app must never contain.
 *
 * **Why this exists, concretely.** `PortfolioStrip` imported the React hook
 * `useAccount` from `'wagmi'`. This app drives the wallet through `@wagmi/core`
 * imperatively and mounts **no `WagmiProvider`**, so the hook threw
 * `WagmiProviderNotFoundError` and took the entire homepage down
 * (cross-lane request #58).
 *
 * The reason it got that far is worth stating, because it is what makes a
 * type-checker useless here: `wagmi` is not a dependency of `web/`, but a stale
 * copy sits at the **workspace root** `node_modules/wagmi` from before this app
 * dropped it. Node and webpack resolution walk up from `web/`, find it, and
 * resolve happily — so the import compiles, builds, and only explodes in the
 * browser. Nothing in `tsc` or `next build` can catch that.
 *
 * A grep-shaped check is therefore the right tool rather than a weak one. The
 * alternative was ESLint with `no-restricted-imports`, rejected because it
 * costs a large dependency tree in a repo whose supply-chain policy pins every
 * package to an exact version at least 180 days old — a lot of surface to buy
 * one rule. This has no dependencies at all.
 *
 * Usage:
 *   node scripts/check-forbidden-imports.mjs
 *   node scripts/check-forbidden-imports.mjs --dir src --json
 *
 * Runs automatically before `pnpm build` via the `prebuild` script.
 */

import { readdir, readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const HERE = path.dirname(fileURLToPath(import.meta.url))

/**
 * Add a rule here when a module is banned outright. Keep the `why` specific —
 * a rule whose message only says "forbidden" gets deleted by the next person
 * who hits it.
 */
const RULES = [
  {
    // `wagmi` and any subpath of it. `@wagmi/core` is deliberately NOT matched:
    // that is the package this app actually uses.
    pattern: /^wagmi(\/|$)/,
    why: 'this app mounts no <WagmiProvider>, so wagmi React hooks throw WagmiProviderNotFoundError at runtime — and it resolves from the workspace root, so nothing catches it at build time (#58)',
    instead: "'@/lib/chain/account' for account state, '@wagmi/core' for actions",
  },
]

const EXTENSIONS = new Set(['.ts', '.tsx', '.mts', '.js', '.jsx', '.mjs'])

/** `from '…'`, `import '…'`, `require('…')`, and `import('…')`. */
const IMPORT_PATTERNS = [
  /\bfrom\s+['"]([^'"]+)['"]/g,
  /\bimport\s+['"]([^'"]+)['"]/g,
  /\brequire\(\s*['"]([^'"]+)['"]\s*\)/g,
  /\bimport\(\s*['"]([^'"]+)['"]\s*\)/g,
]

function parseArgs(argv) {
  const options = { dir: path.join(HERE, '..', 'src'), json: false }
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--json') options.json = true
    else if (argv[i] === '--dir') options.dir = path.resolve(argv[++i])
    else if (argv[i] === '--help' || argv[i] === '-h') {
      console.log('Usage: check-forbidden-imports.mjs [--dir PATH] [--json]')
      process.exit(0)
    } else {
      console.error(`Unknown argument: ${argv[i]}`)
      process.exit(2)
    }
  }
  return options
}

async function* walk(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      if (entry.name === 'node_modules' || entry.name.startsWith('.')) continue
      yield* walk(full)
    } else if (EXTENSIONS.has(path.extname(entry.name))) {
      yield full
    }
  }
}

/**
 * Strip comments before matching. The file that documents this very incident
 * mentions `from 'wagmi'` in prose, and a checker that fails on its own
 * explanation teaches people to delete the explanation.
 */
function stripComments(source) {
  return source.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' ')).replace(/\/\/[^\n]*/g, '')
}

async function main() {
  const options = parseArgs(process.argv.slice(2))
  const violations = []

  for await (const file of walk(options.dir)) {
    const source = stripComments(await readFile(file, 'utf8'))
    const lines = source.split('\n')

    lines.forEach((line, index) => {
      for (const pattern of IMPORT_PATTERNS) {
        pattern.lastIndex = 0
        let match
        while ((match = pattern.exec(line)) !== null) {
          const specifier = match[1]
          const rule = RULES.find((candidate) => candidate.pattern.test(specifier))
          if (rule) {
            violations.push({
              file: path.relative(path.join(HERE, '..'), file).replace(/\\/g, '/'),
              line: index + 1,
              specifier,
              why: rule.why,
              instead: rule.instead,
            })
          }
        }
      }
    })
  }

  if (options.json) {
    console.log(JSON.stringify({ violations }, null, 2))
  } else if (violations.length === 0) {
    console.log('✓ No forbidden imports.')
  } else {
    console.error(`\n✗ ${violations.length} forbidden import(s):\n`)
    for (const violation of violations) {
      console.error(`  ${violation.file}:${violation.line}  imports '${violation.specifier}'`)
      console.error(`      ${violation.why}`)
      console.error(`      use instead: ${violation.instead}\n`)
    }
  }

  process.exit(violations.length > 0 ? 1 : 0)
}

main().catch((error) => {
  console.error(error)
  process.exit(2)
})
