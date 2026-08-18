import api from './index'

export const listJobs = (params = {}) => api.get('/jobs', { params })

export const recommendJobs = (params = {}) =>
  api.get('/jobs/recommend', { params })

export const analyzeJob = (text, messageType = 'text', jobId = null) =>
  api.post('/jobs/analyze', {
    text,
    message_type: messageType,
    job_id: jobId,
  }, { timeout: 120000 })

export const analyzeJobImage = (file, sessionId = null) => {
  const formData = new FormData()
  formData.append('file', file)
  if (sessionId) formData.append('session_id', String(sessionId))
  return api.post('/jobs/analyze-image', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  })
}

export const getJobDetail = (jobId) => api.get(`/jobs/${jobId}`)

export const getJobAnalysis = (jobId) => api.get(`/jobs/${jobId}/analysis`)
