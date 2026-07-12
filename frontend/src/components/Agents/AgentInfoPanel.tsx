import { useQuery } from "@tanstack/react-query"
import { Bot, FileText, Globe, Lock, Wrench } from "lucide-react"

import { AgentsService, type AgentPublic } from "@/client"
import AgentInfoSection from "@/components/Agents/AgentInfoSection"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { getInitials } from "@/utils"

interface AgentInfoPanelProps {
  agent: AgentPublic
}

const AgentInfoPanel = ({ agent }: AgentInfoPanelProps) => {
  const { data: profilePictureLink } = useQuery({
    queryKey: ["profilePicture", agent.id],
    queryFn: async () => {
      const res = await AgentsService.getProfilePicture({ agentId: agent.id })
      return res as string
    },
    retry: false,
  })

  const { data: skillNames } = useQuery({
    queryKey: ["agentSkills", agent.id],
    queryFn: async () => {
      const res = (await AgentsService.getSkillNames({
        agentId: agent.id,
      })) as { skill_names: string[] }
      return res.skill_names
    },
  })

  const tools = agent.tools_config ?? []

  return (
    <div className="flex flex-col gap-4 rounded-xl border p-6">
      <div className="flex items-start gap-4">
        <Avatar className="size-14">
          {profilePictureLink ? (
            <AvatarImage src={profilePictureLink} alt={agent.name} />
          ) : null}
          <AvatarFallback className="bg-zinc-600 text-white">
            {agent.name ? getInitials(agent.name) : <Bot className="size-5" />}
          </AvatarFallback>
        </Avatar>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="truncate text-xl font-semibold">{agent.name}</h1>
            <Badge variant={agent.is_public ? "secondary" : "outline"}>
              {agent.is_public ? (
                <Globe className="size-3" />
              ) : (
                <Lock className="size-3" />
              )}
              {agent.is_public ? "Public" : "Private"}
            </Badge>
          </div>
          <p
            className={
              agent.description
                ? "text-sm text-muted-foreground"
                : "text-sm text-muted-foreground italic"
            }
          >
            {agent.description || "No description"}
          </p>
        </div>
      </div>

      <div className="flex flex-col">
        <AgentInfoSection title="System Prompt" defaultOpen>
          {agent.system_prompt ? (
            <p className="whitespace-pre-wrap rounded-md bg-muted/50 p-3 text-sm text-muted-foreground">
              {agent.system_prompt}
            </p>
          ) : (
            <p className="text-sm text-muted-foreground italic">
              No system prompt set
            </p>
          )}
        </AgentInfoSection>

        <AgentInfoSection title="Tools" defaultOpen>
          {tools.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {tools.map((tool) => (
                <Badge key={tool} variant="secondary" className="gap-1">
                  <Wrench className="size-3" />
                  {tool}
                </Badge>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground italic">
              No tools configured
            </p>
          )}
        </AgentInfoSection>

        <AgentInfoSection title="Skill Files">
          {skillNames && skillNames.length > 0 ? (
            <div className="flex flex-col gap-1.5">
              {skillNames.map((skill) => (
                <div
                  key={skill}
                  className="flex items-center gap-2 rounded-md border px-2 py-1.5 text-sm"
                >
                  <FileText className="size-4 shrink-0 text-muted-foreground" />
                  <span className="truncate">{skill}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground italic">
              No skill files uploaded
            </p>
          )}
        </AgentInfoSection>

        <AgentInfoSection title="Details">
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-sm">
            <dt className="text-muted-foreground">Owner</dt>
            <dd className="truncate">{agent.owner_name || "—"}</dd>
            <dt className="text-muted-foreground">Created</dt>
            <dd>
              {agent.created_at
                ? new Date(agent.created_at).toLocaleDateString()
                : "—"}
            </dd>
            <dt className="text-muted-foreground">Agent ID</dt>
            <dd className="truncate font-mono text-xs">{agent.id}</dd>
          </dl>
        </AgentInfoSection>
      </div>
    </div>
  )
}

export default AgentInfoPanel
