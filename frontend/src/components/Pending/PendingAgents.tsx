import { Card, CardHeader } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

const PendingAgents = () => (
  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
    {Array.from({ length: 8 }).map((_, index) => (
      <Card key={index} className="gap-3 py-4">
        <CardHeader className="px-4">
          <div className="flex items-start justify-between gap-2">
            <Skeleton className="size-10 rounded-full" />
          </div>
          <Skeleton className="mt-3 h-4 w-2/3" />
          <Skeleton className="mt-2 h-3 w-full" />
        </CardHeader>
      </Card>
    ))}
  </div>
)

export default PendingAgents
