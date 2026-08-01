// Shared between AddAgent (create flow) and EditAgent (edit flow) so the two
// forms validate and label files identically.

export const MAX_IMAGE_SIZE = 5 * 1024 * 1024
export const ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/gif"]

export const MAX_SKILL_FILE_SIZE = 2 * 1024 * 1024
export const ALLOWED_SKILL_EXTENSIONS = [".md", ".txt", ".pdf", ".docx"]

export function fileExtension(fileName: string) {
  const parts = fileName.split(".")
  return parts.length > 1 ? `.${parts.pop()?.toLowerCase()}` : ""
}

export function toSkillName(fileName: string) {
  return fileName
    .replace(/\.[^./]+$/, "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "-")
}

export function formatFileSize(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
