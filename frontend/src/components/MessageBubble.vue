<script setup lang="ts">
import { computed, ref } from 'vue'
import { ArrowUpRight, ChevronDown, FileText } from 'lucide-vue-next'
import { marked } from 'marked'
import type { Message } from '../types/chat'

const props = defineProps<{ message: Message; isTyping?: boolean }>()
const showSources = ref(false)

function sanitize(html: string) {
  if (typeof window === 'undefined') return html
  const document = new DOMParser().parseFromString(html, 'text/html')
  document.querySelectorAll('script, style, iframe, object, embed, form').forEach((node) => node.remove())
  document.querySelectorAll('*').forEach((element) => {
    Array.from(element.attributes).forEach((attribute) => {
      if (attribute.name.toLowerCase().startsWith('on')) element.removeAttribute(attribute.name)
      if ((attribute.name === 'href' || attribute.name === 'src') && /^javascript:/i.test(attribute.value)) {
        element.removeAttribute(attribute.name)
      }
    })
  })
  return document.body.innerHTML
}

const renderedContent = computed(() => sanitize(marked.parse(props.message.content || '', { breaks: true, gfm: true }) as string))

function sourceLabel(source: { source?: string | null; section?: string | null; topic?: string | null }) {
  return [source.source, source.section, source.topic].filter(Boolean).join(' · ') || '知识库相关内容'
}
</script>

<template>
  <div :class="['message-bubble-stack', message.role]">
    <div :class="['message-bubble', message.role, { 'typing-bubble': isTyping }]">
    <template v-if="isTyping"><span /><span /><span /></template>
    <div v-else-if="message.role === 'assistant'" class="markdown-content" v-html="renderedContent" />
    <p v-else>{{ message.content }}</p>
    </div>
  <div class="message-meta">{{ message.role === 'assistant' ? 'WhiteBear AI' : '你' }} · {{ isTyping ? '正在处理' : message.time }}</div>
  <button v-if="message.sources.length" class="source-toggle" type="button" @click="showSources = !showSources">
    <FileText :size="13" />{{ message.sources.length }} 个依据<ChevronDown :size="13" :class="{ rotate: showSources }" />
  </button>
  <div v-if="message.sources.length && showSources" class="source-list">
    <div v-for="(source, index) in message.sources" :key="`${sourceLabel(source)}-${index}`" class="source-item">
      <span class="source-dot" /><div class="source-copy"><b>{{ sourceLabel(source) }}</b><span v-if="source.content">{{ source.content }}</span></div><ArrowUpRight :size="13" />
    </div>
  </div>
  </div>
</template>
