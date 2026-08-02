<template>
  <div class="chat-view">
    <div class="chat-header">
      <h2>对话助手</h2>
      <el-tag :type="backendStatus === 'connected' ? 'success' : 'warning'" size="small">
        {{ backendStatus === 'connected' ? '已连接' : '未连接后端' }}
      </el-tag>
      <el-tag v-if="sessionId" type="info" size="small">会话 #{{ sessionId }}</el-tag>
    </div>

    <div class="chat-messages" ref="messagesContainer">
      <div class="welcome-card" v-if="messages.length === 0">
        <div class="welcome-icon">🛡️</div>
        <h3>欢迎使用 JobGuard</h3>
        <p>我是你的求职助手，可以帮你：</p>
        <div class="feature-list">
          <div class="feature-item">
            <el-icon color="#409eff"><Warning /></el-icon>
            <span>分析岗位，识别垃圾岗位和虚假宣传</span>
          </div>
          <div class="feature-item">
            <el-icon color="#67c23a"><Document /></el-icon>
            <span>针对岗位智能生成简历和招呼语</span>
          </div>
          <div class="feature-item">
            <el-icon color="#e6a23c"><Briefcase /></el-icon>
            <span>根据你的画像推荐适合的岗位</span>
          </div>
        </div>
        <p class="hint">你可以：粘贴岗位链接让我分析、上传简历让我帮你优化、或者直接告诉我你想找什么工作</p>
        <el-button type="primary" style="margin-top: 12px" @click="quickStart">
          快速开始 → 建立我的求职画像
        </el-button>
      </div>

      <div
        v-for="(msg, index) in messages"
        :key="index"
        class="message"
        :class="msg.role"
      >
        <div class="message-avatar">
          <el-avatar v-if="msg.role === 'user'" :size="36" icon="UserFilled" />
          <el-avatar v-else :size="36" style="background: #409eff">JG</el-avatar>
        </div>
        <div class="message-content">
          <div class="message-text" v-html="formatMessage(msg.content)"></div>
          <div v-if="msg.meta" class="message-meta">
            <el-tag v-if="msg.meta.completeness" size="small" type="success">
              画像完整度 {{ msg.meta.completeness }}%
            </el-tag>
          </div>
          <div class="message-time">{{ msg.time }}</div>
        </div>
      </div>

      <div v-if="loading" class="message assistant">
        <div class="message-avatar">
          <el-avatar :size="36" style="background: #409eff">JG</el-avatar>
        </div>
        <div class="message-content">
          <div class="typing-indicator">
            <span></span><span></span><span></span>
          </div>
        </div>
      </div>
    </div>

    <div class="chat-input">
      <el-input
        v-model="inputText"
        type="textarea"
        :rows="2"
        placeholder="描述你的求职需求，或粘贴简历内容..."
        @keydown.enter.exact.prevent="sendMessage"
        :disabled="loading"
      />
      <div class="input-actions">
        <div class="input-left">
          <el-upload
            action="#"
            :auto-upload="false"
            :show-file-list="false"
            accept=".txt,.md,.pdf,.doc,.docx"
            :on-change="handleFileChange"
            :disabled="loading"
          >
            <el-button :icon="Paperclip" circle size="small" title="上传简历/文件" />
          </el-upload>
          <span class="char-count" v-if="inputText.length > 0">{{ inputText.length }} 字</span>
        </div>
        <el-button type="primary" :icon="Promotion" @click="sendMessage" :disabled="!inputText.trim() || loading">
          发送
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted } from 'vue'
import { createSession, sendMessage as sendChatMessage } from '../api/chat'
import { Promotion, Paperclip } from '@element-plus/icons-vue'

const inputText = ref('')
const loading = ref(false)
const messages = ref([])
const messagesContainer = ref(null)
const sessionId = ref(null)
const backendStatus = ref('disconnected')

// 初始化：创建会话
onMounted(async () => {
  try {
    const res = await createSession(1, 'general')  // 默认用户 ID=1
    sessionId.value = res.session_id
    backendStatus.value = 'connected'
  } catch (e) {
    console.warn('后端未连接:', e.message)
    backendStatus.value = 'disconnected'
  }
})

const sendMessage = async () => {
  const text = inputText.value.trim()
  if (!text) return

  // 添加用户消息
  messages.value.push({
    role: 'user',
    content: text,
    time: new Date().toLocaleTimeString(),
  })
  inputText.value = ''
  loading.value = true

  await nextTick()
  scrollToBottom()

  if (sessionId.value && backendStatus.value === 'connected') {
    await sendViaSSE(text)
  } else {
    // 后端未连接，使用降级回复
    sendMockResponse(text)
  }
}

const sendViaSSE = async (text) => {
  try {
    const response = await sendChatMessage(sessionId.value, text)

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let assistantContent = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('event: ')) {
          const eventType = line.slice(7).trim()
          continue
        }
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6))
            handleSSEEvent(data)
            if (data.content) {
              assistantContent = data.content
            }
          } catch (e) {
            // 非 JSON 数据，跳过
          }
        }
      }
    }

    loading.value = false
    if (assistantContent) {
      messages.value.push({
        role: 'assistant',
        content: assistantContent,
        time: new Date().toLocaleTimeString(),
      })
    }
  } catch (e) {
    console.error('SSE 请求失败:', e)
    loading.value = false
    sendMockResponse(text)
  }
}

const handleSSEEvent = (data) => {
  // 处理不同 SSE 事件类型
  switch (true) {
    case !!data.stage:
      // 状态更新事件
      break
    case !!data.updated_fields:
      // 画像更新事件
      break
    case !!data.summary:
      // 简历解析事件
      messages.value.push({
        role: 'assistant',
        content: `📄 简历解析完成！\n${data.summary}`,
        time: new Date().toLocaleTimeString(),
        meta: { completeness: data.completeness },
      })
      break
  }
}

const handleFileChange = async (uploadFile) => {
  const file = uploadFile.raw
  if (!file) return

  const validTypes = ['.txt', '.md', '.pdf', '.doc', '.docx']
  const ext = '.' + file.name.split('.').pop().toLowerCase()
  if (!validTypes.includes(ext)) {
    messages.value.push({
      role: 'assistant',
      content: `不支持的文件格式（${ext}）。支持: ${validTypes.join(', ')}`,
      time: new Date().toLocaleTimeString(),
    })
    return
  }

  // 显示上传中
  messages.value.push({
    role: 'user',
    content: `📎 上传了文件: ${file.name}`,
    time: new Date().toLocaleTimeString(),
  })

  if (backendStatus.value === 'connected') {
    // 使用后端上传 API
    try {
      const formData = new FormData()
      formData.append('file', file)
      const res = await fetch(`/api/profile/1/upload-resume`, {
        method: 'POST',
        body: formData,
      })
      const data = await res.json()
      if (data.code === 0) {
        const d = data.data
        messages.value.push({
          role: 'assistant',
          content: `📄 简历解析完成！\n\n- 学历: ${d.summary.degree || '未知'}\n- 学校: ${d.summary.school || '未知'}\n- 项目: ${d.summary.projects_count} 个\n- 技能: ${d.summary.skills_count} 个\n- 画像完整度: ${d.completeness}%`,
          time: new Date().toLocaleTimeString(),
          meta: { completeness: d.completeness },
        })
      } else {
        throw new Error(data.detail || '解析失败')
      }
    } catch (e) {
      messages.value.push({
        role: 'assistant',
        content: `文件上传失败: ${e.message}。请尝试直接粘贴简历文本。`,
        time: new Date().toLocaleTimeString(),
      })
    }
  } else {
    // 降级：前端读取文本内容
    if (file.type === 'application/pdf' || file.name.endsWith('.pdf') ||
        file.name.endsWith('.doc') || file.name.endsWith('.docx')) {
      messages.value.push({
        role: 'assistant',
        content: 'PDF/Word 文件需要后端支持。后端未连接，请直接粘贴简历文本。',
        time: new Date().toLocaleTimeString(),
      })
      return
    }

    const reader = new FileReader()
    reader.onload = (e) => {
      const text = e.target.result
      inputText.value = `[文件: ${file.name}]\n\n${text}`
    }
    reader.onerror = () => {
      messages.value.push({
        role: 'assistant',
        content: `文件读取失败: ${file.name}`,
        time: new Date().toLocaleTimeString(),
      })
    }
    reader.readAsText(file)
  }
}

const sendMockResponse = (text) => {
  setTimeout(() => {
    loading.value = false

    let response
    if (text.length > 200 && (
      text.includes('教育') || text.includes('项目') || text.includes('经历')
    )) {
      response = '简历内容已收到，但后端当前不可用，无法自动解析。请检查网络连接或稍后再试。'
    } else if (text.includes('岗位') || text.includes('链接') || text.includes('zhipin')) {
      response = '后端连接异常，暂时无法分析岗位。请检查服务状态或稍后再试。'
    } else {
      response = '后端连接异常，暂时无法处理你的请求。请检查服务状态或刷新页面重试。'
    }

    messages.value.push({
      role: 'assistant',
      content: response,
      time: new Date().toLocaleTimeString(),
    })
    nextTick(() => scrollToBottom())
  }, 800)
}

const quickStart = () => {
  inputText.value = '你好，我想建立我的求职画像'
  sendMessage()
}

const formatMessage = (text) => {
  if (!text) return ''
  // 简单的 Markdown 转换
  return text
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>')
    .replace(/•/g, '&nbsp;&nbsp;•')
}

const scrollToBottom = () => {
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}
</script>

<style scoped>
.chat-view {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 48px);
  max-width: 800px;
  margin: 0 auto;
}

.chat-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 16px;
  border-bottom: 1px solid #e4e7ed;
  margin-bottom: 16px;
}

.chat-header h2 {
  font-size: 20px;
  color: #303133;
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px 0;
}

.welcome-card {
  text-align: center;
  padding: 40px 20px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}

.welcome-icon {
  font-size: 48px;
  margin-bottom: 16px;
}

.welcome-card h3 {
  font-size: 22px;
  color: #303133;
  margin-bottom: 8px;
}

.welcome-card p {
  color: #606266;
  margin-bottom: 16px;
}

.feature-list {
  text-align: left;
  max-width: 400px;
  margin: 0 auto 16px;
}

.feature-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 0;
  color: #606266;
}

.hint {
  font-size: 13px;
  color: #909399;
}

.message {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}

.message.user {
  flex-direction: row-reverse;
}

.message-content {
  max-width: 70%;
}

.message.user .message-content {
  text-align: right;
}

.message-text {
  background: #fff;
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
}

.message.user .message-text {
  background: #409eff;
  color: #fff;
}

.message-meta {
  margin-top: 6px;
}

.message-time {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 12px 16px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
}

.typing-indicator span {
  width: 8px;
  height: 8px;
  background: #c0c4cc;
  border-radius: 50%;
  animation: typing 1.4s infinite ease-in-out;
}

.typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.4s; }

@keyframes typing {
  0%, 60%, 100% { transform: translateY(0); }
  30% { transform: translateY(-8px); }
}

.chat-input {
  background: #fff;
  border-radius: 12px;
  padding: 12px;
  box-shadow: 0 -2px 12px rgba(0, 0, 0, 0.04);
}

.input-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}

.input-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
}

.char-count {
  font-size: 12px;
  color: #909399;
}
</style>
