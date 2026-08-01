import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { FileText, ImagePlus, Plus, Upload, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { AgentsService, UtilsService } from "@/client"
import {
  ALLOWED_IMAGE_TYPES,
  ALLOWED_SKILL_EXTENSIONS,
  fileExtension,
  formatFileSize,
  MAX_IMAGE_SIZE,
  MAX_SKILL_FILE_SIZE,
  toSkillName,
} from "@/components/Agents/agentFiles"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"
import { ExpandingInput } from "../ui/expanding-input"

const formSchema = z.object({
  name: z.string().min(1, { message: "Name is required" }),
  description: z.string().optional(),
  system_prompt: z.string().min(1, { message: "System prompt is required" }),
  tools_config: z.array(z.string()),
  is_public: z.boolean(),
})

type FormData = z.infer<typeof formSchema>

interface AddAgentProps {
  variant?: "default" | "hero"
}

const AddAgent = ({ variant = "default" }: AddAgentProps) => {
  const [isOpen, setIsOpen] = useState(false)
  const [pendingTool, setPendingTool] = useState("")
  const [profilePicture, setProfilePicture] = useState<File | null>(null)
  const [profilePreview, setProfilePreview] = useState<string | null>(null)
  const [skillFiles, setSkillFiles] = useState<File[]>([])
  const profilePictureInputRef = useRef<HTMLInputElement>(null)
  const skillFilesInputRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  useEffect(() => {
    return () => {
      if (profilePreview) URL.revokeObjectURL(profilePreview)
    }
  }, [profilePreview])

  const { data: availableTools } = useQuery({
    queryKey: ["tools"],
    queryFn: () => UtilsService.getTools(),
    enabled: isOpen,
  })

  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      name: "",
      description: "",
      system_prompt: "",
      tools_config: [],
      is_public: false,
    },
  })

  const resetLocalState = () => {
    form.reset()
    setProfilePicture(null)
    setProfilePreview(null)
    setSkillFiles([])
    setPendingTool("")
  }

  const mutation = useMutation({
    mutationFn: async (data: FormData) => {
      const agent = await AgentsService.createAgent({
        requestBody: {
          name: data.name,
          description: data.description,
          system_prompt: data.system_prompt,
          tools_config: data.tools_config,
          is_public: data.is_public,
        },
      })

      if (profilePicture) {
        await AgentsService.uploadProfilePicture({
          agentId: agent.id,
          contentLength: profilePicture.size,
          formData: { file: profilePicture },
        })
      }

      for (const file of skillFiles) {
        await AgentsService.uploadSkill({
          agentId: agent.id,
          contentLength: file.size,
          formData: { file, skill_name: toSkillName(file.name) },
        })
      }

      return agent
    },
    onSuccess: () => {
      showSuccessToast("Agent created successfully")
      resetLocalState()
      setIsOpen(false)
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["agents"] })
    },
  })

  const onSubmit = (data: FormData) => {
    mutation.mutate(data)
  }

  const handleProfilePictureChange = (
    e: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const file = e.target.files?.[0]
    e.target.value = ""
    if (!file) return

    if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
      showErrorToast("Only JPG, PNG, and GIF images are allowed.")
      return
    }
    if (file.size > MAX_IMAGE_SIZE) {
      showErrorToast("Image must be 5 MB or smaller.")
      return
    }

    if (profilePreview) URL.revokeObjectURL(profilePreview)
    setProfilePicture(file)
    setProfilePreview(URL.createObjectURL(file))
  }

  const handleRemoveProfilePicture = () => {
    if (profilePreview) URL.revokeObjectURL(profilePreview)
    setProfilePicture(null)
    setProfilePreview(null)
  }

  const handleSkillFilesChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    e.target.value = ""

    const existingNames = new Set(skillFiles.map((f) => f.name))
    const valid: File[] = []
    for (const file of files) {
      if (existingNames.has(file.name)) continue
      if (!ALLOWED_SKILL_EXTENSIONS.includes(fileExtension(file.name))) {
        showErrorToast(
          `${file.name}: only .md, .txt, .pdf, and .docx files are allowed.`,
        )
        continue
      }
      if (file.size > MAX_SKILL_FILE_SIZE) {
        showErrorToast(`${file.name}: file must be 2 MB or smaller.`)
        continue
      }
      valid.push(file)
    }
    if (valid.length > 0) setSkillFiles((prev) => [...prev, ...valid])
  }

  const handleRemoveSkillFile = (name: string) => {
    setSkillFiles((prev) => prev.filter((f) => f.name !== name))
  }

  return (
    <Dialog
      open={isOpen}
      onOpenChange={(open) => {
        setIsOpen(open)
        if (!open) resetLocalState()
      }}
    >
      <DialogTrigger asChild>
        {variant === "hero" ? (
          <Button size="lg">
            <Plus className="mr-2" />
            Create your first agent
          </Button>
        ) : (
          <Button>
            <Plus className="mr-2" />
            Create Agent
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="top-4 max-h-[calc(100%-2rem)] translate-y-0 overflow-y-auto sm:max-w-lg sm:top-[50%] sm:max-h-[85vh] sm:translate-y-[-50%] lg:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Agent Designer</DialogTitle>
          <DialogDescription>
            Fill in the details to create a new agent.
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)}>
            <div className="grid gap-6 py-4">
              <div className="flex items-center gap-4">
                <Avatar className="size-16">
                  {profilePreview && <AvatarImage src={profilePreview} />}
                  <AvatarFallback className="bg-zinc-600 text-white">
                    <ImagePlus className="size-5" />
                  </AvatarFallback>
                </Avatar>
                <div className="flex flex-col gap-1.5">
                  <input
                    ref={profilePictureInputRef}
                    type="file"
                    accept="image/jpeg,image/png,image/gif"
                    className="hidden"
                    onChange={handleProfilePictureChange}
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => profilePictureInputRef.current?.click()}
                  >
                    {profilePicture ? "Change photo" : "Upload photo"}
                  </Button>
                  {profilePicture && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="text-muted-foreground"
                      onClick={handleRemoveProfilePicture}
                    >
                      Remove photo
                    </Button>
                  )}
                </div>
              </div>

              <div className="grid gap-y-4 gap-x-6 lg:grid-cols-2">
                {/* ROW 1 */}
                <FormField
                  control={form.control}
                  name="name"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>
                        Name <span className="text-destructive">*</span>
                      </FormLabel>
                      <FormControl>
                        <Input
                          placeholder="Name"
                          type="text"
                          {...field}
                          required
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="system_prompt"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>
                        System Prompt{" "}
                        <span className="text-destructive">*</span>
                      </FormLabel>
                      <FormControl>
                        <ExpandingInput
                          placeholder="You are a helpful assistant that..."
                          {...field}
                          required
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                {/* ROW 2 */}
                <FormField
                  control={form.control}
                  name="description"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Description</FormLabel>
                      <FormControl>
                        <ExpandingInput placeholder="Description" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="tools_config"
                  render={({ field }) => {
                    // ... (Keep your existing tools_config logic here)
                    const selectedTools = field.value ?? []
                    const selectableTools = (availableTools ?? []).filter(
                      (tool) => !selectedTools.includes(tool),
                    )

                    return (
                      <FormItem>
                        <FormLabel>Tools</FormLabel>
                        <FormControl>
                          <Select
                            value={pendingTool}
                            onValueChange={(tool) => {
                              field.onChange([...selectedTools, tool])
                              setPendingTool("")
                            }}
                          >
                            <SelectTrigger className="w-full">
                              <SelectValue placeholder="Add a tool..." />
                            </SelectTrigger>
                            <SelectContent>
                              {selectableTools.length === 0 ? (
                                <div className="px-2 py-1.5 text-sm text-muted-foreground">
                                  No more tools available
                                </div>
                              ) : (
                                selectableTools.map((tool) => (
                                  <SelectItem key={tool} value={tool}>
                                    {tool}
                                  </SelectItem>
                                ))
                              )}
                            </SelectContent>
                          </Select>
                        </FormControl>
                        {selectedTools.length > 0 && (
                          <div className="flex flex-wrap gap-1.5 pt-1">
                            {selectedTools.map((tool) => (
                              <Badge
                                key={tool}
                                variant="secondary"
                                className="gap-1 pr-1"
                              >
                                {tool}
                                <button
                                  type="button"
                                  onClick={() =>
                                    field.onChange(
                                      selectedTools.filter((t) => t !== tool),
                                    )
                                  }
                                  className="rounded-full hover:bg-muted-foreground/20"
                                >
                                  <X className="size-3" />
                                  <span className="sr-only">Remove {tool}</span>
                                </button>
                              </Badge>
                            ))}
                          </div>
                        )}
                        <FormMessage />
                      </FormItem>
                    )
                  }}
                />

                {/* ROW 3 */}
                <FormField
                  control={form.control}
                  name="is_public"
                  render={({ field }) => (
                    <FormItem className="flex items-center gap-3 space-y-0 h-full pt-6">
                      <FormControl>
                        <Checkbox
                          checked={field.value}
                          onCheckedChange={field.onChange}
                        />
                      </FormControl>
                      <FormLabel className="font-normal m-0 pb-1">
                        Make this agent public
                      </FormLabel>
                    </FormItem>
                  )}
                />

                <FormItem>
                  <FormLabel>Skill Files</FormLabel>
                  <input
                    ref={skillFilesInputRef}
                    type="file"
                    accept=".md,.txt,.pdf,.docx"
                    multiple
                    className="hidden"
                    onChange={handleSkillFilesChange}
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="w-fit block"
                    onClick={() => skillFilesInputRef.current?.click()}
                  >
                    <Upload className="size-4 mr-2 inline" />
                    Upload skill files
                  </Button>
                  {skillFiles.length > 0 && (
                    <div className="grid gap-1.5 pt-1">
                      {skillFiles.map((file) => (
                        <div
                          key={file.name}
                          className="flex items-center justify-between gap-2 rounded-md border px-2 py-1.5 text-sm"
                        >
                          <div className="flex min-w-0 items-center gap-2">
                            <FileText className="size-4 shrink-0 text-muted-foreground" />
                            <span className="truncate">{file.name}</span>
                            <span className="shrink-0 text-xs text-muted-foreground">
                              {formatFileSize(file.size)}
                            </span>
                          </div>
                          <button
                            type="button"
                            onClick={() => handleRemoveSkillFile(file.name)}
                            className="shrink-0 rounded-full p-0.5 hover:bg-muted-foreground/20"
                          >
                            <X className="size-3.5" />
                            <span className="sr-only">Remove {file.name}</span>
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </FormItem>
              </div>
            </div>

            <DialogFooter className="mt-6">
              <DialogClose asChild>
                <Button variant="outline" disabled={mutation.isPending}>
                  Cancel
                </Button>
              </DialogClose>
              <LoadingButton type="submit" loading={mutation.isPending}>
                Save
              </LoadingButton>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}

export default AddAgent
