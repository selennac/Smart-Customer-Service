<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  Activity,
  ArrowUpRight,
  Bell,
  Bot,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleDollarSign,
  Clock3,
  Command,
  FileText,
  Inbox,
  Menu,
  MessageCircle,
  PackageCheck,
  PanelRight,
  Plus,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Ticket,
  Trash2,
  Truck,
  X,
} from 'lucide-vue-next'
import MessageBubble from './components/MessageBubble.vue'
import Sidebar from './components/Sidebar.vue'
import type { Message, Thread } from './types/chat'
import {
  API_BASE,
  authStore,
  createThread,
  deleteThread,
  decideRefund as decideRefundApi,
  formatDate,
  getThreadMessages,
  listPendingRefunds,
  listThreads,
  login,
  streamConversation,
  type PendingAction,
  type RefundItem,
  type SourceItem,
  type StreamEnvelope,
  type ThreadItem as ApiThread,
  type ThreadStatus,
} from './api/client'

const activeView = ref<'chat' | 'admin'>('chat')
const mobileSidebarOpen = ref(false)
const mobileContextOpen = ref(false)
const contextPanelVisible = ref(true)
const composer = ref('')
const isRunning = ref(false)
const interruptVisible = ref(true)
const toast = ref('')
const scroller = ref<HTMLElement | null>(null)
const isLoading = ref(false)
const errorMessage = ref('')
const loginUserId = ref('DEMO-USR-001')
const loginName = ref('')
const isLoggingIn = ref(false)
const currentUser = ref(authStore.user)
const pendingAction = ref<PendingAction | null>(null)
const deleteDialogVisible = ref(false)
const deleteTarget = ref<Thread | null>(null)
const NEW_THREAD_TITLE = '新会话'

const threads = ref<Thread[]>([])
const emptyThread: Thread = { id: '', title: NEW_THREAD_TITLE, preview: '开始一个新的客服会话', status: 'active', time: '', messages: [] }

const selectedThreadId = ref('')
const selectedThread = computed(() => threads.value.find((thread) => thread.id === selectedThreadId.value) ?? threads.value[0] ?? emptyThread)

const authenticated = ref(Boolean(authStore.token))
const customerLabel = computed(() => currentUser.value?.name || '当前用户')
const orderLabel = computed(() => pendingAction.value?.order_id || '尚未关联订单')

function mapThread(item: ApiThread): Thread {
  return { id: item.thread_id, title: item.title || NEW_THREAD_TITLE, preview: item.last_message || '暂无消息', status: item.status, time: formatDate(item.updated_at), messages: [], createdAt: item.created_at }
}

async function loadWorkspace() {
  if (!authenticated.value) return
  isLoading.value = true
  errorMessage.value = ''
  try {
    const result = await listThreads()
    threads.value = result.items.map(mapThread)
    if (!threads.value.length) {
      const created = await createThread()
      threads.value = [{ id: created.thread_id, title: NEW_THREAD_TITLE, preview: '开始一个新的客服会话', status: created.status, time: '刚刚', messages: [] }]
    }
    selectedThreadId.value = threads.value[0].id
    await loadMessages(threads.value[0])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '无法加载会话数据'
  } finally { isLoading.value = false }
}

async function loadMessages(thread: Thread) {
  if (!thread.id) return
  try {
    const result = await getThreadMessages(thread.id)
    thread.messages = result.messages.map((message) => ({ id: Number(message.message_id.replace(/\D/g, '').slice(-8)) || Date.now(), role: message.role, content: message.content, time: '', sources: message.sources || [] }))
    pendingAction.value = result.pending_action || null
    interruptVisible.value = Boolean(result.pending_action) || thread.status === 'pending_user' || thread.status === 'pending_supervisor'
    const last = thread.messages[thread.messages.length - 1]
    if (last) thread.preview = last.content
    if (result.title) thread.title = result.title
  } catch (error) { errorMessage.value = error instanceof Error ? error.message : '无法加载消息' }

  // 加载messages 自动滚到底部
  await nextTick()
  const el = scroller.value
  if (el) {
    el.scrollTo({
      top: el.scrollHeight,
      behavior: 'smooth'
    })
  }
}

const steps = computed(() => [
  { label: '意图识别', detail: 'after_sale', state: 'done', icon: Sparkles },
  { label: '查询订单', detail: 'query_order', state: 'done', icon: PackageCheck },
  { label: '校验政策', detail: 'search_faq', state: 'done', icon: FileText },
  { label: pendingAction.value?.kind === 'supervisor_approval' ? '等待主管审批' : '等待确认', detail: pendingAction.value?.kind || 'refund_confirmation', state: interruptVisible.value ? 'current' : 'done', icon: ShieldCheck },
])

const statusLabel: Record<ThreadStatus, string> = {
  active: '进行中',
  pending_user: '待你确认',
  pending_supervisor: '待主管审批',
  closed: '已完成',
}

const statusIcon = (status: ThreadStatus) => status === 'pending_user' ? Clock3 : status === 'closed' ? CheckCircle2 : MessageCircle

async function selectThread(thread: Thread) {
  selectedThreadId.value = thread.id
  mobileSidebarOpen.value = false
  interruptVisible.value = thread.status === 'pending_user' || thread.status === 'pending_supervisor'
  pendingAction.value = null
  await loadMessages(thread)
}

async function startNewThread() {
  if (!authenticated.value || isLoading.value) return
  isLoading.value = true
  errorMessage.value = ''
  try {
    const created = await createThread()
    const thread: Thread = { id: created.thread_id, title: NEW_THREAD_TITLE, preview: '开始一个新的客服会话', status: created.status, time: '刚刚', messages: [] }
    threads.value.unshift(thread)
    selectedThreadId.value = thread.id
    pendingAction.value = null
    interruptVisible.value = false
    mobileSidebarOpen.value = false
    await nextTick()
  } catch (error) { errorMessage.value = error instanceof Error ? error.message : '新建会话失败' }
  finally { isLoading.value = false }
}

function requestDeleteThread() {
  if (!selectedThread.value.id || isLoading.value) return
  deleteTarget.value = selectedThread.value
  deleteDialogVisible.value = true
}

function closeDeleteDialog() {
  if (isLoading.value) return
  deleteDialogVisible.value = false
  deleteTarget.value = null
}

async function deleteCurrentThread() {
  const deletingId = deleteTarget.value?.id
  if (!deletingId || isLoading.value) return
  deleteDialogVisible.value = false
  deleteTarget.value = null
  isLoading.value = true
  errorMessage.value = ''
  try {
    await deleteThread(deletingId)
    const index = threads.value.findIndex((thread) => thread.id === deletingId)
    threads.value = threads.value.filter((thread) => thread.id !== deletingId)
    const next = threads.value[index] || threads.value[index - 1]
    selectedThreadId.value = next?.id || ''
    pendingAction.value = null
    interruptVisible.value = false
    if (next) await loadMessages(next)
    flash('会话已删除')
  } catch (error) { errorMessage.value = error instanceof Error ? error.message : '删除会话失败' }
  finally { isLoading.value = false }
}

function flash(message: string) {
  toast.value = message
  window.setTimeout(() => (toast.value = ''), 2800)
}

async function sendMessage() {
  const content = composer.value.trim()
  if (!content || isRunning.value) return
  selectedThread.value.messages.push({ id: Date.now(), role: 'user', content, time: '现在', sources: [] })
  selectedThread.value.preview = content
  composer.value = ''
  isRunning.value = true
  errorMessage.value = ''
  const assistantId = Date.now() + 1
  const assistantMessage: Message = { id: assistantId, role: 'assistant', content: '', time: '现在', sources: [] }
  selectedThread.value.messages.push(assistantMessage)
  await nextTick()
  scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: 'smooth' })
  try {
    await streamConversation(selectedThread.value.id, { message: content }, handleStreamEvent)
  } catch (error) {
    selectedThread.value.messages = selectedThread.value.messages.filter((message) => message.id !== assistantId)
    errorMessage.value = error instanceof Error ? error.message : '消息发送失败'
  } finally { isRunning.value = false }
}

function handleStreamEvent(event: StreamEnvelope) {
  const lastAssistant = [...selectedThread.value.messages].reverse().find((message) => message.role === 'assistant')
  if (event.type === 'message.delta' && lastAssistant) {
    lastAssistant.content += String(event.data.content || '')
    void nextTick(() => scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: 'auto' }))
  }
  if (event.type === 'message.completed' && lastAssistant) {
    lastAssistant.content = String(event.data.answer || lastAssistant.content)
    const sources = Array.isArray(event.data.sources) ? event.data.sources : []
    lastAssistant.sources = sources.map((source) => typeof source === 'string' ? { source } : { source: source.source as string | null, section: source.section as string | null, topic: source.topic as string | null, content: source.content as string | null }) as SourceItem[]
    selectedThread.value.preview = lastAssistant.content
    if (typeof event.data.title === 'string' && event.data.title.trim()) selectedThread.value.title = event.data.title
  }
  if (event.type === 'run.interrupted') {
    const nextPendingAction = event.data as unknown as PendingAction
    const interruptedAnswer = String(event.data.answer || '').trim() || (
      nextPendingAction.kind === 'supervisor_approval'
        ? '退款已提交，金额超过 500 元，正在等待主管审批。审批完成后我们会通知你。'
        : '退款申请已准备，请确认退款金额和原因。'
    )
    if (lastAssistant) {
      lastAssistant.content = interruptedAnswer
      selectedThread.value.preview = interruptedAnswer
      if (typeof event.data.title === 'string' && event.data.title.trim()) selectedThread.value.title = event.data.title
    }
    pendingAction.value = nextPendingAction
    interruptVisible.value = true
    selectedThread.value.status = pendingAction.value.kind === 'supervisor_approval' ? 'pending_supervisor' : 'pending_user'
  }
  if (event.type === 'run.failed') errorMessage.value = String(event.data.message || '客服服务暂时不可用')
}

function quickPrompt(prompt: string) {
  composer.value = prompt
}

function toggleContextPanel() {
  if (window.innerWidth <= 900) {
    contextPanelVisible.value = true
    mobileContextOpen.value = !mobileContextOpen.value
    return
  }
  contextPanelVisible.value = !contextPanelVisible.value
}

function contextPanelLabel() {
  if (window.innerWidth <= 900) return mobileContextOpen.value ? '隐藏处理面板' : '查看处理面板'
  return contextPanelVisible.value ? '隐藏处理面板' : '查看处理面板'
}

async function resumeRefund(decision: 'confirm' | 'cancel') {
  if (!pendingAction.value || !selectedThread.value.id) return
  const action = pendingAction.value
  pendingAction.value = null
  interruptVisible.value = false
  isRunning.value = true
  try {
    await streamConversation(selectedThread.value.id, { resume: { ...action, decision } }, handleStreamEvent)
    const resumedPendingAction = pendingAction.value as PendingAction | null
    if (resumedPendingAction?.kind === 'supervisor_approval') {
      interruptVisible.value = true
      selectedThread.value.status = 'pending_supervisor'
      flash('退款已提交，等待主管审批')
    } else {
      interruptVisible.value = false
      selectedThread.value.status = decision === 'cancel' ? 'active' : 'closed'
      flash(decision === 'confirm' ? '退款请求已提交' : '已取消退款申请')
    }
  } catch (error) {
    pendingAction.value = action
    interruptVisible.value = true
    selectedThread.value.status = action.kind === 'supervisor_approval' ? 'pending_supervisor' : 'pending_user'
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
  }
  finally { isRunning.value = false }
}

function confirmRefund() { return resumeRefund('confirm') }
function cancelRefund() { return resumeRefund('cancel') }

function switchView(view: 'chat' | 'admin') {
  if (view === 'admin' && !currentUser.value?.is_admin) {
    activeView.value = 'chat'
    flash('当前账号没有审批中心权限')
    return
  }
  activeView.value = view
  mobileSidebarOpen.value = false
  if (view === 'admin' && authenticated.value) void loadAdminRefunds()
}

interface AdminRefund extends RefundItem { user: string; wait: string; risk: string }
const pendingRefunds = ref<AdminRefund[]>([])
const defaultRefund: AdminRefund = { refund_id: '暂无待审批退款', order_id: '暂无订单', amount: '0.00', reason: '当前没有待审批记录', status: 'pending_supervisor', user: '暂无用户', wait: '', risk: '普通' }
const selectedRefund = ref<AdminRefund>(defaultRefund)
const approvalState = computed<'idle' | 'approved' | 'rejected'>(() => {
  if (selectedRefund.value.status === 'rejected') return 'rejected'
  if (selectedRefund.value.status === 'approved' || selectedRefund.value.status === 'completed') return 'approved'
  return 'idle'
})
const canDecideSelectedRefund = computed(() => pendingRefunds.value.some(
  (refund) => refund.refund_id === selectedRefund.value.refund_id && refund.status === 'pending_supervisor',
))

async function loadAdminRefunds() {
  try {
    const result = await listPendingRefunds()
    pendingRefunds.value = (result.data || []).map((refund) => ({ ...refund, user: '待加载用户', wait: formatDate(refund.reviewed_at || undefined) || '待处理', risk: Number(refund.amount) >= 1000 ? '较高' : '普通' }))
    selectedRefund.value = pendingRefunds.value[0] || defaultRefund
  } catch (error) { errorMessage.value = error instanceof Error ? error.message : '无法加载审批列表' }
}

async function decideRefund(decision: 'approved' | 'rejected') {
  if (!selectedRefund.value) return
  try {
    const result = await decideRefundApi(selectedRefund.value.refund_id, decision === 'approved' ? 'approve' : 'reject')
    const index = pendingRefunds.value.findIndex((refund) => refund.refund_id === selectedRefund.value.refund_id)
    if (index >= 0 && result.approval?.data) {
      const updatedRefund = { ...pendingRefunds.value[index], ...result.approval.data }
      pendingRefunds.value[index] = updatedRefund
      selectedRefund.value = updatedRefund
    }
    flash(decision === 'approved' ? '已批准退款，流程正在恢复' : '已拒绝退款，用户将收到通知')
  } catch (error) { errorMessage.value = error instanceof Error ? error.message : '审批失败' }
}

async function handleLogin() {
  if (!loginUserId.value.trim() || isLoggingIn.value) return
  isLoggingIn.value = true; errorMessage.value = ''
  try {
    const result = await login(loginUserId.value.trim())
    currentUser.value = { user_id: result.user_id, name: result.name, is_admin: result.is_admin }
    authenticated.value = true
    activeView.value = 'chat'
    loginName.value = result.name
    await loadWorkspace()
  } catch (error) { errorMessage.value = error instanceof Error ? error.message : '登录失败，请检查用户 ID' }
  finally { isLoggingIn.value = false }
}

function logout() { authStore.clear(); authenticated.value = false; currentUser.value = null; activeView.value = 'chat'; threads.value = []; selectedThreadId.value = '' }

function handleGlobalKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && deleteDialogVisible.value) closeDeleteDialog()
}

onMounted(async () => {
  window.addEventListener('keydown', handleGlobalKeydown)
  if (authenticated.value) { await loadWorkspace() }
})

onBeforeUnmount(() => window.removeEventListener('keydown', handleGlobalKeydown))
</script>

<template>
  <div class="app-shell">
    <div class="ambient ambient-one" />
    <div class="ambient ambient-two" />

    <Sidebar :threads="threads" :selected-thread-id="selectedThreadId" :active-view="activeView" :current-user="currentUser" :customer-label="customerLabel" :open="mobileSidebarOpen" @select="selectThread" @start-new="startNewThread" @switch-view="switchView" @logout="logout" />

    <main class="main-area">
      <header class="topbar">
        <button class="mobile-menu icon-button" title="打开导航" @click="mobileSidebarOpen = !mobileSidebarOpen"><Menu :size="20" /></button>
        <div class="breadcrumb"><span>客服中枢</span><ChevronRight :size="14" /><b>{{ activeView === 'chat' ? '客户服务' : '审批中心' }}</b></div>
        <div class="topbar-actions"><div class="live-pill"><span class="live-pulse" />LIVE</div><button class="icon-button" title="通知"><Bell :size="18" /><span class="notification-dot" /></button><div class="top-avatar">{{ customerLabel.slice(0, 1) }}</div></div>
      </header>

      <section v-if="activeView === 'chat'" class="workspace">
        <div class="conversation-column glass-panel">
          <div class="conversation-head">
            <div><div class="eyebrow"><span class="status-dot" />{{ statusLabel[selectedThread.status] }}</div><h1>{{ selectedThread.title }}</h1><p>{{ selectedThread.id }} <span>·</span> 已持续 08:24</p></div>
            <div class="head-actions"><button class="icon-button" :title="contextPanelLabel()" :aria-label="contextPanelLabel()" @click="toggleContextPanel"><PanelRight :size="18" /></button><button class="icon-button danger-icon" title="删除会话" :disabled="!selectedThread.id || isLoading" @click="requestDeleteThread"><Trash2 :size="17" /></button></div>
          </div>

          <div ref="scroller" class="message-scroller">
            <div v-if="!selectedThread.id" class="conversation-empty"><div class="empty-orbit"><Plus :size="20" /></div><b>还没有会话</b><span>创建一个新会话，开始处理客户问题。</span><button class="button button-primary" type="button" @click="startNewThread"><Plus :size="15" />新建会话</button></div>
            <div v-if="selectedThread.id" class="day-divider"><span>今天</span></div>
            <article v-for="message in selectedThread.messages" :key="message.id" :class="['message-row', message.role]">
              <div v-if="message.role === 'assistant'" class="message-avatar assistant-avatar"><Bot :size="17" /></div>
              <div class="message-content-wrap"><MessageBubble :message="message" :is-typing="isRunning && message.role === 'assistant' && !message.content" /></div>
              <div v-if="message.role === 'user'" class="message-avatar user-avatar">你</div>
            </article>

            <div v-if="interruptVisible && pendingAction?.kind === 'refund_confirmation'" class="interrupt-card">
              <div class="interrupt-top"><div class="interrupt-icon"><CircleDollarSign :size="19" /></div><div><b>请确认退款申请</b><span>Graph 已暂停，等待你的决定</span></div><span class="interrupt-tag">需确认</span></div>
              <div class="refund-summary"><div><small>退款金额</small><strong>¥{{ pendingAction.amount || '待确认' }}</strong></div><div><small>订单编号</small><b>{{ pendingAction.order_id || '未关联订单' }}</b></div><div><small>退款原因</small><b>{{ pendingAction.reason || '用户申请退款' }}</b></div></div>
              <div class="policy-note"><FileText :size="14" /><span>依据《退款政策》：签收 7 天内且商品保持完好，可申请无理由退款。</span></div>
              <div class="interrupt-actions"><button class="button button-primary" type="button" @click="confirmRefund"><Check :size="16" />确认退款</button><button class="button button-quiet" type="button" @click="cancelRefund"><X :size="16" />暂不处理</button></div>
            </div>
            <div v-else-if="interruptVisible && pendingAction?.kind === 'supervisor_approval'" class="interrupt-card supervisor-card">
              <div class="interrupt-top"><div class="interrupt-icon"><Clock3 :size="19" /></div><div><b>等待主管审批</b><span>退款申请已提交，审批完成后会更新状态</span></div><span class="interrupt-tag">处理中</span></div>
              <div class="refund-summary"><div><small>退款金额</small><strong>¥{{ pendingAction.amount || '待确认' }}</strong></div><div><small>退款编号</small><b>{{ pendingAction.refund_id || '处理中' }}</b></div></div>
              <div class="policy-note"><ShieldCheck :size="14" /><span>金额超过 500 元，需要主管审批。你可以稍后在本会话查看处理结果。</span></div>
            </div>
          </div>

          <div class="composer-zone"><div class="quick-prompts"><button type="button" @click="quickPrompt('帮我查询订单 ORD-20240918-0841 的物流进度')"><Truck :size="14" />查询物流</button><button type="button" @click="quickPrompt('我想申请一笔退款')"><CircleDollarSign :size="14" />发起退款</button><button type="button" @click="quickPrompt('我要投诉物流问题')"><Ticket :size="14" />创建工单</button></div><div class="composer"><textarea v-model="composer" rows="1" :disabled="!selectedThread.id" placeholder="输入你的问题，WhiteBear AI 会实时处理…" @keydown.enter.exact.prevent="sendMessage" /><div class="composer-footer"><span><Command :size="13" /> Enter 发送</span><button class="send-button" type="button" title="发送消息" :disabled="!composer.trim() || isRunning || !selectedThread.id" @click="sendMessage"><Send :size="17" /></button></div></div><div class="composer-disclaimer"><Sparkles :size="13" />AI 可能会犯错，请在重要操作前核对信息</div></div>
        </div>

        <aside v-if="contextPanelVisible" class="context-column" :class="{ 'mobile-open': mobileContextOpen }">
          <div class="context-panel glass-panel"><div class="panel-heading"><div><span class="eyebrow">LIVE CONTEXT</span><h2>处理进度</h2></div><button class="icon-button mobile-close" title="关闭面板" @click="mobileContextOpen = false"><X :size="17" /></button></div><div class="run-indicator"><span class="run-icon"><Activity :size="16" /></span><div><b>Graph 正在运行</b><small>run_8a4f · 刚刚更新</small></div><span class="live-pulse" /></div><div class="stepper"><div v-for="(step, index) in steps" :key="step.label" :class="['step', step.state]"><div class="step-marker"><Check v-if="step.state === 'done'" :size="13" /><component :is="step.icon" v-else :size="14" /></div><div class="step-copy"><b>{{ step.label }}</b><small>{{ step.detail }}</small></div><div v-if="index < steps.length - 1" class="step-line" /></div></div></div>
          <div class="context-panel glass-panel profile-context"><div class="panel-heading"><div><span class="eyebrow">CUSTOMER</span><h2>用户信息</h2></div><button class="icon-button" title="查看用户"><ArrowUpRight :size="16" /></button></div><div class="customer-card"><div class="large-avatar">{{ customerLabel.slice(0, 1) }}</div><div><b>{{ customerLabel }}</b><span>{{ currentUser?.user_id || '未登录' }}</span></div><span class="vip-badge">已认证</span></div><div class="metric-grid"><div><small>当前会话</small><b>{{ threads.length }}</b></div><div><small>连接状态</small><b class="metric-live">在线</b></div><div><small>API 环境</small><b class="metric-live">{{ API_BASE.startsWith('/') ? '本地' : '远端' }}</b></div></div></div>
          <div class="context-panel glass-panel order-context"><div class="panel-heading"><div><span class="eyebrow">BUSINESS OBJECT</span><h2>关联订单</h2></div><button class="icon-button" title="查看订单"><ArrowUpRight :size="16" /></button></div><div class="order-id"><PackageCheck :size="17" /><b>{{ orderLabel }}</b><span class="order-state">{{ pendingAction ? '处理中' : '由会话识别' }}</span></div><div class="order-line"><span>订单详情由客服工具实时返回</span></div><div class="order-line muted"><span>当前线程</span><span>{{ selectedThread.id || '尚未创建' }}</span></div><div class="order-line muted"><span>会话状态</span><span>{{ statusLabel[selectedThread.status] }}</span></div></div>
        </aside>
      </section>

      <section v-else class="admin-workspace">
        <div class="admin-title-row"><div><span class="eyebrow">SUPERVISOR CONSOLE</span><h1>审批中心</h1><p>需要人工判断的高风险退款会出现在这里。</p></div><div class="admin-stat"><span class="stat-number">{{ String(pendingRefunds.length).padStart(2, '0') }}</span><span>待处理</span></div></div>
        <div class="admin-grid"><div class="approval-list glass-panel"><div class="panel-toolbar"><div><b>待审批退款</b><span>按提交时间排序</span></div><button class="filter-button" type="button" @click="loadAdminRefunds"><Search :size="15" />刷新</button></div><div v-if="!pendingRefunds.length" class="empty-state"><Inbox :size="20" /><b>暂无待审批退款</b><span>新的高额退款会自动出现在这里</span></div><button v-for="refund in pendingRefunds" :key="refund.refund_id" :class="['approval-item', { selected: selectedRefund.refund_id === refund.refund_id }]" type="button" @click="selectedRefund = refund"><div class="approval-item-top"><span class="risk-dot" :class="refund.risk === '较高' ? 'high' : 'normal'" />{{ refund.refund_id }}<span class="approval-wait">{{ refund.wait }}</span></div><div class="approval-item-main"><div><b>{{ refund.user }}</b><span>{{ refund.reason }}</span></div><strong>¥{{ refund.amount }}</strong></div><div class="approval-item-order">{{ refund.order_id }}<ChevronRight :size="14" /></div></button></div><div class="approval-detail glass-panel"><div class="detail-head"><div><span class="eyebrow">REFUND REQUEST</span><h2>{{ selectedRefund.refund_id }}</h2></div><span :class="['detail-status', approvalState]">{{ approvalState === 'idle' ? '等待处理' : approvalState === 'approved' ? '已批准' : '已拒绝' }}</span></div><div class="detail-amount"><small>申请退款金额</small><strong>¥{{ selectedRefund.amount }}</strong><span>{{ selectedRefund.reason }}</span></div><div class="detail-section"><div class="section-label"><PackageCheck :size="15" />订单信息</div><div class="detail-table"><div><span>订单编号</span><b>{{ selectedRefund.order_id }}</b></div><div><span>用户</span><b>{{ selectedRefund.user }}</b></div><div><span>退款状态</span><b class="success-text">{{ selectedRefund.status }}</b></div><div><span>提交时间</span><b>{{ selectedRefund.wait || '待处理' }}</b></div></div></div><div class="detail-section"><div class="section-label"><FileText :size="15" />政策依据</div><div class="evidence-box"><div class="evidence-icon"><ShieldCheck :size="16" /></div><div><b>退款政策 · 大额退款审核</b><span>金额超过 ¥500，需主管审批后进入退款流程。</span></div><ArrowUpRight :size="15" /></div></div><div class="approval-actions"><button class="button button-danger" type="button" :disabled="!canDecideSelectedRefund" @click="decideRefund('rejected')"><X :size="16" />拒绝退款</button><button class="button button-primary" type="button" :disabled="!canDecideSelectedRefund" @click="decideRefund('approved')"><Check :size="16" />批准退款</button></div></div></div>
      </section>
    </main>

    <div v-if="!authenticated" class="login-overlay">
      <div class="login-card glass-panel">
        <div class="login-mark"><Sparkles :size="20" /></div>
        <span class="eyebrow">ORBIT DESK / SECURE ACCESS</span>
        <h1>连接客服中枢</h1>
        <p>输入后端数据库中的用户 ID，加载真实会话与处理记录。</p>
        <form class="login-form" @submit.prevent="handleLogin">
          <label for="user-id">用户 ID</label>
          <input id="user-id" v-model="loginUserId" autocomplete="username" placeholder="例如 DEMO-USR-001" />
          <button class="button button-primary login-submit" type="submit" :disabled="isLoggingIn || !loginUserId.trim()"><span v-if="isLoggingIn" class="button-spinner" />{{ isLoggingIn ? '正在连接…' : '进入工作台' }}<ArrowUpRight v-if="!isLoggingIn" :size="15" /></button>
        </form>
        <div class="login-hint"><ShieldCheck :size="14" />请求仅发送到 {{ API_BASE }}，不会保存密码。</div>
      </div>
    </div>
    <div v-if="isLoading" class="loading-strip"><span class="button-spinner" />正在同步会话数据…</div>
    <div v-if="errorMessage" class="error-banner"><X :size="16" /><span>{{ errorMessage }}</span><button type="button" @click="errorMessage = ''; authenticated ? loadWorkspace() : handleLogin()">重试</button></div>
    <transition name="toast"><div v-if="toast" class="toast-message"><CheckCircle2 :size="17" />{{ toast }}</div></transition>
    <div v-if="deleteDialogVisible" class="delete-dialog-overlay" @click.self="closeDeleteDialog">
      <section class="delete-dialog glass-panel" role="dialog" aria-modal="true" aria-labelledby="delete-dialog-title">
        <div class="delete-dialog-icon"><Trash2 :size="19" /></div>
        <div class="delete-dialog-copy">
          <span class="eyebrow">DELETE THREAD</span>
          <h2 id="delete-dialog-title">删除这个会话？</h2>
          <p>“{{ deleteTarget?.title }}” 将被永久删除，删除后无法恢复。</p>
          <span class="delete-dialog-note"><ShieldCheck :size="14" />退款等业务记录不会受到影响</span>
        </div>
        <div class="delete-dialog-actions">
          <button class="button button-quiet" type="button" :disabled="isLoading" @click="closeDeleteDialog">取消</button>
          <button class="button button-danger delete-confirm-button" type="button" :disabled="isLoading" @click="deleteCurrentThread"><Trash2 :size="15" />确认删除</button>
        </div>
      </section>
    </div>
    <div v-if="mobileSidebarOpen" class="scrim" @click="mobileSidebarOpen = false" />
  </div>
</template>
