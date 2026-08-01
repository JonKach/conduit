import { useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Search,
  Store,
} from "lucide-react"
import { Suspense, useMemo, useState } from "react"

import { type AgentPublic, AgentsService } from "@/client"
import PublicAgentCard from "@/components/Agents/PublicAgentCard"
import PendingAgents from "@/components/Pending/PendingAgents"
import { Button } from "@/components/ui/button"
import { ButtonGroup } from "@/components/ui/button-group"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

type SortOption = "recent" | "popular"

const PAGE_SIZE_OPTIONS = [8, 12, 24, 48]

function getMarketplaceQueryOptions(sort: SortOption) {
  return {
    queryFn: () =>
      AgentsService.readPublicAgents({ skip: 0, limit: 100, sort }),
    queryKey: ["publicAgents", sort],
  }
}

export const Route = createFileRoute("/_layout/marketplace")({
  component: Marketplace,
  head: () => ({
    meta: [
      {
        title: "Marketplace - Conduit",
      },
    ],
  }),
})

function matchesSearch(agent: AgentPublic, query: string) {
  const haystack = `${agent.name} ${agent.description ?? ""} ${agent.owner_name ?? ""}`
  return haystack.toLowerCase().includes(query.toLowerCase())
}

function MarketplaceContent() {
  const [sort, setSort] = useState<SortOption>("recent")
  const [search, setSearch] = useState("")
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(12)

  const { data: agents } = useSuspenseQuery(getMarketplaceQueryOptions(sort))

  const filtered = useMemo(() => {
    const query = search.trim()
    if (!query) return agents.data
    return agents.data.filter((agent) => matchesSearch(agent, query))
  }, [agents.data, search])

  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize))
  const safePage = Math.min(page, pageCount - 1)

  const handleSearchChange = (value: string) => {
    setSearch(value)
    setPage(0)
  }

  const handleSortChange = (value: SortOption) => {
    setSort(value)
    setPage(0)
  }

  const pageItems = filtered.slice(
    safePage * pageSize,
    safePage * pageSize + pageSize,
  )

  if (agents.data.length === 0) {
    return (
      <div className="flex min-h-[70vh] flex-col items-center justify-center gap-4 text-center">
        <div className="rounded-full bg-muted p-4">
          <Store className="h-8 w-8 text-muted-foreground" />
        </div>
        <div>
          <h2 className="text-lg font-semibold">No public agents yet</h2>
          <p className="text-muted-foreground">
            Agents marked public by their owners will show up here.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl">Marketplace</h1>
          <p className="text-muted-foreground">
            Browse public agents and add them to your own list
          </p>
        </div>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative w-full sm:max-w-sm">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => handleSearchChange(e.target.value)}
            placeholder="Search agents..."
            className="pl-9"
          />
        </div>
        <ButtonGroup>
          <Button
            type="button"
            variant={sort === "recent" ? "default" : "outline"}
            size="sm"
            onClick={() => handleSortChange("recent")}
          >
            Recent
          </Button>
          <Button
            type="button"
            variant={sort === "popular" ? "default" : "outline"}
            size="sm"
            onClick={() => handleSortChange("popular")}
          >
            Popular
          </Button>
        </ButtonGroup>
      </div>

      {filtered.length === 0 ? (
        <p className="py-12 text-center text-muted-foreground">
          No agents match "{search}".
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {pageItems.map((agent) => (
            <PublicAgentCard key={agent.id} agent={agent} />
          ))}
        </div>
      )}

      {pageCount > 1 && (
        <div className="flex flex-col items-start justify-between gap-4 border-t pt-4 sm:flex-row sm:items-center">
          <div className="flex items-center gap-x-2">
            <p className="text-sm text-muted-foreground">Per page</p>
            <Select
              value={`${pageSize}`}
              onValueChange={(value) => {
                setPageSize(Number(value))
                setPage(0)
              }}
            >
              <SelectTrigger className="h-8 w-[70px]">
                <SelectValue placeholder={pageSize} />
              </SelectTrigger>
              <SelectContent side="top">
                {PAGE_SIZE_OPTIONS.map((size) => (
                  <SelectItem key={size} value={`${size}`}>
                    {size}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex items-center gap-x-6">
            <div className="flex items-center gap-x-1 text-sm text-muted-foreground">
              <span>Page</span>
              <span className="font-medium text-foreground">
                {safePage + 1}
              </span>
              <span>of</span>
              <span className="font-medium text-foreground">{pageCount}</span>
            </div>

            <div className="flex items-center gap-x-1">
              <Button
                variant="outline"
                size="sm"
                className="h-8 w-8 p-0"
                onClick={() => setPage(0)}
                disabled={safePage === 0}
              >
                <span className="sr-only">Go to first page</span>
                <ChevronsLeft className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-8 w-8 p-0"
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={safePage === 0}
              >
                <span className="sr-only">Go to previous page</span>
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-8 w-8 p-0"
                onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
                disabled={safePage >= pageCount - 1}
              >
                <span className="sr-only">Go to next page</span>
                <ChevronRight className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-8 w-8 p-0"
                onClick={() => setPage(pageCount - 1)}
                disabled={safePage >= pageCount - 1}
              >
                <span className="sr-only">Go to last page</span>
                <ChevronsRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function Marketplace() {
  return (
    <Suspense fallback={<PendingAgents />}>
      <MarketplaceContent />
    </Suspense>
  )
}
