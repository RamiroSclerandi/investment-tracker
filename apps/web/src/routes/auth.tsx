import { createRoute } from '@tanstack/react-router'
import { AuthLayout } from '@/components/auth-layout'
import { PlaceholderPage } from '@/components/placeholder-page'
import { rootRoute } from '@/routes/__root'

export const authLayoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: 'auth',
  component: AuthLayout,
})

const AUTH_PAGES = [
  { path: '/login', title: 'Log in' },
  { path: '/register', title: 'Register' },
  { path: '/verify-email', title: 'Verify your email' },
  { path: '/forgot-password', title: 'Forgot password' },
  { path: '/reset-password', title: 'Reset password' },
  { path: '/auth/complete', title: 'Completing sign-in' },
] as const

export const authRoutes = AUTH_PAGES.map(({ path, title }) =>
  createRoute({
    getParentRoute: () => authLayoutRoute,
    path,
    component: () => <PlaceholderPage title={title} />,
  }),
)
