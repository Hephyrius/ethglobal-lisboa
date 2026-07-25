'use client'

import { useMutation } from '@tanstack/react-query'
import type { z } from 'zod'
import type { Mandate as MandateT } from '@curator/schema'
import { apiFetch, apiFetchStrict, postJson, type Sourced } from './client'
import { simulateGenesisChat, type ChatMessage } from './genesis-sim'
import { routes, schemas } from './routes'
import { useReportMode } from './mode-context'

type ChatResponse = z.infer<typeof schemas.genesisChat.response>
type FinalizeResponse = z.infer<typeof schemas.genesisFinalize.response>

/** A local model thinking takes seconds, not milliseconds. */
const MODEL_TIMEOUT_MS = 120_000
/** A deploy waits on a block. */
const DEPLOY_TIMEOUT_MS = 90_000

export function useGenesisChat() {
  const mutation = useMutation({
    mutationFn: ({
      messages,
      draft,
    }: {
      messages: ChatMessage[]
      draft: Partial<MandateT>
    }): Promise<Sourced<ChatResponse>> =>
      apiFetch({
        path: routes.genesisChat(),
        schema: schemas.genesisChat.response,
        init: postJson({ messages }),
        fallback: () => simulateGenesisChat(messages, draft),
        timeoutMs: MODEL_TIMEOUT_MS,
      }),
  })

  useReportMode('genesis-chat', mutation.data)
  return mutation
}

/**
 * `POST /genesis/finalize` — deploys the vault. **No fixture fallback, by
 * design.**
 *
 * Every read in this app degrades to a fixture so the UI is never blocked. A
 * deploy must not: falling back here would hand back a vault address that was
 * never deployed and a transaction hash that does not exist, and someone would
 * eventually show that hash to a judge. Reads degrade; writes fail honestly.
 *
 * The genesis screen handles the failure by keeping the mandate on screen and
 * offering a clearly-labelled fixture preview of the vault surface instead.
 */
export function useGenesisFinalize() {
  return useMutation({
    mutationFn: (mandate: MandateT): Promise<FinalizeResponse> =>
      apiFetchStrict({
        path: routes.genesisFinalize(),
        schema: schemas.genesisFinalize.response,
        init: postJson({ mandate }),
        timeoutMs: DEPLOY_TIMEOUT_MS,
      }),
  })
}
