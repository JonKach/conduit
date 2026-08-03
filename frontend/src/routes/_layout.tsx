import { createFileRoute, Outlet, redirect } from "@tanstack/react-router"

import { UsersService } from "@/client"
import AppSidebar from "@/components/Sidebar/AppSidebar"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import { isLoggedIn } from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout")({
  component: Layout,
  beforeLoad: async ({ context }) => {
    // isLoggedIn() is just "is there a token in localStorage" - it never
    // validates it, so an expired/forged token used to pass this gate and
    // the app would quietly stop working instead of bouncing to /login.
    // ensureQueryData actually calls the API (and, via the shared
    // ["currentUser"] key, warms the same cache useAuth() reads) so an
    // expired session gets caught here instead.
    if (!isLoggedIn()) {
      throw redirect({ to: "/login" })
    }
    try {
      await context.queryClient.ensureQueryData({
        queryKey: ["currentUser"],
        queryFn: UsersService.readUserMe,
        staleTime: 5 * 60 * 1000,
        retry: false, // an expired/invalid token will never succeed on retry
      })
    } catch {
      localStorage.removeItem("access_token")
      context.queryClient.clear()
      throw redirect({ to: "/login" })
    }
  },
})

function Layout() {
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <header className="sticky top-0 z-10 flex h-16 shrink-0 items-center gap-2 border-b px-4">
          <SidebarTrigger className="-ml-1 text-muted-foreground" />
        </header>
        <main className="flex-1 p-6 md:p-8">
          <div className="mx-auto max-w-7xl">
            <Outlet />
          </div>
        </main>
      </SidebarInset>
    </SidebarProvider>
  )
}

export default Layout
