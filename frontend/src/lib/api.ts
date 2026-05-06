const rawBase = import.meta.env.VITE_API_BASE as string | undefined

export function apiBase(): string {
  if (rawBase && rawBase.length > 0) {
    return rawBase.replace(/\/$/, '')
  }
  return ''
}

export function apiUrl(path: string): string {
  const base = apiBase()
  const p = path.startsWith('/') ? path : `/${path}`
  if (!base) {
    return p
  }
  return `${base}${p}`
}
