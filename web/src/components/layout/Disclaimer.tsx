/**
 * "Proof of concept for ETH Lisbon, do not send money to this."
 *
 * Deliberately **not dismissible**. A dismissible warning is one someone
 * dismisses, and the page it matters most on is a deep-linked vault reached
 * from a shared URL — where the reader has no context, sees a deposit form
 * wired to a real wallet, and is one click from funding an unaudited contract
 * whose key is held by a language model.
 *
 * Sits above the sticky header rather than inside it so it cannot be scrolled
 * past on the one page that has a long scroll, and so it survives every route
 * including `/vault/[address]`.
 */
export function Disclaimer() {
  return (
    <div className="border-b border-warn/25 bg-warn/[0.07]">
      <p className="mx-auto max-w-[1400px] px-4 py-1.5 text-center text-2xs leading-relaxed text-warn sm:px-6">
        <span className="font-semibold">Proof of concept for ETHGlobal Lisbon.</span>{' '}
        <span className="hidden sm:inline">
          Unaudited contracts on a local fork, curated by a language model that holds the key.{' '}
        </span>
        Do not send real money to this.
      </p>
    </div>
  )
}
