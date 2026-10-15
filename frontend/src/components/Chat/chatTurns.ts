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
  files?: string[]
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

// Marker appended by build_user_message (backend/app/gcs_backend.py). Only the
// "Attached Files" section is rendered; "Available Files" is for the model.
const PROMPT_DATA_MARKER = "%%PROMPT_DATA%%"
const ATTACHED_FILES_HEADER = "Attached Files:"

/**
 * Strip the `%%PROMPT_DATA%%` marker sections off a message's raw content,
 * returning the human-authored text plus the paths listed under "Attached
 * Files:" (normalized to match what the upload endpoint returns, e.g.
 * "/invoice.pdf" — no leading "/media").
 */
export function splitPromptData(raw: string): {
  text: string
  files: string[]
} {
  const markerIndex = raw.indexOf(PROMPT_DATA_MARKER)
  if (markerIndex === -1) return { text: raw, files: [] }

  const text = raw.slice(0, markerIndex).trimEnd()
  const sections = raw
    .slice(markerIndex)
    .split(PROMPT_DATA_MARKER)
    .filter((section) => section.length > 0)
  const attachedSection = sections.find((section) =>
    section.startsWith(ATTACHED_FILES_HEADER),
  )
  if (!attachedSection) return { text, files: [] }

  const files = attachedSection
    .slice(ATTACHED_FILES_HEADER.length)
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith("- "))
    .map((line) =>
      line
        .slice(2)
        .trim()
        .replace(/^\/media/, ""),
    )

  return { text, files }
}

/** Strip the agent-visible "/media/" mount prefix and any leading slash. */
export function fileNameFromPath(path: string): string {
  return path.replace(/^\/media\//, "").replace(/^\//, "")
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
      const { text, files } = splitPromptData(extractText(message.content))
      turns.push({
        id: `history-${index}`,
        role: "user",
        text,
        files: files.length > 0 ? files : undefined,
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
