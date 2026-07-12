import { EllipsisVertical } from "lucide-react"
import { useState } from "react"

import type { ThreadPublic } from "@/client"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import DeleteThread from "@/components/Agents/DeleteThread"
import RenameThread from "@/components/Agents/RenameThread"

interface ThreadActionsMenuProps {
  thread: ThreadPublic
}

const ThreadActionsMenu = ({ thread }: ThreadActionsMenuProps) => {
  const [open, setOpen] = useState(false)

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          onClick={(e) => e.stopPropagation()}
        >
          <EllipsisVertical />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
        <RenameThread thread={thread} onSuccess={() => setOpen(false)} />
        <DeleteThread thread={thread} onSuccess={() => setOpen(false)} />
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export default ThreadActionsMenu
