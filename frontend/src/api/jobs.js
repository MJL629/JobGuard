import api from './index'

export const listJobs = (params = {}) => api.get('/jobs', { params })

export const recommendJobs = (userId, params = {}) =>
  api.get('/jobs/recommend', { params: { user_id: userId, ...params } })

export const analyzeJob = (userId, text, messageType = 'job_link') =>
  api.post('/jobs/analyze', { user_id: userId, text, message_type: messageType })

export const getJobDetail = (jobId) => api.get(`/jobs/${jobId}`)

export const getJobAnalysis = (jobId, userId) =>
  api.get(`/jobs/${jobId}/analysis`, { params: { user_id: userId } })
