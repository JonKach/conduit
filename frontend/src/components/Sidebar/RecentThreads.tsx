import { useQuery } from "@tanstack/react-query"
import { Link as RouterLink, useRouterState } from "@tanstack/react-router"
import { MessageSquare } from "lucide-react"

import { ThreadsService } from "@/client"
import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSkeleton,
  useSidebar,
} from "@/components/ui/sidebar"

export function RecentThreads() {
  const { isMobile, setOpenMobile } = useSidebar()
  const router = useRouterState()
  const currentPath = router.location.pathname

  const { data, isLoading } = useQuery({
    queryKey: ["recentThreads"],
    queryFn: () => ThreadsService.readRecentThreads({ limit: 8 }),
  })

  const handleMenuClick = () => {
    if (isMobile) {
      setOpenMobile(false)
    }
  }

  if (!isLoading && (!data || data.data.length === 0)) {
    return null
  }

  return (
    <SidebarGroup>
      <SidebarGroupLabel>Recent Threads</SidebarGroupLabel>
      <SidebarGroupContent>
        <SidebarMenu>
          {isLoading
            ? Array.from({ length: 3 }).map((_, index) => (
                <SidebarMenuItem key={index}>
                  <SidebarMenuSkeleton showIcon />
                </SidebarMenuItem>
              ))
            : data?.data.map((thread) => {
                const path = `/threads/${thread.agent_id}/${thread.id}`
                return (
                  <SidebarMenuItem key={thread.id}>
                    <SidebarMenuButton
                      tooltip={thread.name}
                      isActive={currentPath === path}
                      asChild
                    >
                      <RouterLink
                        to="/threads/$agentId/$threadId"
                        params={{
                          agentId: thread.agent_id,
                          threadId: thread.id,
                        }}
                        onClick={handleMenuClick}
                      >
                        <MessageSquare />
                        <span className="min-w-0 flex-1 truncate">
                          {thread.name}
                        </span>
                      </RouterLink>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                )
              })}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  )
}

export default RecentThreads
