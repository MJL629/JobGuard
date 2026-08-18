import api from './index'

export const getAgentGraph = () => api.get('/agent/graph')
export const getAgentTools = () => api.get('/agent/tools')
export const getAgentRuns = (limit = 30) => api.get('/agent/runs', { params: { limit } })
export const getAgentMetrics = (days = 30) => api.get('/agent/metrics', { params: { days } })
export const executeAgentTool = (name, arguments_ = {}, confirmed = false) =>
  api.post(`/agent/tools/${name}/execute`, { arguments: arguments_, confirmed }, { timeout: 240000 })
