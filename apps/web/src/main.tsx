import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from '@/app'
import { refreshSession } from '@/features/auth/session'
import '@/styles/index.css'

void refreshSession()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
