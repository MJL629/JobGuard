import api from './index'

export const listResumeTemplates = () => api.get('/resume/templates')

export const uploadResumeTemplate = (file) => {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/resume/templates/custom', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export const generateResume = (jobId, maxProjects = 3, templateId = 'template-01') =>
  api.post('/resume/generate', {
    job_id: jobId,
    options: { max_projects: maxProjects, template_id: templateId },
  }, { timeout: 240000 })

export const getResumeHistory = () => api.get('/resume/history')

export const getResume = (resumeId) => api.get(`/resume/${resumeId}`)

export const downloadResumeFile = (resumeId, format = 'pdf') =>
  api.get(`/resume/${resumeId}/download`, {
    params: { format },
    responseType: 'blob',
    timeout: 120000,
  })
