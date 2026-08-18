import api from './index'

export const getProfile = (userId) => api.get(`/profile/${userId}`)

export const getMyProfile = () => api.get('/profile/me')

export const updateMyProfile = (data) => api.patch('/profile/me', data)

export const uploadResume = (userId, file) => {
  const formData = new FormData()
  formData.append('file', file)
  return api.post(`/profile/${userId}/upload-resume`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export const uploadMyResume = (file) => {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/profile/me/upload-resume', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export const listMyResumes = () => api.get('/profile/me/resumes')

export const getMyResumeStatus = (resumeId) =>
  api.get(`/profile/me/resumes/${resumeId}`)

export const setPrimaryResume = (resumeId) =>
  api.patch(`/profile/me/resumes/${resumeId}/primary`)

export const addMyExperience = (data) => api.post('/profile/me/experiences', data)

export const addProject = (userId, data) =>
  api.post(`/profile/${userId}/projects`, data)

export const deleteProject = (userId, projectId) =>
  api.delete(`/profile/${userId}/projects/${projectId}`)
