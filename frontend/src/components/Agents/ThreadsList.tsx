import { useSuspenseQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { MessageSquare, MessagesSquare } from "lucide-react"

import { ThreadsService } from "@/client"
import ThreadActionsMenu from "@/components/Agents/ThreadActionsMenu"

function getThreadsQueryOptions(agentId: string) {
  return {
    queryFn: () => ThreadsService.readThreads({ agentId, skip: 0, limit: 100 }),
    queryKey: ["threads", agentId],
  }
}

function formatLastModified(lastModified: string | null | undefined) {
  if (!lastModified) return "—"
  return new Date(lastModified).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  })
}

interface ThreadsListProps {
  agentId: string
}

const ThreadsList = ({ agentId }: ThreadsListProps) => {
  const { data: threads } = useSuspenseQuery(getThreadsQueryOptions(agentId))

  if (threads.data.length === 0) {
    return (
      <div className="flex min-h-[40vh] flex-col items-center justify-center gap-3 rounded-xl border border-dashed text-center">
        <div className="rounded-full bg-muted p-4">
          <MessagesSquare className="size-8 text-muted-foreground" />
        </div>
        <div>
          <h3 className="font-semibold">No threads yet</h3>
          <p className="text-sm text-muted-foreground">
            Create a thread to start a conversation with this agent
          </p>
        </div>
      </div>
    )
  }

  const sorted = [...threads.data].sort((a, b) =>
    (b.last_modified ?? "").localeCompare(a.last_modified ?? ""),
  )

  return (
    <div className="flex flex-col divide-y rounded-xl border">
      {sorted.map((thread) => (
        <Link
          key={thread.id}
          to="/threads/$agentId/$threadId"
          params={{ agentId, threadId: thread.id }}
          className="flex items-center gap-3 px-4 py-3 hover:bg-muted/50"
        >
          <MessageSquare className="size-4 shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1 truncate font-medium">
            {thread.name}
          </span>
          <span className="shrink-0 text-sm text-muted-foreground">
            {formatLastModified(thread.last_modified)}
          </span>
          <ThreadActionsMenu thread={thread} />
        </Link>
      ))}
    </div>
  )
}

export default ThreadsList
