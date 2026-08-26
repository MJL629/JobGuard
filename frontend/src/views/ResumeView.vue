<template>
  <div class="resume-view">
    <div class="page-header">
      <h2>简历管理</h2>
      <el-tag v-if="!resumeData" type="info">尚未生成简历</el-tag>
      <el-tag v-else type="success">简历已生成</el-tag>
    </div>

    <div class="resume-layout">
      <div class="main-panel">
        <!-- Generate Section -->
        <div class="generate-card" v-if="!resumeData && !loading">
          <h3>生成岗位定制简历</h3>
          <p>请选择一个已经分析过的目标岗位，系统将根据岗位要求生成定制简历。</p>
          <el-form label-width="100px" style="margin-top: 16px;">
            <el-form-item label="目标岗位">
              <el-select v-model="selectedJobId" placeholder="请选择目标岗位" filterable style="width: 100%">
                <el-option v-for="job in jobs" :key="job.id" :label="`${job.job_title}｜${job.company_name}`" :value="job.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="最多项目数">
              <el-input-number v-model="maxProjects" :min="1" :max="5" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="generateResume" :loading="loading" :disabled="!selectedJobId">
                生成定制简历
              </el-button>
            </el-form-item>
          </el-form>
        </div>

        <!-- Loading -->
        <div v-if="loading" class="loading-card">
          <el-icon class="is-loading" :size="32"><Loading /></el-icon>
          <p>正在生成岗位定制简历……</p>
          <p class="sub">正在筛选相关项目、改写经历描述并匹配岗位关键词……</p>
        </div>

        <!-- Resume Preview -->
        <div v-if="resumeData" class="preview-panel">
          <div class="preview-header">
            <h3>简历预览</h3>
            <div class="preview-actions">
              <el-button size="small" @click="downloadResume" :icon="Download">下载简历</el-button>
              <el-button size="small" type="primary" @click="resetResume">重新生成</el-button>
            </div>
          </div>
          <div class="resume-preview" v-html="renderedMarkdown"></div>
        </div>
      </div>

      <div class="sidebar-panel">
        <div class="greeting-card" v-if="greetingText">
          <h4>招呼语</h4>
          <div class="greeting-text">{{ greetingText }}</div>
          <el-button size="small" type="primary" text @click="copyGreeting">复制招呼语</el-button>
        </div>

        <div class="projects-card" v-if="selectedProjects.length">
          <h4>已选项目</h4>
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

        <div class="history-card">
          <h4>生成记录</h4>
          <div v-if="history.length === 0" class="empty-hint">暂无历史简历</div>
          <div v-for="h in history" :key="h.id" class="history-item" @click="loadResumeFromHistory(h.id)">
            <span class="history-title">{{ h.job_title }}｜{{ h.company_name }}（第 {{ h.version }} 版）</span>
            <span class="history-date">{{ formatDate(h.created_at) }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { marked } from 'marked'
import { ElMessage } from 'element-plus'
import { recommendJobs } from '../api/jobs'
import { generateResume as requestResume, getResume, getResumeHistory } from '../api/resume'
import { useUserStore } from '../stores/user'

const route = useRoute()
const userStore = useUserStore()
const loading = ref(false)
const selectedJobId = ref(null)
const maxProjects = ref(3)
const resumeData = ref(null)
const greetingText = ref('')
const selectedProjects = ref([])
const history = ref([])
const jobs = ref([])
const resumeId = ref(null)

const renderedMarkdown = computed(() => {
  if (!resumeData.value) return ''
  return marked(resumeData.value)
})

const generateResume = async () => {
  loading.value = true
  try {
    const res = await requestResume(userStore.user.id, selectedJobId.value, null, { max_projects: maxProjects.value })
    if (res.code !== 0) throw new Error(res.message || '生成失败')
    const data = res.data
    resumeId.value = data.resume_id
    resumeData.value = data.resume_markdown
    greetingText.value = data.greeting || ''
    selectedProjects.value = data.selected_projects || []
    await loadHistory()
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error.message || '简历生成失败')
  } finally {
    loading.value = false
  }
}

const downloadResume = () => {
  if (resumeId.value) {
    window.open(`http://localhost:8000/api/resume/${resumeId.value}/download`, '_blank')
    return
  }
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

const loadHistory = async () => {
  const res = await getResumeHistory(userStore.user.id)
  history.value = res.data?.items || []
}

const loadResumeFromHistory = async (id) => {
  try {
    const res = await getResume(id)
    if (res.code !== 0) throw new Error(res.message || '读取失败')
    const data = res.data
    resumeId.value = data.id
    selectedJobId.value = data.job_id
    resumeData.value = data.resume_markdown
    greetingText.value = data.greeting_text || ''
    selectedProjects.value = data.selected_projects || []
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error.message || '历史简历读取失败')
  }
}

onMounted(async () => {
  try {
    const [jobRes] = await Promise.all([
      recommendJobs(userStore.user.id, { page: 1, page_size: 100 }),
      loadHistory(),
    ])
    jobs.value = jobRes.data?.items || []
    const queryJobId = Number(route.query.job_id)
    if (queryJobId) {
      selectedJobId.value = queryJobId
      if (!jobs.value.some(job => Number(job.id) === queryJobId)) {
        const moreJobs = await recommendJobs(userStore.user.id, { page: 1, page_size: 100, sub_category: 'agent_algo' })
        jobs.value = [...jobs.value, ...(moreJobs.data?.items || [])]
      }
    }
  } catch (error) {
    ElMessage.error('简历页面数据加载失败')
  }
})
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

.resume-layout { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 20px; align-items: start; }
.main-panel { min-width: 0; }

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
  display: flex; flex-direction: column; gap: 4px; padding: 8px 0;
  font-size: 13px; border-bottom: 1px solid #f2f3f5;
  cursor: pointer;
}
.history-item:hover { color: #409eff; }
.history-title { line-height: 1.45; }
.history-date { color: #909399; font-size: 12px; }
.empty-hint { font-size: 13px; color: #c0c4cc; text-align: center; padding: 12px; }

@media (max-width: 960px) {
  .resume-layout { grid-template-columns: 1fr; }
}
</style>
