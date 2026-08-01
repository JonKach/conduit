import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  FileText,
  ImagePlus,
  Loader2,
  Plus,
  Trash2,
  Upload,
  X,
} from "lucide-react"
import { useRef, useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { type AgentPublic, AgentsService, UtilsService } from "@/client"
import {
  ALLOWED_IMAGE_TYPES,
  ALLOWED_SKILL_EXTENSIONS,
  fileExtension,
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
} from "@/components/ui/dialog"
import { ExpandingInput } from "@/components/ui/expanding-input"
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
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

const formSchema = z.object({
  name: z.string().min(1, { message: "Name is required" }),
  description: z.string().optional(),
  system_prompt: z.string().min(1, { message: "System prompt is required" }),
  tools_config: z.array(z.string()),
  is_public: z.boolean(),
})

type FormData = z.infer<typeof formSchema>

interface EditAgentProps {
  agent: AgentPublic
  open: boolean
  onOpenChange: (open: boolean) => void
}

const EditAgent = ({ agent, open, onOpenChange }: EditAgentProps) => {
  const [toolsPopoverOpen, setToolsPopoverOpen] = useState(false)
  const skillFilesInputRef = useRef<HTMLInputElement>(null)
  const profilePictureInputRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      name: agent.name,
      description: agent.description ?? "",
      system_prompt: agent.system_prompt ?? "",
      tools_config: agent.tools_config ?? [],
      is_public: agent.is_public,
    },
  })

  const { data: availableTools } = useQuery({
    queryKey: ["tools"],
    queryFn: () => UtilsService.getTools(),
    enabled: open,
  })

  const { data: profilePictureLink, isLoading: profilePictureLoading } =
    useQuery({
      queryKey: ["profilePicture", agent.id],
      queryFn: async () => {
        const res = await AgentsService.getProfilePicture({
          agentId: agent.id,
        })
        return res as string
      },
      enabled: open,
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
    enabled: open,
  })

  const invalidateAgent = () => {
    queryClient.invalidateQueries({ queryKey: ["agent", agent.id] })
    queryClient.invalidateQueries({ queryKey: ["agents"] })
  }

  const updateMutation = useMutation({
    mutationFn: (data: FormData) =>
      AgentsService.updateAgent({
        agentId: agent.id,
        requestBody: {
          name: data.name,
          description: data.description,
          system_prompt: data.system_prompt,
          tools_config: data.tools_config,
          is_public: data.is_public,
        },
      }),
    onSuccess: () => {
      showSuccessToast("Agent updated successfully")
      onOpenChange(false)
    },
    onError: handleError.bind(showErrorToast),
    onSettled: invalidateAgent,
  })

  const profilePictureMutation = useMutation({
    mutationFn: (file: File) =>
      AgentsService.uploadProfilePicture({
        agentId: agent.id,
        contentLength: file.size,
        formData: { file },
      }),
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["profilePicture", agent.id] })
    },
  })

  const removeProfilePictureMutation = useMutation({
    mutationFn: () => AgentsService.deleteProfilePicture({ agentId: agent.id }),
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["profilePicture", agent.id] })
    },
  })

  const uploadSkillMutation = useMutation({
    mutationFn: (file: File) =>
      AgentsService.uploadSkill({
        agentId: agent.id,
        contentLength: file.size,
        formData: { file, skill_name: toSkillName(file.name) },
      }),
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["agentSkills", agent.id] })
    },
  })

  const deleteSkillMutation = useMutation({
    mutationFn: (skillName: string) =>
      AgentsService.deleteSkill({ agentId: agent.id, skillName }),
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["agentSkills", agent.id] })
    },
  })

  const onSubmit = (data: FormData) => {
    updateMutation.mutate(data)
  }

  const handleOpenChange = (nextOpen: boolean) => {
    onOpenChange(nextOpen)
    if (nextOpen) {
      form.reset({
        name: agent.name,
        description: agent.description ?? "",
        system_prompt: agent.system_prompt ?? "",
        tools_config: agent.tools_config ?? [],
        is_public: agent.is_public,
      })
    }
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
    profilePictureMutation.mutate(file)
  }

  const handleSkillFilesChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    e.target.value = ""

    const existingNames = new Set(skillNames ?? [])
    for (const file of files) {
      if (existingNames.has(`${toSkillName(file.name)}/SKILL.md`)) {
        showErrorToast(`${file.name}: a skill with that name already exists.`)
        continue
      }
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
      uploadSkillMutation.mutate(file)
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="top-4 max-h-[calc(100%-2rem)] translate-y-0 overflow-y-auto sm:max-w-lg sm:top-[50%] sm:max-h-[85vh] sm:translate-y-[-50%] lg:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Edit Agent</DialogTitle>
          <DialogDescription>
            Update this agent's configuration.
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)}>
            <div className="grid gap-6 py-4">
              <div className="flex items-center gap-4">
                <Avatar className="size-16">
                  {profilePictureLink ? (
                    <AvatarImage src={profilePictureLink} alt={agent.name} />
                  ) : null}
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
                    disabled={profilePictureMutation.isPending}
                    onClick={() => profilePictureInputRef.current?.click()}
                  >
                    {profilePictureMutation.isPending ? (
                      <Loader2 className="animate-spin" />
                    ) : null}
                    {profilePictureLink ? "Change photo" : "Upload photo"}
                  </Button>
                  {!profilePictureLoading && profilePictureLink && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="text-muted-foreground"
                      disabled={removeProfilePictureMutation.isPending}
                      onClick={() => removeProfilePictureMutation.mutate()}
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
                    const selectedTools = field.value ?? []
                    const selectableTools = (availableTools ?? []).filter(
                      (tool) => !selectedTools.includes(tool),
                    )

                    return (
                      <FormItem>
                        <FormLabel>Tools</FormLabel>
                        <FormControl>
                          <Popover
                            open={toolsPopoverOpen}
                            onOpenChange={setToolsPopoverOpen}
                          >
                            <PopoverTrigger asChild>
                              <Button type="button" variant="outline" size="sm">
                                <Plus />
                                Add tool
                              </Button>
                            </PopoverTrigger>
                            <PopoverContent align="start" className="w-56 p-1">
                              {selectableTools.length === 0 ? (
                                <div className="px-2 py-1.5 text-sm text-muted-foreground">
                                  No more tools available
                                </div>
                              ) : (
                                <div className="flex flex-col">
                                  {selectableTools.map((tool) => (
                                    <button
                                      key={tool}
                                      type="button"
                                      className="rounded-sm px-2 py-1.5 text-left text-sm hover:bg-accent hover:text-accent-foreground"
                                      onClick={() => {
                                        field.onChange([...selectedTools, tool])
                                        setToolsPopoverOpen(false)
                                      }}
                                    >
                                      {tool}
                                    </button>
                                  ))}
                                </div>
                              )}
                            </PopoverContent>
                          </Popover>
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
                    <FormItem className="flex flex-col gap-1.5 space-y-0 pt-2">
                      <div className="flex items-center gap-3">
                        <FormControl>
                          <Checkbox
                            checked={field.value}
                            disabled={agent.is_public}
                            onCheckedChange={field.onChange}
                          />
                        </FormControl>
                        <FormLabel className="font-normal m-0">
                          Make this agent public
                        </FormLabel>
                      </div>
                      {agent.is_public && (
                        <p className="text-xs text-muted-foreground">
                          Public agents can't be made private again.
                        </p>
                      )}
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
                    disabled={uploadSkillMutation.isPending}
                    onClick={() => skillFilesInputRef.current?.click()}
                  >
                    {uploadSkillMutation.isPending ? (
                      <Loader2 className="size-4 mr-2 inline animate-spin" />
                    ) : (
                      <Upload className="size-4 mr-2 inline" />
                    )}
                    Upload skill files
                  </Button>
                  {skillNames && skillNames.length > 0 && (
                    <div className="grid gap-1.5 pt-1">
                      {skillNames.map((skill) => {
                        const isDeleting =
                          deleteSkillMutation.isPending &&
                          deleteSkillMutation.variables === skill
                        return (
                          <div
                            key={skill}
                            className="flex items-center justify-between gap-2 rounded-md border px-2 py-1.5 text-sm"
                          >
                            <div className="flex min-w-0 items-center gap-2">
                              <FileText className="size-4 shrink-0 text-muted-foreground" />
                              <span className="truncate">{skill}</span>
                            </div>
                            <button
                              type="button"
                              disabled={isDeleting}
                              onClick={() => deleteSkillMutation.mutate(skill)}
                              className="shrink-0 rounded-full p-0.5 hover:bg-muted-foreground/20"
                            >
                              {isDeleting ? (
                                <Loader2 className="size-3.5 animate-spin" />
                              ) : (
                                <Trash2 className="size-3.5" />
                              )}
                              <span className="sr-only">Delete {skill}</span>
                            </button>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </FormItem>
              </div>
            </div>

            <DialogFooter className="mt-6">
              <DialogClose asChild>
                <Button variant="outline" disabled={updateMutation.isPending}>
                  Cancel
                </Button>
              </DialogClose>
              <LoadingButton type="submit" loading={updateMutation.isPending}>
                Save
              </LoadingButton>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}

export default EditAgent
