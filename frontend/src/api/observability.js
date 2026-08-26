import api from './index'

export const getAgentTraces = (params = {}) =>
  api.get('/observability/traces', { params })
