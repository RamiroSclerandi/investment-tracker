import { z } from 'zod'

export const PASSWORD_MIN_LENGTH = 12

export const emailSchema = z.email({ error: 'Ingresá un email válido.' })

export const passwordSchema = z
  .string()
  .min(PASSWORD_MIN_LENGTH, { error: `Usá al menos ${PASSWORD_MIN_LENGTH} caracteres.` })
  .max(128, { error: 'Usá hasta 128 caracteres.' })
