import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { login, register, getMe } from '../api/auth'

const readSavedUser = () => {
  try {
    return JSON.parse(localStorage.getItem('user') || 'null')
  } catch {
    localStorage.removeItem('user')
    return null
  }
}

export const useUserStore = defineStore('user', () => {
  const user = ref(readSavedUser())
  const token = ref(localStorage.getItem('token') || '')
  const refreshToken = ref(localStorage.getItem('refresh_token') || '')
  const profile = ref(null)

  const isLoggedIn = computed(() => !!token.value)

  const setToken = (newToken) => {
    token.value = newToken
    localStorage.setItem('token', newToken)
  }

  const setSession = (session) => {
    setToken(session.access_token)
    refreshToken.value = session.refresh_token
    user.value = { user_id: session.user_id, username: session.username }
    localStorage.setItem('refresh_token', session.refresh_token)
    localStorage.setItem('user', JSON.stringify(user.value))
  }

  const loginUser = async (username, password) => {
    const session = await login(username, password)
    setSession(session)
    return session
  }

  const registerUser = async (username, password, email = null) => {
    const session = await register(username, password, email)
    setSession(session)
    return session
  }

  const restoreSession = async () => {
    if (!token.value) return null
    const currentUser = await getMe()
    user.value = currentUser
    localStorage.setItem('user', JSON.stringify(currentUser))
    return currentUser
  }

  const logout = () => {
    token.value = ''
    user.value = null
    profile.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('refresh_token')
    localStorage.removeItem('user')
    sessionStorage.removeItem('chat_session_id')
  }

  return {
    user,
    token,
    refreshToken,
    profile,
    isLoggedIn,
    setToken,
    setSession,
    loginUser,
    registerUser,
    restoreSession,
    logout,
  }
})
