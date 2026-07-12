export interface ToolCallInfo {
  id: string
  name: string
  input: string
}

export interface UsageInfo {
  input_tokens: number
  output_tokens: number
  total_tokens: number
}

export interface UserTurn {
  id: string
  role: "user"
  text: string
}

export interface AssistantTurn {
  id: string
  role: "assistant"
  text: string
  reasoning: string
  toolCalls: ToolCallInfo[]
  usage?: UsageInfo
  status: "streaming" | "done" | "error"
  error?: string
}

export type ChatTurn = UserTurn | AssistantTurn

function extractText(content: unknown): string {
  if (typeof content === "string") return content
  if (Array.isArray(content)) {
    return content
      .map((block) => {
        if (typeof block === "string") return block
        if (block && typeof block === "object" && "text" in block) {
          return String((block as { text: unknown }).text ?? "")
        }
        return ""
      })
      .join("")
  }
  return ""
}

export interface HistoryMessage {
  type: string
  content: unknown
  usage?: UsageInfo | null
}

/**
 * The backend replays checkpointed messages as flat human/ai/tool entries
 * with no id linking a tool call to the assistant turn that made it, so
 * historical tool calls aren't reconstructed here — only live streaming
 * turns show them (see useThreadStream "tool_call" events).
 */
export function seedTurnsFromHistory(messages: HistoryMessage[]): ChatTurn[] {
  const turns: ChatTurn[] = []
  for (const [index, message] of messages.entries()) {
    if (message.type === "human") {
      turns.push({
        id: `history-${index}`,
        role: "user",
        text: extractText(message.content),
      })
    } else if (message.type === "ai") {
      turns.push({
        id: `history-${index}`,
        role: "assistant",
        text: extractText(message.content),
        reasoning: "",
        toolCalls: [],
        usage: message.usage ?? undefined,
        status: "done",
      })
    }
  }
  return turns
}
