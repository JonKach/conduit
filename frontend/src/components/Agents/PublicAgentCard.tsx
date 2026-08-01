import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { Bot, Check, Loader2, Plus, Users } from "lucide-react"

import { type AgentPublic, AgentsService } from "@/client"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import useCustomToast from "@/hooks/useCustomToast"
import { getInitials, handleError } from "@/utils"

interface PublicAgentCardProps {
  agent: AgentPublic
}

/**
 * A marketplace listing card. Also reused on the "My Agents" page's "Added
 * Agents" section, where every card is already added -- the Add/Remove
 * button toggles off the same `is_added` state either way.
 */
const PublicAgentCard = ({ agent }: PublicAgentCardProps) => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showErrorToast } = useCustomToast()

  const { data: profilePictureLink } = useQuery({
    queryKey: ["profilePicture", agent.id],
    queryFn: async () => {
      const res = await AgentsService.getProfilePicture({ agentId: agent.id })
      return res as string
    },
    retry: false,
  })

  const invalidateAddedLists = () => {
    queryClient.invalidateQueries({ queryKey: ["publicAgents"] })
    queryClient.invalidateQueries({ queryKey: ["addedPublicAgents"] })
  }

  const addMutation = useMutation({
    mutationFn: () =>
      AgentsService.addPublicAgent({ requestBody: { agent_id: agent.id } }),
    onError: handleError.bind(showErrorToast),
    onSettled: invalidateAddedLists,
  })

  const removeMutation = useMutation({
    mutationFn: () => AgentsService.removePublicAgent({ agentId: agent.id }),
    onError: handleError.bind(showErrorToast),
    onSettled: invalidateAddedLists,
  })

  const isPending = addMutation.isPending || removeMutation.isPending

  const handleToggle = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (agent.is_added) {
      removeMutation.mutate()
    } else {
      addMutation.mutate()
    }
  }

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
          {typeof agent.added_count === "number" && (
            <Badge variant="secondary" className="shrink-0 gap-1">
              <Users className="size-3" />
              {agent.added_count}
            </Badge>
          )}
        </div>
        <CardTitle className="truncate pt-1 text-base">{agent.name}</CardTitle>
        {agent.owner_name ? (
          <p className="truncate text-xs text-muted-foreground">
            by {agent.owner_name}
          </p>
        ) : null}
        <CardDescription
          className={agent.description ? "line-clamp-2" : "italic"}
        >
          {agent.description || "No description"}
        </CardDescription>
      </CardHeader>
      <CardFooter className="px-4">
        {agent.is_owner ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="w-full text-muted-foreground"
            disabled
          >
            Owned
          </Button>
        ) : (
          <Button
            type="button"
            variant={agent.is_added ? "secondary" : "outline"}
            size="sm"
            className="w-full"
            disabled={isPending}
            onClick={handleToggle}
          >
            {isPending ? (
              <Loader2 className="animate-spin" />
            ) : agent.is_added ? (
              <Check />
            ) : (
              <Plus />
            )}
            {agent.is_added ? "Added" : "Add"}
          </Button>
        )}
      </CardFooter>
    </Card>
  )
}

export default PublicAgentCard
