import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useUserStore = defineStore('user', () => {
  const user = ref(null)
  const token = ref(localStorage.getItem('token') || '')
  const profile = ref(null)

  const isLoggedIn = computed(() => !!token.value)

  const setToken = (newToken) => {
    token.value = newToken
    localStorage.setItem('token', newToken)
  }

  const logout = () => {
    token.value = ''
    user.value = null
    profile.value = null
    localStorage.removeItem('token')
  }

  return {
    user,
    token,
    profile,
    isLoggedIn,
    setToken,
    logout,
  }
})
