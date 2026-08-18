import api from './index'

/**
 * 创建对话会话
 */
export const createSession = (sessionType = 'profile_building') => {
  return api.post('/chat/session', { session_type: sessionType })
}

/**
 * 发送消息（SSE 流式）
 */
export const sendMessage = (sessionId, content, messageType = 'text') => {
  // SSE 流式请求需要特殊处理，不通过 axios
  const token = localStorage.getItem('token')
  return fetch(`/api/chat/${sessionId}/message`, {
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

/** 获取服务器已经保存的流事件，用于缺序或连接中断后的补偿。 */
export const getStreamEvents = (sessionId, streamId, afterSequence = 0) =>
  api.get(`/chat/${sessionId}/events`, {
    params: { stream_id: streamId, after_sequence: afterSequence },
  })
