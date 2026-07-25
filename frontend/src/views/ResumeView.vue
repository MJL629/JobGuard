<template>
  <div class="resume-view">
    <div class="page-header">
      <h2>Resume Manager</h2>
      <el-tag v-if="!resumeData" type="info">No resume generated yet</el-tag>
      <el-tag v-else type="success">Ready</el-tag>
    </div>

    <!-- Generate Section -->
    <div class="generate-card" v-if="!resumeData && !loading">
      <h3>Generate Tailored Resume</h3>
      <p>Select a job you've analyzed, and I'll generate a resume tailored to that position.</p>
      <el-form label-width="100px" style="margin-top: 16px;">
        <el-form-item label="Target Job">
          <el-select v-model="selectedJobId" placeholder="Select a job" style="width: 100%">
            <el-option label="Java Backend @ TechCorp (Demo)" :value="1" />
            <el-option label="Frontend Dev @ WebCo (Demo)" :value="2" />
          </el-select>
        </el-form-item>
        <el-form-item label="Max Projects">
          <el-input-number v-model="maxProjects" :min="1" :max="5" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="generateResume" :loading="loading">
            Generate Resume
          </el-button>
        </el-form-item>
      </el-form>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="loading-card">
      <el-icon class="is-loading" :size="32"><Loading /></el-icon>
      <p>Generating your tailored resume...</p>
      <p class="sub">Selecting best projects, rewriting descriptions, matching keywords...</p>
    </div>

    <!-- Resume Preview -->
    <div v-if="resumeData" class="resume-layout">
      <!-- Preview -->
      <div class="preview-panel">
        <div class="preview-header">
          <h3>Resume Preview</h3>
          <div class="preview-actions">
            <el-button size="small" @click="downloadResume" :icon="Download">Download PDF</el-button>
            <el-button size="small" type="primary" @click="resetResume">New Resume</el-button>
          </div>
        </div>
        <div class="resume-preview" v-html="renderedMarkdown"></div>
      </div>

      <!-- Sidebar: Greeting + Projects -->
      <div class="sidebar-panel">
        <!-- Greeting -->
        <div class="greeting-card" v-if="greetingText">
          <h4>📨 Greeting Message</h4>
          <div class="greeting-text">{{ greetingText }}</div>
          <el-button size="small" type="primary" text @click="copyGreeting">Copy</el-button>
        </div>

        <!-- Selected Projects -->
        <div class="projects-card" v-if="selectedProjects.length">
          <h4>📂 Selected Projects</h4>
          <div class="project-item" v-for="(p, i) in selectedProjects" :key="i">
            <div class="project-rank">#{{ i + 1 }}</div>
            <div class="project-info">
              <div class="project-name">{{ p.project_name }}</div>
              <el-progress
                :percentage="Math.round((p.relevance_score || 0.8) * 100)"
                :stroke-width="6"
                :color="progressColor(p.relevance_score)"
              />
            </div>
          </div>
        </div>

        <!-- History -->
        <div class="history-card">
          <h4>📜 History</h4>
          <div v-if="history.length === 0" class="empty-hint">No previous resumes</div>
          <div v-for="h in history" :key="h.id" class="history-item">
            <span>{{ h.job_title }} @ {{ h.company_name }}</span>
            <span class="history-date">{{ formatDate(h.created_at) }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { marked } from 'marked'

const loading = ref(false)
const selectedJobId = ref(null)
const maxProjects = ref(3)
const resumeData = ref(null)
const greetingText = ref('')
const selectedProjects = ref([])
const history = ref([])

const renderedMarkdown = computed(() => {
  if (!resumeData.value) return ''
  return marked(resumeData.value)
})

const generateResume = async () => {
  loading.value = true
  await new Promise(r => setTimeout(r, 1500))

  resumeData.value = `# Zhang San

Beijing | zhangsan@email.com | 138-xxxx-xxxx

## Job Target
**Java Backend Developer**

## Self Evaluation
Computer Science graduate from Tsinghua University with hands-on experience in building scalable microservices. Proficient in Java ecosystem with proven ability to deliver high-performance backend systems handling millions of daily requests.

## Education
- **B.S. in Computer Science**, Tsinghua University, 2020-2024

## Skills
**Languages:** Java, Python, SQL | **Frameworks:** Spring Boot, MyBatis, Flask | **Infrastructure:** MySQL, Redis, Docker, Kubernetes | **Tools:** Git, Maven, Jenkins

## Project Experience

### E-commerce Microservice Platform
*Backend Developer* | 2023.03 - 2023.09

- Designed and implemented a microservice architecture serving 500K+ daily active users, reducing API latency by 40%
- Built a distributed order processing system using Spring Boot and RabbitMQ, handling 10K+ orders per minute
- Optimized MySQL queries with indexing and caching strategies, improving database response time by 60%

**Tech Stack:** Java, Spring Boot, MySQL, Redis, RabbitMQ, Docker

### Online Education System
*Full Stack Developer* | 2022.09 - 2023.01

- Developed a real-time collaborative learning platform supporting 1000+ concurrent users
- Implemented WebSocket-based live chat and notification system with 99.9% uptime

**Tech Stack:** Java, Spring Boot, Vue.js, WebSocket, MySQL`

  greetingText.value = 'Hello! I am very interested in the Java Backend Developer position at your company. My background in Computer Science from Tsinghua University, combined with hands-on experience building scalable microservice platforms, makes me a strong fit. I would love the opportunity to discuss how I can contribute to your team.'

  selectedProjects.value = [
    { project_name: 'E-commerce Microservice Platform', relevance_score: 0.95 },
    { project_name: 'Online Education System', relevance_score: 0.82 },
  ]

  history.value = [
    { id: 1, job_title: 'Java Backend', company_name: 'TechCorp', created_at: '2026-07-25T10:00:00' },
    { id: 2, job_title: 'Backend Engineer', company_name: 'DataFlow', created_at: '2026-07-24T15:30:00' },
  ]

  loading.value = false
}

const downloadResume = () => {
  const blob = new Blob([resumeData.value], { type: 'text/markdown' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = 'resume.md'; a.click()
  URL.revokeObjectURL(url)
}

const copyGreeting = () => {
  navigator.clipboard.writeText(greetingText.value)
}

const resetResume = () => {
  resumeData.value = null
  greetingText.value = ''
  selectedProjects.value = []
}

const progressColor = (score) => {
  if (score >= 0.9) return '#67c23a'
  if (score >= 0.7) return '#409eff'
  return '#e6a23c'
}

const formatDate = (d) => {
  if (!d) return ''
  return new Date(d).toLocaleDateString()
}
</script>

<style scoped>
.resume-view { max-width: 1100px; margin: 0 auto; }
.page-header { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; }
.page-header h2 { font-size: 20px; color: #303133; }

.generate-card {
  background: #fff; padding: 24px; border-radius: 8px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.06);
}
.generate-card h3 { margin-bottom: 8px; }
.generate-card p { color: #909399; font-size: 14px; }

.loading-card {
  text-align: center; padding: 60px; background: #fff; border-radius: 8px;
}
.loading-card p { margin-top: 16px; font-size: 16px; color: #303133; }
.loading-card .sub { font-size: 13px; color: #909399; }

.resume-layout { display: grid; grid-template-columns: 1fr 320px; gap: 20px; }

.preview-panel {
  background: #fff; border-radius: 8px; box-shadow: 0 2px 12px rgba(0,0,0,0.06);
  overflow: hidden;
}
.preview-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 16px 20px; border-bottom: 1px solid #ebeef5;
}
.preview-header h3 { font-size: 16px; }
.preview-actions { display: flex; gap: 8px; }

.resume-preview {
  padding: 32px 40px; font-size: 13px; line-height: 1.7;
}
.resume-preview :deep(h1) { font-size: 22px; margin-bottom: 4px; }
.resume-preview :deep(h2) { font-size: 16px; border-bottom: 2px solid #333; padding-bottom: 4px; margin-top: 20px; }
.resume-preview :deep(h3) { font-size: 14px; margin-bottom: 4px; }
.resume-preview :deep(ul) { padding-left: 20px; }
.resume-preview :deep(li) { margin-bottom: 4px; }
.resume-preview :deep(strong) { color: #303133; }

.sidebar-panel { display: flex; flex-direction: column; gap: 16px; }

.greeting-card, .projects-card, .history-card {
  background: #fff; padding: 16px; border-radius: 8px;
  box-shadow: 0 1px 6px rgba(0,0,0,0.06);
}
.greeting-card h4, .projects-card h4, .history-card h4 {
  font-size: 14px; margin-bottom: 12px; color: #303133;
}

.greeting-text {
  font-size: 13px; line-height: 1.6; color: #606266;
  background: #f5f7fa; padding: 12px; border-radius: 6px; margin-bottom: 8px;
}

.project-item { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; }
.project-rank {
  width: 28px; height: 28px; border-radius: 50%; background: #409eff;
  color: #fff; display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 700; flex-shrink: 0;
}
.project-info { flex: 1; }
.project-name { font-size: 13px; font-weight: 600; margin-bottom: 4px; }

.history-item {
  display: flex; justify-content: space-between; padding: 6px 0;
  font-size: 13px; border-bottom: 1px solid #f2f3f5;
}
.history-date { color: #909399; font-size: 12px; }
.empty-hint { font-size: 13px; color: #c0c4cc; text-align: center; padding: 12px; }
</style>
