import { useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { ArrowLeft } from "lucide-react"
import { Suspense } from "react"
import { AgentsService } from "@/client"
import AgentInfoPanel from "@/components/Agents/AgentInfoPanel"
import CreateThread from "@/components/Agents/CreateThread"
import ThreadsList from "@/components/Agents/ThreadsList"
import PendingThreads from "@/components/Pending/PendingThreads"
import { Skeleton } from "@/components/ui/skeleton"

function getAgentQueryOptions(agentId: string) {
  return {
    queryFn: () => AgentsService.readAgent({ agentId }),
    queryKey: ["agent", agentId],
  }
}

export const Route = createFileRoute("/_layout/agents/$agentId")({
  component: AgentDetail,
})

function AgentDetailContent({ agentId }: { agentId: string }) {
  const { data: agent } = useSuspenseQuery(getAgentQueryOptions(agentId))
  const navigate = useNavigate()

  return (
    <>
      <ArrowLeft
        className="size-6 text-muted-foreground hover:text-foreground cursor-pointer"
        onClick={() => navigate({ to: "/" })}
      />
      <div className="flex flex-1 flex-col gap-6 lg:flex-row mt-5">
        <div className="lg:w-96 lg:shrink-0">
          <AgentInfoPanel agent={agent} />
        </div>
        <div className="flex flex-1 flex-col gap-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">Threads</h2>
            <CreateThread agentId={agentId} />
          </div>
          <Suspense fallback={<PendingThreads />}>
            <ThreadsList agentId={agentId} />
          </Suspense>
        </div>
      </div>
    </>
  )
}

function AgentDetailSkeleton() {
  return (
    <div className="flex flex-1 flex-col gap-6 lg:flex-row">
      <div className="flex flex-col gap-4 rounded-xl border p-6 lg:w-96 lg:shrink-0">
        <div className="flex items-start gap-4">
          <Skeleton className="size-14 rounded-full" />
          <div className="flex flex-1 flex-col gap-2 pt-1">
            <Skeleton className="h-5 w-32" />
            <Skeleton className="h-4 w-full" />
          </div>
        </div>
        <div className="flex flex-col gap-3 border-t pt-3">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-4 w-24" />
        </div>
      </div>
      <div className="flex flex-1 flex-col gap-4">
        <div className="flex items-center justify-between">
          <Skeleton className="h-6 w-24" />
          <Skeleton className="h-9 w-32" />
        </div>
        <PendingThreads />
      </div>
    </div>
  )
}

function AgentDetail() {
  const { agentId } = Route.useParams()

  return (
    <Suspense fallback={<AgentDetailSkeleton />}>
      <AgentDetailContent agentId={agentId} />
    </Suspense>
  )
}
