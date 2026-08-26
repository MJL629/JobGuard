import api from './index'

export const generateResume = (userId, jobId, jobInfo = null, options = {}) =>
  api.post('/resume/generate', { user_id: userId, job_id: jobId, job_info: jobInfo, options })

export const getResume = (resumeId) => api.get(`/resume/${resumeId}`)

export const downloadResume = (resumeId) =>
  `http://localhost:8000/api/resume/${resumeId}/download`

export const getResumeHistory = (userId) =>
  api.get('/resume/user/history', { params: { user_id: userId } })
