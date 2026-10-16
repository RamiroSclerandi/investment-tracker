import { createRoute } from '@tanstack/react-router'
import { AuthLayout } from '@/components/auth-layout'
import { AuthCompletePage } from '@/features/auth/auth-complete-page'
import { ForgotPasswordPage } from '@/features/auth/forgot-password-page'
import { LoginPage } from '@/features/auth/login-page'
import { RegisterPage } from '@/features/auth/register-page'
import { ResetPasswordPage } from '@/features/auth/reset-password-page'
import { VerifyEmailPage } from '@/features/auth/verify-email-page'
import { rootRoute } from '@/routes/__root'

export const authLayoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: 'auth',
  component: AuthLayout,
})

const authCompleteRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: '/auth/complete',
  component: AuthCompletePage,
})

const loginRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: '/login',
  validateSearch: (search: Record<string, unknown>): { verified?: true; reset?: true } => ({
    ...(search.verified === true ? { verified: true } : {}),
    ...(search.reset === true ? { reset: true } : {}),
  }),
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

const forgotPasswordRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: '/forgot-password',
  component: ForgotPasswordPage,
})

const resetPasswordRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: '/reset-password',
  component: ResetPasswordPage,
})

export const authRoutes = [
  loginRoute,
  registerRoute,
  verifyEmailRoute,
  forgotPasswordRoute,
  resetPasswordRoute,
  authCompleteRoute,
]
