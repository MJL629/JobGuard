import api from './index'

export const login = (username, password) =>
  api.post('/auth/login', { username, password })

export const register = (username, password, email = null) =>
  api.post('/auth/register', { username, password, email })

