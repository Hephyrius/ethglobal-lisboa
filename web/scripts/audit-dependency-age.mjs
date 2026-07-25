#!/usr/bin/env node
/**
 * Dependency-age audit for the JavaScript side of the repo.
 *
 * Policy: every package in the resolved tree must have been published at least
 * N days ago (default 180). The reasoning is that npm supply-chain compromises
 * are discovered and yanked in days-to-weeks, so refusing to install anything
 * from the recent window removes most of the exposure without pinning us to
 * genuinely ancient software. Pinning direct dependencies is not enough on its
 * own — a caret anywhere in the transitive tree reopens the same hole — so this
 * checks the *whole* resolved lockfile.
 *
 * This is a check, not a fix. When it fails, the remedy is to pin the offending
 * package (web/package.json for a direct dependency, `pnpm.overrides` in the
 * root package.json for a transitive one) and reinstall.
 *
 * Usage:
 *   node scripts/audit-dependency-age.mjs
 *   node scripts/audit-dependency-age.mjs --max-age-days 90
 *   node scripts/audit-dependency-age.mjs --json
 *   node scripts/audit-dependency-age.mjs --lockfile ../pnpm-lock.yaml
 *
 * Exit code is 1 if any package violates the policy, so it works in CI.
 */

import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const DEFAULTS = {
  maxAgeDays: 180,
  lockfile: path.join(HERE, '..', '..', 'pnpm-lock.yaml'),
  concurrency: 8,
  registry: 'https://registry.npmjs.org',
}

function parseArgs(argv) {
  const options = { ...DEFAULTS, json: false }
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]
    if (arg === '--json') options.json = true
    else if (arg === '--max-age-days') options.maxAgeDays = Number(argv[++i])
    else if (arg === '--lockfile') options.lockfile = path.resolve(argv[++i])
    else if (arg === '--concurrency') options.concurrency = Number(argv[++i])
    else if (arg === '--registry') options.registry = argv[++i]
    else if (arg === '--help' || arg === '-h') {
      console.log(
        'Usage: audit-dependency-age.mjs [--max-age-days N] [--lockfile PATH] [--concurrency N] [--json]',
      )
      process.exit(0)
    } else {
      console.error(`Unknown argument: ${arg}`)
      process.exit(2)
    }
  }
  if (!Number.isFinite(options.maxAgeDays) || options.maxAgeDays < 0) {
    console.error('--max-age-days must be a non-negative number')
    process.exit(2)
  }
  return options
}

/**
 * Pull `name@version` pairs out of the `packages:` section of a pnpm v9
 * lockfile. Deliberately a regex rather than a YAML dependency: this tool must
 * be runnable before `pnpm install` has been trusted, so it takes no
 * dependencies of its own.
 */
function parseLockfile(text) {
  const start = text.indexOf('\npackages:')
  if (start === -1) return []

  const section = text.slice(start)
  const entries = new Map()
  // e.g.   '@types/react@18.3.26':      or   zod@3.25.76:
  const pattern = /^ {2}'?((?:@[^/\s']+\/)?[^@\s']+)@([^':\s()]+)'?:$/gm

  let match
  while ((match = pattern.exec(section)) !== null) {
    const [, name, version] = match
    // Peer-suffixed keys look like `wagmi@2.19.2(react@18.3.1)`; the regex stops
    // at the paren, so the version is already clean. Links and file: specs have
    // no registry entry to check.
    if (version.startsWith('link:') || version.startsWith('file:')) continue
    entries.set(`${name}@${version}`, { name, version })
  }
  return [...entries.values()]
}

async function fetchPackageTimes(name, registry) {
  const url = `${registry}/${name.replace('/', '%2F')}`
  const response = await fetch(url, { headers: { accept: 'application/json' } })
  if (!response.ok) throw new Error(`registry returned ${response.status}`)
  const body = await response.json()
  return body.time ?? {}
}

async function mapWithConcurrency(items, limit, worker) {
  const results = []
  let cursor = 0
  const runners = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (cursor < items.length) {
      const index = cursor++
      results[index] = await worker(items[index], index)
    }
  })
  await Promise.all(runners)
  return results
}

async function main() {
  const options = parseArgs(process.argv.slice(2))
  const lockText = await readFile(options.lockfile, 'utf8').catch((error) => {
    console.error(`Cannot read lockfile at ${options.lockfile}: ${error.message}`)
    process.exit(2)
  })

  const packages = parseLockfile(lockText)
  if (packages.length === 0) {
    console.error('No packages found in the lockfile — has the format changed?')
    process.exit(2)
  }

  const cutoff = new Date(Date.now() - options.maxAgeDays * 86_400_000)
  const uniqueNames = [...new Set(packages.map((entry) => entry.name))]

  if (!options.json) {
    process.stderr.write(
      `Auditing ${packages.length} resolved packages (${uniqueNames.length} distinct) ` +
        `against a ${options.maxAgeDays}-day minimum age…\n`,
    )
  }

  const timesByName = new Map()
  const errors = []
  await mapWithConcurrency(uniqueNames, options.concurrency, async (name) => {
    try {
      timesByName.set(name, await fetchPackageTimes(name, options.registry))
    } catch (error) {
      errors.push({ name, message: error.message })
    }
  })

  const violations = []
  const unknown = []
  for (const entry of packages) {
    const times = timesByName.get(entry.name)
    const published = times?.[entry.version]
    if (!published) {
      unknown.push(entry)
      continue
    }
    const publishedAt = new Date(published)
    if (publishedAt > cutoff) {
      violations.push({
        ...entry,
        publishedAt: published,
        ageDays: Math.floor((Date.now() - publishedAt.getTime()) / 86_400_000),
      })
    }
  }

  violations.sort((a, b) => a.ageDays - b.ageDays)

  if (options.json) {
    console.log(JSON.stringify({ cutoff: cutoff.toISOString(), violations, unknown, errors }, null, 2))
  } else {
    if (violations.length === 0) {
      console.log(
        `\n✓ All ${packages.length} resolved packages are at least ${options.maxAgeDays} days old.`,
      )
    } else {
      console.log(`\n✗ ${violations.length} package(s) newer than ${options.maxAgeDays} days:\n`)
      for (const violation of violations) {
        console.log(
          `  ${`${violation.name}@${violation.version}`.padEnd(48)} ` +
            `${violation.ageDays}d old  (${violation.publishedAt.slice(0, 10)})`,
        )
      }
      console.log('\nPin these in web/package.json, or in `pnpm.overrides` if transitive.')
    }
    if (unknown.length > 0) {
      console.log(`\n${unknown.length} package(s) had no publish time on the registry (skipped).`)
    }
    if (errors.length > 0) {
      console.log(`\n${errors.length} package(s) could not be checked:`)
      for (const error of errors.slice(0, 10)) console.log(`  ${error.name}: ${error.message}`)
    }
  }

  process.exit(violations.length > 0 ? 1 : 0)
}

main().catch((error) => {
  console.error(error)
  process.exit(2)
})
