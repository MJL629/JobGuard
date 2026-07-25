import api from './index'

export const getProfile = (userId) => api.get(`/profile/${userId}`)

export const uploadResume = (userId, file) => {
  const formData = new FormData()
  formData.append('file', file)
  return api.post(`/profile/${userId}/upload-resume`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export const addProject = (userId, data) =>
  api.post(`/profile/${userId}/projects`, data)

export const deleteProject = (userId, projectId) =>
  api.delete(`/profile/${userId}/projects/${projectId}`)
