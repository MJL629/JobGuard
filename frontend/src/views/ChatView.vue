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
          <div class="message-text">{{ msg.content }}</div>
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
          <div v-if="statusMessage" class="step-status">{{ statusMessage }}</div>
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
            accept=".txt,.md,.pdf,.docx,.png,.jpg,.jpeg,.webp"
            :on-change="handleFileChange"
            :disabled="loading"
          >
            <el-button :icon="Paperclip" circle size="small" title="上传简历/文件" />
          </el-upload>
          <el-upload
            action="#"
            :auto-upload="false"
            :show-file-list="false"
            accept=".png,.jpg,.jpeg,.webp"
            :on-change="handleJobImageChange"
            :disabled="loading"
          >
            <el-button :icon="Picture" circle size="small" title="上传岗位截图进行避雷分析" />
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
import { createSession, getHistory, getStreamEvents, sendMessage as sendChatMessage } from '../api/chat'
import { uploadMyResume } from '../api/profile'
import { analyzeJobImage } from '../api/jobs'
import { Promotion, Paperclip, Picture } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const inputText = ref('')
const loading = ref(false)
const messages = ref([])
const messagesContainer = ref(null)
const sessionId = ref(null)
const backendStatus = ref('disconnected')
const statusMessage = ref('')

const mapHistoryMessage = (msg) => ({
  role: msg.role,
  content: msg.content,
  time: msg.created_at ? new Date(msg.created_at).toLocaleTimeString() : '',
})

const startNewSession = async () => {
  const res = await createSession('profile_building')
  sessionId.value = res.session_id
  sessionStorage.setItem('chat_session_id', String(res.session_id))
  backendStatus.value = 'connected'
  if (res.first_message) {
    messages.value.push({
      role: 'assistant',
      content: res.first_message,
      time: new Date().toLocaleTimeString(),
      meta: { completeness: res.completeness },
    })
  }
}

// 初始化：优先恢复当前浏览器会话，否则由后端主动发起画像对话。
onMounted(async () => {
  try {
    const savedSessionId = Number(sessionStorage.getItem('chat_session_id'))
    if (savedSessionId) {
      try {
        const history = await getHistory(savedSessionId)
        sessionId.value = savedSessionId
        messages.value = (history.messages || []).map(mapHistoryMessage)
        backendStatus.value = 'connected'
        return
      } catch {
        sessionStorage.removeItem('chat_session_id')
      }
    }
    await startNewSession()
  } catch (e) {
    console.warn('后端未连接:', e.message)
    backendStatus.value = 'disconnected'
    messages.value.push({
      role: 'assistant',
      content: '暂时无法创建画像会话，请检查登录状态或后端服务后重试。',
      time: new Date().toLocaleTimeString(),
    })
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
    loading.value = false
    messages.value.push({
      role: 'assistant',
      content: '后端当前不可用，消息没有被处理。请恢复服务后重试。',
      time: new Date().toLocaleTimeString(),
    })
  }
}

const sendViaSSE = async (text) => {
  let streamId = ''
  let contiguousSequence = 0
  let maxSequence = 0
  let streamCompleted = false
  const seenEventIds = new Set()
  const receivedSequences = new Set()

  const applyEvent = (eventType, data, frameEventId = '') => {
    const eventId = frameEventId || data.event_id || ''
    if (eventId && seenEventIds.has(eventId)) return
    if (eventId) seenEventIds.add(eventId)

    const sequence = Number(data.sequence || 0)
    if (sequence > 0) {
      receivedSequences.add(sequence)
      maxSequence = Math.max(maxSequence, sequence)
      while (receivedSequences.has(contiguousSequence + 1)) contiguousSequence += 1
    }
    if (eventType === 'done') streamCompleted = true
    handleSSEEvent(eventType, data)
  }

  const replayMissingEvents = async () => {
    if (!streamId) return false
    const replay = await getStreamEvents(sessionId.value, streamId, contiguousSequence)
    const events = [...(replay.events || [])].sort((a, b) => a.sequence - b.sequence)
    for (const event of events) {
      applyEvent(event.event, event.data || {}, event.id)
    }
    return Boolean(replay.completed && streamCompleted && contiguousSequence >= Number(replay.last_sequence || 0))
  }

  try {
    const response = await sendChatMessage(sessionId.value, text)

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`)
    }
    streamId = response.headers.get('X-Stream-ID') || ''

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    const processFrame = (frame) => {
      if (!frame.trim()) return
      let eventType = 'message'
      let eventId = ''
      const dataLines = []
      for (const line of frame.split(/\r?\n/)) {
        if (line.startsWith('id:')) {
          eventId = line.slice(3).trim()
        } else if (line.startsWith('event:')) {
          eventType = line.slice(6).trim() || 'message'
        } else if (line.startsWith('data:')) {
          dataLines.push(line.slice(5).replace(/^ /, ''))
        }
      }
      if (!dataLines.length) return
      try {
        const data = JSON.parse(dataLines.join('\n'))
        streamId = streamId || data.stream_id || ''
        applyEvent(eventType, data, eventId)
      } catch (error) {
        console.warn('忽略无法解析的 SSE 事件:', error)
      }
    }

    const consumeFrames = (flush = false) => {
      const frames = buffer.split(/\r?\n\r?\n/)
      buffer = flush ? '' : (frames.pop() || '')
      for (const frame of frames) processFrame(frame)
      if (flush && buffer.trim()) processFrame(buffer)
    }

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      consumeFrames()
    }
    buffer += decoder.decode()
    consumeFrames(true)

    if (!streamCompleted || contiguousSequence < maxSequence) {
      const recovered = await replayMissingEvents()
      if (!recovered) throw new Error('流式响应不完整')
    }
  } catch (e) {
    console.error('SSE 请求失败:', e)
    let recovered = false
    try {
      recovered = await replayMissingEvents()
    } catch (replayError) {
      console.warn('SSE 补偿失败:', replayError)
    }
    if (!recovered) {
      messages.value.push({
        role: 'assistant',
        content: `消息流中断：${e.message || '网络连接异常'}。已保留服务器成功保存的内容，请重试未完成的操作。`,
        time: new Date().toLocaleTimeString(),
      })
    }
  } finally {
    loading.value = false
    statusMessage.value = ''
    nextTick(() => scrollToBottom())
  }
}

const handleSSEEvent = (eventType, data) => {
  if (eventType === 'status') {
    statusMessage.value = data.message || '正在处理...'
    return
  }
  if (eventType === 'profile_updated') {
    const fields = (data.updated_fields || []).join('、')
    ElMessage.success(fields ? `画像已更新：${fields}` : '画像已更新')
    return
  }
  if (eventType === 'resume_parsed' && data.summary) {
    messages.value.push({
      role: 'assistant',
      content: `📄 简历解析完成！\n${data.summary}`,
      time: new Date().toLocaleTimeString(),
      meta: { completeness: data.completeness },
    })
    return
  }
  if (eventType === 'message' && data.content) {
    messages.value.push({
      role: 'assistant',
      content: data.content,
      time: new Date().toLocaleTimeString(),
    })
    return
  }
  if (eventType === 'analysis_complete' && data.summary) {
    statusMessage.value = '岗位分析已完成'
    return
  }
  if (eventType === 'error') {
    messages.value.push({
      role: 'assistant',
      content: `处理失败：${data.message || '未知错误'}`,
      time: new Date().toLocaleTimeString(),
    })
  }
}

const handleFileChange = async (uploadFile) => {
  const file = uploadFile.raw
  if (!file) return

  const validTypes = ['.txt', '.md', '.pdf', '.docx', '.png', '.jpg', '.jpeg', '.webp']
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
    try {
      const data = await uploadMyResume(file)
      if (data.code === 0) {
        const d = data.data
        messages.value.push({
          role: 'assistant',
          content: `📄 简历解析完成！\n\n- 学历: ${d.summary.degree || '未知'}\n- 学校: ${d.summary.school || '未知'}\n- 项目: ${d.summary.projects_count} 个\n- 技能: ${d.summary.skills_count} 个\n- 识别文字: ${d.file?.extracted_chars || 0} 字${d.file?.ocr_used ? '（本地 OCR）' : ''}\n- 画像完整度: ${d.completeness}%`,
          time: new Date().toLocaleTimeString(),
          meta: { completeness: d.completeness },
        })
      } else {
        throw new Error(data.detail || data.message || '解析失败')
      }
    } catch (e) {
      const detail = e.response?.data?.detail
      const reason = detail?.message || detail || e.message || '未知错误'
      messages.value.push({
        role: 'assistant',
        content: `文件上传失败：${reason}。请根据提示调整文件后重试。`,
        time: new Date().toLocaleTimeString(),
      })
    }
  } else {
    // 降级：前端读取文本内容
    if (file.type === 'application/pdf' || file.type.startsWith('image/') ||
        file.name.endsWith('.pdf') || file.name.endsWith('.docx')) {
      messages.value.push({
        role: 'assistant',
        content: 'PDF、DOCX 和图片识别需要后端支持。后端未连接，请直接粘贴简历文本。',
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

const handleJobImageChange = async (uploadFile) => {
  const file = uploadFile.raw
  if (!file) return
  messages.value.push({
    role: 'user',
    content: `🖼️ 上传了岗位截图：${file.name}`,
    time: new Date().toLocaleTimeString(),
  })
  if (backendStatus.value !== 'connected') {
    messages.value.push({
      role: 'assistant',
      content: '后端未连接，岗位截图没有被处理。请恢复服务后重试。',
      time: new Date().toLocaleTimeString(),
    })
    return
  }

  loading.value = true
  statusMessage.value = '正在 OCR 识别岗位截图并分析风险...'
  try {
    const response = await analyzeJobImage(file, sessionId.value)
    if (response.code !== 0) throw new Error(response.message || '岗位截图分析失败')
    const data = response.data
    const report = data.report || {}
    messages.value.push({
      role: 'assistant',
      content: `## 岗位截图分析完成\n\n- 企业：${data.job_info?.company_name || '未识别'}\n- 岗位：${data.job_info?.job_title || '未识别'}\n- OCR：识别 ${data.image_ocr?.extracted_chars || 0} 字\n- 风险：${report.recommendation_text || report.risk_level || '待核实'}\n\n${report.summary || ''}\n\n${report.advice || ''}`,
      time: new Date().toLocaleTimeString(),
    })
  } catch (error) {
    const detail = error.response?.data?.detail
    const reason = detail?.message || detail || error.message || '未知错误'
    messages.value.push({
      role: 'assistant',
      content: `岗位截图分析失败：${reason}`,
      time: new Date().toLocaleTimeString(),
    })
  } finally {
    loading.value = false
    statusMessage.value = ''
    nextTick(() => scrollToBottom())
  }
}

const quickStart = () => {
  inputText.value = '你好，我想建立我的求职画像'
  sendMessage()
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

.step-status {
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
}

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
