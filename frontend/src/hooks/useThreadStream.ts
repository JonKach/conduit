import { useCallback, useRef, useState } from "react"

import { type ChatRequest, OpenAPI } from "@/client"

export type ThreadStreamEventType =
  | "start"
  | "data"
  | "reasoning"
  | "tool_call"
  | "done"
  | "error"

export interface ThreadStreamEvent {
  type: ThreadStreamEventType
  data: string
  id: string
}

interface UseThreadStreamParams {
  agentId: string
  threadId: string
  onEvent: (event: ThreadStreamEvent) => void
}

/**
 * The generated SDK is axios-based and buffers the whole response body, so it
 * can't be used to read a Server-Sent-Events stream incrementally. This talks
 * to the same /stream endpoint directly with fetch() so we can read the
 * response body as it arrives.
 */
export function useThreadStream({
  agentId,
  threadId,
  onEvent,
}: UseThreadStreamParams) {
  const [isStreaming, setIsStreaming] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const send = useCallback(
    async (chatRequest: ChatRequest) => {
      const controller = new AbortController()
      abortRef.current = controller
      setIsStreaming(true)

      try {
        const token = localStorage.getItem("access_token") || ""
        const response = await fetch(
          `${OpenAPI.BASE}/api/v1/agents/${agentId}/threads/${threadId}/stream`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify(chatRequest),
            signal: controller.signal,
          },
        )

        if (!response.ok || !response.body) {
          throw new Error(
            `Stream request failed with status ${response.status}`,
          )
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ""

        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })

          let boundary = buffer.indexOf("\n\n")
          while (boundary !== -1) {
            const rawEvent = buffer.slice(0, boundary)
            buffer = buffer.slice(boundary + 2)
            boundary = buffer.indexOf("\n\n")

            const line = rawEvent.startsWith("data: ")
              ? rawEvent.slice(6)
              : rawEvent
            if (!line.trim()) continue

            try {
              const parsed = JSON.parse(line) as ThreadStreamEvent
              onEvent(parsed)
              if (parsed.type === "done" || parsed.type === "error") {
                await reader.cancel()
                return
              }
            } catch (err) {
              console.error("Failed to parse stream event", line, err)
            }
          }
        }
      } finally {
        setIsStreaming(false)
        abortRef.current = null
      }
    },
    [agentId, threadId, onEvent],
  )

  const cancel = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  return { send, cancel, isStreaming }
}
