export type AppEnv = 'development' | 'production'

function resolveAppEnv(): AppEnv {
  const raw = import.meta.env.VITE_APP_ENV as string | undefined
  if (raw === 'development' || raw === 'production') return raw
  return import.meta.env.PROD ? 'production' : 'development'
}

export const appEnv: AppEnv = resolveAppEnv()
export const isDevelopment = appEnv === 'development'
export const isProduction = appEnv === 'production'
