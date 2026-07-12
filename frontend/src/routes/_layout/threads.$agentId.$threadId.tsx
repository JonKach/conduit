import { useQuery, useQueryClient, useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { ArrowLeft, Bot } from "lucide-react"
import { Suspense, useCallback, useRef, useState } from "react"

import {
  AgentsService,
  type AgentPublic,
  ThreadsService,
  type ThreadContentPublic,
} from "@/client"
import ChatComposer from "@/components/Chat/ChatComposer"
import ChatTranscript from "@/components/Chat/ChatTranscript"
import {
  seedTurnsFromHistory,
  type ChatTurn,
  type HistoryMessage,
} from "@/components/Chat/chatTurns"
import ThreadActionsMenu from "@/components/Agents/ThreadActionsMenu"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Skeleton } from "@/components/ui/skeleton"
import { useThreadStream, type ThreadStreamEvent } from "@/hooks/useThreadStream"
import { getInitials } from "@/utils"

// No model-selection UI exists yet; the agent worker just needs some model id.
const DEFAULT_MODEL = "google_genai:gemini-3.1-flash-lite"

export const Route = createFileRoute("/_layout/threads/$agentId/$threadId")({
  component: () => {
    const { agentId, threadId } = Route.useParams()
    // Force a full remount (and state reset) when navigating between threads.
    return <ChatPage key={threadId} agentId={agentId} threadId={threadId} />
  },
})

function useAgentQuery(agentId: string) {
  return useSuspenseQuery({
    queryKey: ["agent", agentId],
    queryFn: () => AgentsService.readAgent({ agentId }),
  })
}

function useThreadQuery(agentId: string, threadId: string) {
  return useSuspenseQuery({
    queryKey: ["thread", agentId, threadId],
    queryFn: () => ThreadsService.readThread({ agentId, threadId }),
  })
}

function ChatHeader({
  agent,
  thread,
  profilePictureLink,
}: {
  agent: AgentPublic
  thread: ThreadContentPublic
  profilePictureLink?: string
}) {
  return (
    <div className="flex items-center gap-3 border-b px-4 py-3">
      <Link to="/agents/$agentId" params={{ agentId: agent.id }}>
        <ArrowLeft className="size-5 text-muted-foreground hover:text-foreground" />
      </Link>
      <Avatar className="size-9">
        {profilePictureLink ? (
          <AvatarImage src={profilePictureLink} alt={agent.name} />
        ) : null}
        <AvatarFallback className="bg-zinc-600 text-white">
          {agent.name ? getInitials(agent.name) : <Bot className="size-4" />}
        </AvatarFallback>
      </Avatar>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{thread.name}</p>
        <p className="truncate text-xs text-muted-foreground">{agent.name}</p>
      </div>
      <ThreadActionsMenu thread={thread} />
    </div>
  )
}

function ChatPageSkeleton() {
  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col gap-4 p-4">
      <div className="flex items-center gap-3">
        <Skeleton className="size-9 rounded-full" />
        <Skeleton className="h-4 w-40" />
      </div>
      <div className="flex flex-1 flex-col gap-3">
        <Skeleton className="ml-auto h-10 w-2/3" />
        <Skeleton className="h-16 w-3/4" />
      </div>
    </div>
  )
}

function ChatPageContent({ agentId, threadId }: { agentId: string; threadId: string }) {
  const { data: agent } = useAgentQuery(agentId)
  const { data: thread } = useThreadQuery(agentId, threadId)
  const queryClient = useQueryClient()

  const { data: profilePictureLink } = useQuery({
    queryKey: ["profilePicture", agent.id],
    queryFn: async () => {
      const res = await AgentsService.getProfilePicture({ agentId: agent.id })
      return res as string
    },
    retry: false,
  })

  const [turns, setTurns] = useState<ChatTurn[]>(() =>
    seedTurnsFromHistory(thread.messages as unknown as HistoryMessage[]),
  )
  const activeAssistantId = useRef<string | null>(null)

  const updateAssistant = useCallback(
    (update: (turn: Extract<ChatTurn, { role: "assistant" }>) => Extract<ChatTurn, { role: "assistant" }>) => {
      setTurns((prev) =>
        prev.map((turn) =>
          turn.role === "assistant" && turn.id === activeAssistantId.current
            ? update(turn)
            : turn,
        ),
      )
    },
    [],
  )

  const handleEvent = useCallback(
    (event: ThreadStreamEvent) => {
      switch (event.type) {
        case "data":
          updateAssistant((turn) => ({ ...turn, text: turn.text + event.data }))
          break
        case "reasoning":
          updateAssistant((turn) => ({
            ...turn,
            reasoning: turn.reasoning + event.data,
          }))
          break
        case "tool_call": {
          try {
            const parsed = JSON.parse(event.data) as {
              tool_name: string
              tool_input: unknown
            }
            updateAssistant((turn) => ({
              ...turn,
              toolCalls: [
                ...turn.toolCalls,
                { id: event.id, name: parsed.tool_name, input: JSON.stringify(parsed.tool_input) },
              ],
            }))
          } catch {
            // Malformed tool-call payload; nothing meaningful to show.
          }
          break
        }
        case "done": {
          try {
            const parsed = JSON.parse(event.data) as {
              message?: string
              input_tokens?: string
              output_tokens?: string
              total_tokens?: string
            }
            updateAssistant((turn) => ({
              ...turn,
              status: "done",
              usage:
                parsed.total_tokens !== undefined
                  ? {
                      input_tokens: Number(parsed.input_tokens ?? 0),
                      output_tokens: Number(parsed.output_tokens ?? 0),
                      total_tokens: Number(parsed.total_tokens ?? 0),
                    }
                  : undefined,
            }))
          } catch {
            updateAssistant((turn) => ({ ...turn, status: "done" }))
          }
          queryClient.invalidateQueries({ queryKey: ["recentThreads"] })
          queryClient.invalidateQueries({ queryKey: ["thread", agentId, threadId] })
          activeAssistantId.current = null
          break
        }
        case "error":
          updateAssistant((turn) => ({
            ...turn,
            status: "error",
            error: event.data,
          }))
          activeAssistantId.current = null
          break
      }
    },
    [agentId, queryClient, threadId, updateAssistant],
  )

  const { send, isStreaming } = useThreadStream({
    agentId,
    threadId,
    onEvent: handleEvent,
  })

  const handleSend = (message: string, attachedFiles: string[]) => {
    const assistantId = `assistant-${Date.now()}`
    activeAssistantId.current = assistantId

    setTurns((prev) => [
      ...prev,
      { id: `user-${Date.now()}`, role: "user", text: message },
      {
        id: assistantId,
        role: "assistant",
        text: "",
        reasoning: "",
        toolCalls: [],
        status: "streaming",
      },
    ])

    send({
      message,
      model: DEFAULT_MODEL,
      attached_files: attachedFiles,
      file_read_mode: "reference",
    })
  }

  const handleStop = () => {
    ThreadsService.stopStreamThreadConversation({ agentId, threadId }).catch(() => {
      // If the thread already finished, the backend 400s — nothing to do.
    })
  }

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col overflow-hidden rounded-xl border">
      <ChatHeader agent={agent} thread={thread} profilePictureLink={profilePictureLink} />
      <ChatTranscript
        turns={turns}
        agent={agent}
        profilePictureLink={profilePictureLink}
      />
      <ChatComposer
        agentId={agentId}
        threadId={threadId}
        isStreaming={isStreaming}
        onSend={handleSend}
        onStop={handleStop}
      />
    </div>
  )
}

function ChatPage({ agentId, threadId }: { agentId: string; threadId: string }) {
  return (
    <Suspense fallback={<ChatPageSkeleton />}>
      <ChatPageContent agentId={agentId} threadId={threadId} />
    </Suspense>
  )
}
