import { Outlet } from '@tanstack/react-router'

export function AuthLayout() {
  return (
    <main className="mx-auto flex min-h-svh w-full max-w-sm flex-col justify-center bg-background p-4 text-foreground">
      <Outlet />
    </main>
  )
}
