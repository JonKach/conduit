import { useQueryClient } from "@tanstack/react-query"
import { Loader2, Paperclip, Send, Square, X } from "lucide-react"
import { useRef, useState } from "react"

import { ThreadsService } from "@/client"
import { fileNameFromPath } from "@/components/Chat/chatTurns"
import {
  Attachment,
  AttachmentAction,
  AttachmentActions,
  AttachmentContent,
  AttachmentDescription,
  AttachmentGroup,
  AttachmentMedia,
  AttachmentTitle,
} from "@/components/ui/attachment"
import { Button } from "@/components/ui/button"
import { ExpandingInput } from "@/components/ui/expanding-input"
import useCustomToast from "@/hooks/useCustomToast"

interface StagedFile {
  path: string
  name: string
  state: "uploading" | "done" | "error"
}

interface ChatComposerProps {
  agentId: string
  threadId: string
  isStreaming: boolean
  onSend: (message: string, attachedFiles: string[]) => void
  onStop: () => void
}

const ChatComposer = ({
  agentId,
  threadId,
  isStreaming,
  onSend,
  onStop,
}: ChatComposerProps) => {
  const [text, setText] = useState("")
  // Files staged in this session only; earlier uploads live in ThreadFilesDialog.
  const [stagedFiles, setStagedFiles] = useState<StagedFile[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()
  const { showErrorToast } = useCustomToast()

  const invalidateThreadFiles = () =>
    queryClient.invalidateQueries({
      queryKey: ["threadFiles", agentId, threadId],
    })

  const handleFilesSelected = async (files: FileList | null) => {
    if (!files || files.length === 0) return

    for (const file of Array.from(files)) {
      const placeholder: StagedFile = {
        path: `pending:${file.name}:${Date.now()}`,
        name: file.name,
        state: "uploading",
      }
      setStagedFiles((prev) => [...prev, placeholder])

      try {
        const { path } = (await ThreadsService.upload({
          agentId,
          threadId,
          formData: { file },
          contentLength: file.size,
        })) as { path: string }

        setStagedFiles((prev) =>
          prev.map((f) =>
            f.path === placeholder.path
              ? { path, name: file.name, state: "done" }
              : f,
          ),
        )
        invalidateThreadFiles()
      } catch (_err) {
        setStagedFiles((prev) =>
          prev.map((f) =>
            f.path === placeholder.path ? { ...f, state: "error" } : f,
          ),
        )
        showErrorToast(`Failed to upload ${file.name}.`)
      }
    }
  }

  const handleRemoveFile = async (file: StagedFile) => {
    setStagedFiles((prev) => prev.filter((f) => f.path !== file.path))
    if (file.state === "done") {
      try {
        await ThreadsService.deleteFile({
          agentId,
          threadId,
          filePath: fileNameFromPath(file.path),
        })
      } catch {
        // File may already be gone; nothing actionable for the user here.
      } finally {
        invalidateThreadFiles()
      }
    }
  }

  const handleSend = () => {
    const trimmed = text.trim()
    if (!trimmed || isStreaming) return

    const attachedFiles = stagedFiles
      .filter((f) => f.state === "done")
      .map((f) => f.path)

    onSend(trimmed, attachedFiles)
    setText("")
    setStagedFiles([])
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="border-t bg-background px-4 py-3">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-2">
        {stagedFiles.length > 0 && (
          <AttachmentGroup>
            {stagedFiles.map((file) => (
              <Attachment key={file.path} size="sm" state={file.state}>
                <AttachmentMedia>
                  {file.state === "uploading" ? (
                    <Loader2 className="animate-spin" />
                  ) : (
                    <Paperclip />
                  )}
                </AttachmentMedia>
                <AttachmentContent>
                  <AttachmentTitle>{file.name}</AttachmentTitle>
                  <AttachmentDescription>
                    {file.state === "uploading"
                      ? "Uploading…"
                      : file.state === "error"
                        ? "Upload failed"
                        : "Attached"}
                  </AttachmentDescription>
                </AttachmentContent>
                <AttachmentActions>
                  <AttachmentAction onClick={() => handleRemoveFile(file)}>
                    <X />
                  </AttachmentAction>
                </AttachmentActions>
              </Attachment>
            ))}
          </AttachmentGroup>
        )}

        <div className="flex items-end gap-2">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => {
              handleFilesSelected(e.target.files)
              e.target.value = ""
            }}
          />
          <Button
            type="button"
            variant="outline"
            size="icon"
            onClick={() => fileInputRef.current?.click()}
          >
            <Paperclip />
          </Button>
          <ExpandingInput
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Send a message…"
            className="max-h-48"
          />
          {isStreaming ? (
            <Button
              type="button"
              variant="secondary"
              size="icon"
              onClick={onStop}
            >
              <Square className="fill-current" />
            </Button>
          ) : (
            <Button
              type="button"
              size="icon"
              disabled={!text.trim()}
              onClick={handleSend}
            >
              <Send />
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

export default ChatComposer
