import * as React from "react"

import { cn } from "@/lib/utils"

function ExpandingInput({ className, ...props }: React.ComponentProps<"textarea">) {
  const handleInput = (e: React.FormEvent<HTMLTextAreaElement>) => {
    const target = e.currentTarget;
    target.style.height = "auto"; // Reset height to calculate correctly
    target.style.height = `${target.scrollHeight}px`; // Set to scroll height
  };

  return (
    <textarea
      data-slot="textarea"
      rows={1}
      onInput={handleInput}
      className={cn(
        // Added: resize-none, overflow-hidden, and changed h-9 to min-h-9
        "resize-none overflow-hidden file:text-foreground placeholder:text-muted-foreground selection:bg-primary selection:text-primary-foreground dark:bg-input/30 border-input min-h-9 w-full min-w-0 rounded-md border bg-transparent px-3 py-1.5 text-base shadow-xs transition-[color,box-shadow] outline-none disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm",
        "focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]",
        "aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive",
        className
      )}
      {...props}
    />
  )
}

export { ExpandingInput }