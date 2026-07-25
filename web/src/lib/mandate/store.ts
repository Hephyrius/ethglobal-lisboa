import { Mandate, type Mandate as MandateT } from '@curator/schema'

/**
 * Client-side record of vaults created from this browser, and the mandate each
 * was deployed with.
 *
 * This exists because of a real gap in the frozen interface, filed as
 * cross-lane request #6: `VaultState` carries `mandate_hash` but no route
 * returns the `Mandate` itself, so the vault page has nothing to render in the
 * mandate viewer that §10 Lane E MVP requires. Rather than reach into Lane B or
 * edit the frozen schema, we keep what we already had in hand at
 * `POST /genesis/finalize` and read it back on the vault page.
 *
 * The limitation is honest and worth stating in the UI: this only covers vaults
 * created in *this* browser. When request #6 lands, this becomes a cache in
 * front of the route rather than the only source.
 *
 * Storage is untrusted input — anything read back is re-validated through the
 * zod mirror before it reaches a component.
 */

const VAULT_INDEX_KEY = 'curator.vaults.v1'
const mandateKey = (address: string) => `curator.mandate.v1.${address.toLowerCase()}`

export type LocalVault = {
  address: string
  name: string
  mandateHash: string
  deployTx: string
  createdAt: string
}

function canUseStorage(): boolean {
  return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined'
}

function readJson<T>(key: string): T | null {
  if (!canUseStorage()) return null
  try {
    const raw = window.localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : null
  } catch {
    return null
  }
}

function writeJson(key: string, value: unknown): void {
  if (!canUseStorage()) return
  try {
    window.localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // Quota or private-mode failures must never break the deploy flow — the
    // vault exists on-chain regardless of whether we managed to remember it.
  }
}

export function rememberVault(entry: LocalVault, mandate: MandateT): void {
  const existing = listLocalVaults().filter(
    (vault) => vault.address.toLowerCase() !== entry.address.toLowerCase(),
  )
  writeJson(VAULT_INDEX_KEY, [entry, ...existing])
  writeJson(mandateKey(entry.address), mandate)
}

export function listLocalVaults(): LocalVault[] {
  const stored = readJson<LocalVault[]>(VAULT_INDEX_KEY)
  if (!Array.isArray(stored)) return []
  return stored.filter(
    (entry): entry is LocalVault =>
      typeof entry?.address === 'string' && /^0x[a-fA-F0-9]{40}$/.test(entry.address),
  )
}

/** Null when this browser did not create the vault — the caller decides what to show. */
export function getStoredMandate(address: string): MandateT | null {
  const stored = readJson<unknown>(mandateKey(address))
  if (!stored) return null
  const parsed = Mandate.safeParse(stored)
  return parsed.success ? parsed.data : null
}

export function forgetVault(address: string): void {
  if (!canUseStorage()) return
  writeJson(
    VAULT_INDEX_KEY,
    listLocalVaults().filter((vault) => vault.address.toLowerCase() !== address.toLowerCase()),
  )
  try {
    window.localStorage.removeItem(mandateKey(address))
  } catch {
    // best-effort
  }
}
