import { useQuery } from "@tanstack/react-query"
import { Eye, Loader2 } from "lucide-react"
import { useState } from "react"

import { AgentsService } from "@/client"
import Markdown from "@/components/Chat/Markdown"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"

interface ViewSkillDialogProps {
  agentId: string
  skillName: string
}

/**
 * Preview a single skill's extracted content, per skill row in EditAgent.
 *
 * Nested inside the already-open EditAgent dialog (Radix portals both to
 * document.body, so this doesn't actually nest in the DOM). The trigger must
 * stay `type="button"` since the row lives inside EditAgent's <form>.
 */
const ViewSkillDialog = ({ agentId, skillName }: ViewSkillDialogProps) => {
  const [open, setOpen] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ["agentSkill", agentId, skillName],
    queryFn: async () => {
      const res = (await AgentsService.getSkillContent({
        agentId,
        skillName,
      })) as { skill_name: string; content: string }
      return res
    },
    enabled: open,
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <button
          type="button"
          className="shrink-0 rounded-full p-0.5 hover:bg-muted-foreground/20"
        >
          <Eye className="size-3.5" />
          <span className="sr-only">View {skillName}</span>
        </button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="truncate">{skillName}</DialogTitle>
          <DialogDescription>
            Extracted content for this skill file.
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-[60vh] overflow-y-auto rounded-md border bg-muted/30 p-3">
          {isLoading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              Loading…
            </div>
          ) : data?.content ? (
            <Markdown content={data.content} />
          ) : (
            <p className="text-sm text-muted-foreground italic">
              This skill has no readable content.
            </p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

export default ViewSkillDialog
