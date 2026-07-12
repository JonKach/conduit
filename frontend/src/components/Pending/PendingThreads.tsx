import { MessageSquare } from "lucide-react"

import { Skeleton } from "@/components/ui/skeleton"

const PendingThreads = () => (
  <div className="flex flex-col divide-y rounded-xl border">
    {Array.from({ length: 5 }).map((_, index) => (
      <div key={index} className="flex items-center gap-3 px-4 py-3">
        <MessageSquare className="size-4 shrink-0 text-muted-foreground/40" />
        <Skeleton className="h-4 w-48" />
        <Skeleton className="ml-auto h-4 w-24" />
        <Skeleton className="size-8 rounded-md" />
      </div>
    ))}
  </div>
)

export default PendingThreads
