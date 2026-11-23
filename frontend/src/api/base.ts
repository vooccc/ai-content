const envBase = (import.meta.env.VITE_AICONTENT_API_BASE as string | undefined) || ''
export const API_BASE: string = envBase.replace(/\/$/, '')
