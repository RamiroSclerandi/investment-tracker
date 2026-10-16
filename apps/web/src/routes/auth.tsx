import { createRoute } from '@tanstack/react-router'
import { AuthLayout } from '@/components/auth-layout'
import { PlaceholderPage } from '@/components/placeholder-page'
import { AuthCompletePage } from '@/features/auth/auth-complete-page'
import { LoginPage } from '@/features/auth/login-page'
import { RegisterPage } from '@/features/auth/register-page'
import { VerifyEmailPage } from '@/features/auth/verify-email-page'
import { rootRoute } from '@/routes/__root'

export const authLayoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: 'auth',
  component: AuthLayout,
})

const AUTH_PAGES = [
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
  validateSearch: (search: Record<string, unknown>): { verified?: true } =>
    search.verified === true ? { verified: true } : {},
  component: LoginPage,
})

const registerRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: '/register',
  component: RegisterPage,
})

const verifyEmailRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: '/verify-email',
  component: VerifyEmailPage,
})

export const authRoutes = [
  loginRoute,
  registerRoute,
  verifyEmailRoute,
  ...AUTH_PAGES.map(({ path, title }) =>
    createRoute({
      getParentRoute: () => authLayoutRoute,
      path,
      component: () => <PlaceholderPage title={title} />,
    }),
  ),
  authCompleteRoute,
]
