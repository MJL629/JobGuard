import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useChatStore = defineStore('chat', () => {
  const currentSessionId = ref(null)
  const sessions = ref([])
  const messages = ref([])
  const loading = ref(false)

  const addMessage = (msg) => {
    messages.value.push(msg)
  }

  const clearMessages = () => {
    messages.value = []
  }

  return {
    currentSessionId,
    sessions,
    messages,
    loading,
    addMessage,
    clearMessages,
  }
})
