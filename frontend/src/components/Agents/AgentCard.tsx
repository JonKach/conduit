import { useQuery } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { Bot } from "lucide-react"
import { type AgentPublic, AgentsService } from "@/client"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { getInitials } from "@/utils"

interface AgentCardProps {
  agent: AgentPublic
}

const AgentCard = ({ agent }: AgentCardProps) => {
  const navigate = useNavigate()

  const { data: profilePictureLink } = useQuery({
    queryKey: ["profilePicture", agent.id],
    queryFn: async () => {
      const res = await AgentsService.getProfilePicture({ agentId: agent.id })
      return res as string
    },
    retry: false,
  })

  return (
    <Card
      className="h-full gap-3 py-4 transition-colors hover:outline-2 hover:outline-zinc-300 dark:hover:outline-zinc-700 cursor-pointer"
      onClick={() => navigate({ to: `/agents/${agent.id}` })}
    >
      <CardHeader className="px-4">
        <div className="flex items-start justify-between gap-2">
          <Avatar className="size-10">
            {profilePictureLink ? (
              <AvatarImage src={profilePictureLink} alt={agent.name} />
            ) : null}
            <AvatarFallback className="bg-zinc-600 text-white">
              {agent.name ? (
                getInitials(agent.name)
              ) : (
                <Bot className="size-4" />
              )}
            </AvatarFallback>
          </Avatar>
          {agent.is_public && (
            <Badge variant="secondary" className="shrink-0">
              Public
            </Badge>
          )}
        </div>
        <CardTitle className="truncate pt-1 text-base">{agent.name}</CardTitle>
        <CardDescription
          className={agent.description ? "line-clamp-2" : "italic"}
        >
          {agent.description || "No description"}
        </CardDescription>
      </CardHeader>
    </Card>
  )
}

export default AgentCard
