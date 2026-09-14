<script setup lang="ts">
import { computed } from 'vue'
import { CheckCircle2, ChevronDown, Clock3, LayoutDashboard, MessageCircle, MoreHorizontal, Plus, Search, ShieldCheck } from 'lucide-vue-next'
import type { Thread } from '../types/chat'
import type { ThreadStatus } from '../api/client'

defineProps<{
  threads: Thread[]
  selectedThreadId: string
  activeView: 'chat' | 'admin'
  currentUser: { user_id: string; name: string; is_admin: boolean } | null
  customerLabel: string
  open: boolean
}>()

const emit = defineEmits<{
  select: [thread: Thread]
  'start-new': []
  'switch-view': [view: 'chat' | 'admin']
  logout: []
}>()

const statusIcon = computed(() => (status: ThreadStatus) => status === 'pending_user' ? Clock3 : status === 'closed' ? CheckCircle2 : MessageCircle)
</script>

<template>
  <aside class="sidebar" :class="{ 'is-open': open }">
    <div class="brand-lockup"><div class="brand-mark"><span /></div><div><div class="brand-name">WhiteBear Desk</div><div class="brand-caption">AI SERVICE OS</div></div></div>
    <button class="workspace-switch glass-control" type="button"><span class="workspace-icon"><LayoutDashboard :size="16" /></span><span class="workspace-copy"><b>客服中枢</b><small>主工作区</small></span><ChevronDown :size="15" class="muted-icon" /></button>
    <nav class="primary-nav" aria-label="主导航">
      <button :class="['nav-item', { active: activeView === 'chat' }]" type="button" @click="emit('switch-view', 'chat')"><MessageCircle :size="18" /><span>客户服务</span><span class="nav-count">{{ threads.length }}</span></button>
      <button v-if="currentUser?.is_admin" :class="['nav-item', { active: activeView === 'admin' }]" type="button" @click="emit('switch-view', 'admin')"><ShieldCheck :size="18" /><span>审批中心</span></button>
    </nav>
    <div class="sidebar-section-title"><span>最近会话</span><div class="sidebar-title-actions"><button class="icon-button" title="新建会话" @click="emit('start-new')"><Plus :size="16" /></button><button class="icon-button" title="搜索会话"><Search :size="15" /></button></div></div>
    <div class="thread-list">
      <button v-for="thread in threads" :key="thread.id" :class="['thread-item', { selected: thread.id === selectedThreadId }]" type="button" @click="emit('select', thread)">
        <div class="thread-item-top"><span class="thread-title">{{ thread.title }}</span><span class="thread-time">{{ thread.time }}</span></div>
        <div class="thread-item-bottom"><span class="thread-preview">{{ thread.preview }}</span><component :is="statusIcon(thread.status)" :size="14" :class="['thread-status-icon', thread.status]" /></div>
        <span v-if="thread.unread" class="unread-dot">{{ thread.unread }}</span>
      </button>
    </div>
    <div class="sidebar-footer"><div class="agent-status"><span class="online-dot" />系统运行正常</div><div class="profile-row"><div class="avatar">{{ customerLabel.slice(0, 1) }}</div><div><b>{{ customerLabel }}</b><small>已连接 · {{ currentUser?.user_id || '未登录' }}</small></div><button class="icon-button" title="退出登录" @click="emit('logout')"><MoreHorizontal :size="17" /></button></div></div>
  </aside>
</template>
