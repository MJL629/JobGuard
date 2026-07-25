import api from './index'

/**
 * 创建对话会话
 */
export const createSession = (userId, sessionType = 'general') => {
  return api.post('/chat/session', { user_id: userId, session_type: sessionType })
}

/**
 * 发送消息（SSE 流式）
 */
export const sendMessage = (sessionId, content, messageType = 'text') => {
  // SSE 流式请求需要特殊处理，不通过 axios
  const token = localStorage.getItem('token')
  return fetch(`http://localhost:8000/api/chat/${sessionId}/message`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ content, message_type: messageType }),
  })
}

/**
 * 获取对话历史
 */
export const getHistory = (sessionId) => {
  return api.get(`/chat/${sessionId}/history`)
}
