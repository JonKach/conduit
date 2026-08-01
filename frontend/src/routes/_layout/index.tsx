import { useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Bot } from "lucide-react"
import { Suspense } from "react"

import { AgentsService } from "@/client"
import AddAgent from "@/components/Agents/AddAgent"
import AgentCard from "@/components/Agents/AgentCard"
import PublicAgentCard from "@/components/Agents/PublicAgentCard"
import PendingAgents from "@/components/Pending/PendingAgents"
import useAuth from "@/hooks/useAuth"

function getAgentsQueryOptions() {
  return {
    queryFn: () => AgentsService.readAgents({ skip: 0, limit: 100 }),
    queryKey: ["agents"],
  }
}

function getAddedAgentsQueryOptions() {
  return {
    queryFn: () => AgentsService.readAddedPublicAgents({ skip: 0, limit: 100 }),
    queryKey: ["addedPublicAgents"],
  }
}

export const Route = createFileRoute("/_layout/")({
  component: Dashboard,
  head: () => ({
    meta: [
      {
        title: "Dashboard - Conduit",
      },
    ],
  }),
})

function DashboardContent({ heading }: { heading: string }) {
  const { data: agents } = useSuspenseQuery(getAgentsQueryOptions())
  const { data: addedAgents } = useSuspenseQuery(getAddedAgentsQueryOptions())

  const hasOwned = agents.data.length > 0
  const hasAdded = addedAgents.data.length > 0

  if (!hasOwned && !hasAdded) {
    return (
      <div className="flex min-h-[70vh] flex-col items-center justify-center gap-4 text-center">
        <div className="rounded-full bg-muted p-4">
          <Bot className="h-8 w-8 text-muted-foreground" />
        </div>
        <div>
          <h2 className="text-lg font-semibold">
            You don't have any agents yet
          </h2>
          <p className="text-muted-foreground">
            Create your first agent, or add one from the Marketplace
          </p>
        </div>
        <AddAgent variant="hero" />
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col gap-8">
      <div className="flex flex-col gap-6">
        <div className="flex items-center justify-between">
          <h1 className="max-w-sm truncate text-2xl">{heading}</h1>
          <AddAgent />
        </div>
        {hasOwned ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {agents.data.map((agent) => (
              <AgentCard key={agent.id} agent={agent} />
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground italic">
            You don't have any agents of your own yet.
          </p>
        )}
      </div>

      {hasAdded && (
        <div className="flex flex-col gap-6 border-t pt-6">
          <div>
            <h2 className="text-xl font-semibold">Added Agents</h2>
            <p className="text-sm text-muted-foreground">
              Public agents you've added from the Marketplace
            </p>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {addedAgents.data.map((agent) => (
              <PublicAgentCard key={agent.id} agent={agent} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function Dashboard() {
  const { user: currentUser } = useAuth()
  const heading = `${currentUser?.full_name || currentUser?.email}'s Agents`

  return (
    <Suspense fallback={<PendingAgents />}>
      <DashboardContent heading={heading} />
    </Suspense>
  )
}
