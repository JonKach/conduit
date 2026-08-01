import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { FileText, Loader2, Paperclip, Trash2 } from "lucide-react"
import { useState } from "react"

import { ThreadsService } from "@/client"
import { fileNameFromPath } from "@/components/Chat/chatTurns"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

interface ThreadFilesDialogProps {
  agentId: string
  threadId: string
}

/**
 * Every file ever uploaded to this thread, in one place, deletable.
 *
 * This replaces the old behavior where ChatComposer re-staged every thread
 * file into the composer on load, making it look like the user had just
 * attached a dozen files to their next message. Files now live only here;
 * the composer only ever holds what was uploaded in the current session.
 */
const ThreadFilesDialog = ({ agentId, threadId }: ThreadFilesDialogProps) => {
  const [isOpen, setIsOpen] = useState(false)
  const queryClient = useQueryClient()
  const { showErrorToast } = useCustomToast()

  const { data: files, isLoading } = useQuery({
    queryKey: ["threadFiles", agentId, threadId],
    queryFn: async () => {
      const res = (await ThreadsService.listFiles({ agentId, threadId })) as {
        files: string[]
      }
      return res.files
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (path: string) =>
      ThreadsService.deleteFile({
        agentId,
        threadId,
        filePath: fileNameFromPath(path),
      }),
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["threadFiles", agentId, threadId],
      })
    },
  })

  const count = files?.length ?? 0

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm" className="gap-1.5">
          <Paperclip />
          Files{count > 0 ? ` (${count})` : ""}
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Conversation Files</DialogTitle>
          <DialogDescription>
            Files uploaded to this thread. Deleting one removes it from storage
            and from what the agent can read going forward.
          </DialogDescription>
        </DialogHeader>
        <div className="flex max-h-80 flex-col gap-1.5 overflow-y-auto">
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : count === 0 ? (
            <p className="text-sm text-muted-foreground italic">
              No files in this conversation.
            </p>
          ) : (
            files?.map((path) => {
              const isDeleting =
                deleteMutation.isPending && deleteMutation.variables === path
              return (
                <div
                  key={path}
                  className="flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-sm"
                >
                  <FileText className="size-4 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1 truncate">
                    {fileNameFromPath(path)}
                  </span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    className="shrink-0 text-muted-foreground hover:text-destructive"
                    disabled={isDeleting}
                    onClick={() => deleteMutation.mutate(path)}
                  >
                    {isDeleting ? (
                      <Loader2 className="animate-spin" />
                    ) : (
                      <Trash2 />
                    )}
                  </Button>
                </div>
              )
            })
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

export default ThreadFilesDialog
