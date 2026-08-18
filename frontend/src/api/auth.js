import api from './index'

export const login = (username, password) =>
  api.post('/auth/login', { username, password })

export const register = (username, password, email = null) =>
  api.post('/auth/register', { username, password, email })

export const getMe = () => api.get('/auth/me')

export const refreshAccessToken = (refreshToken) =>
  api.post('/auth/refresh', { refresh_token: refreshToken })
