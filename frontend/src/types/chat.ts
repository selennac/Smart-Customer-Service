import type { SourceItem, ThreadStatus } from '../api/client'

export type Role = 'user' | 'assistant'

export interface Message {
  id: number
  role: Role
  content: string
  time: string
  sources: SourceItem[]
}

export interface Thread {
  id: string
  title: string
  preview: string
  status: ThreadStatus
  time: string
  unread?: number
  messages: Message[]
  createdAt?: string
}
