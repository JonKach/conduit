import { Appearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"

interface AuthLayoutProps {
  children: React.ReactNode
}

export function AuthLayout({ children }: AuthLayoutProps) {
  return (
    // <div className="flex min-h-svh flex-col items-center justify-center gap-8 p-6">
    //   <Logo variant="full" className="h-8" asLink={false} />
    //   <div className="w-full max-w-xs">{children}</div>
    // </div>
    <div className="grid min-h-svh lg:grid-cols-2">
      <div className="bg-muted dark:bg-zinc-900 relative hidden lg:flex lg:items-center lg:justify-center flex-col gap-4 p-6 md:p-10">
        <Logo variant="full" className="h-16" asLink={false} />
        <span className="text-muted-foreground">
          <i>Agentic Harness and Public Agent Marketplace</i>
        </span>
      </div>
      <div className="flex flex-col gap-4 p-6 md:p-10">
        <div className="flex justify-end">
          <Appearance />
        </div>
        <div className="flex flex-1 items-center justify-center">
          <div className="w-full max-w-xs">{children}</div>
        </div>
      </div>
    </div>
  )
}
