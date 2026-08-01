import { EllipsisVertical, Pencil } from "lucide-react"
import { useState } from "react"

import type { AgentPublic } from "@/client"
import DeleteAgent from "@/components/Agents/DeleteAgent"
import EditAgent from "@/components/Agents/EditAgent"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

interface AgentActionsMenuProps {
  agent: AgentPublic
}

const AgentActionsMenu = ({ agent }: AgentActionsMenuProps) => {
  const [menuOpen, setMenuOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)

  return (
    <>
      <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon">
            <EllipsisVertical />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem
            onSelect={(e) => e.preventDefault()}
            onClick={() => {
              setMenuOpen(false)
              setEditOpen(true)
            }}
          >
            <Pencil />
            Edit
          </DropdownMenuItem>
          <DeleteAgent agent={agent} onSuccess={() => setMenuOpen(false)} />
        </DropdownMenuContent>
      </DropdownMenu>
      {/*
        Rendered OUTSIDE the DropdownMenu on purpose: this dialog contains a
        file input. Opening the native OS file picker blurs the whole
        document, which the DropdownMenu reads as an outside interaction and
        closes on -- and closing it would unmount everything nested inside
        its content, including this dialog mid-edit. Keeping it as a
        sibling means the dropdown closing has no effect on it.
      */}
      <EditAgent agent={agent} open={editOpen} onOpenChange={setEditOpen} />
    </>
  )
}

export default AgentActionsMenu
