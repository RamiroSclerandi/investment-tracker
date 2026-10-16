import { createRoute } from '@tanstack/react-router'
import { AuthLayout } from '@/components/auth-layout'
import { PlaceholderPage } from '@/components/placeholder-page'
import { AuthCompletePage } from '@/features/auth/auth-complete-page'
import { LoginPage } from '@/features/auth/login-page'
import { rootRoute } from '@/routes/__root'

export const authLayoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: 'auth',
  component: AuthLayout,
})

const AUTH_PAGES = [
  { path: '/register', title: 'Register' },
  { path: '/verify-email', title: 'Verify your email' },
  { path: '/forgot-password', title: 'Forgot password' },
  { path: '/reset-password', title: 'Reset password' },
] as const

const authCompleteRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: '/auth/complete',
  component: AuthCompletePage,
})

const loginRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: '/login',
  component: LoginPage,
})

export const authRoutes = [
  loginRoute,
  ...AUTH_PAGES.map(({ path, title }) =>
    createRoute({
      getParentRoute: () => authLayoutRoute,
      path,
      component: () => <PlaceholderPage title={title} />,
    }),
  ),
  authCompleteRoute,
]
