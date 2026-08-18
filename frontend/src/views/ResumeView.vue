<template>
  <div class="resume-view">
    <div class="page-header">
      <div>
        <h2>定向简历</h2>
        <p>只使用已保存的用户画像和目标岗位生成；事实核查未通过时不会保存结果。</p>
      </div>
      <el-tag :type="resumeData ? 'success' : 'info'">{{ resumeData ? '已生成' : '等待生成' }}</el-tag>
    </div>

    <el-alert
      title="真实性保护已启用"
      description="学校、技能、项目和量化数字必须能回溯到你的画像。模型核查失败或修正后仍有未核验内容时，本次生成会明确失败。"
      type="warning"
      show-icon
      :closable="false"
      style="margin-bottom: 16px"
    />

    <section class="generate-card">
      <el-form label-width="90px">
        <el-form-item label="目标岗位">
          <el-select v-model="selectedJobId" filterable placeholder="选择数据库中的岗位" style="width: 100%" :disabled="loadingJobs">
            <el-option
              v-for="job in jobs"
              :key="job.id"
              :label="`${job.job_title} · ${job.company_name}`"
              :value="job.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="项目数量">
          <el-input-number v-model="maxProjects" :min="1" :max="5" />
        </el-form-item>
        <el-form-item label="简历模板">
          <div class="template-grid">
            <button
              v-for="item in templates"
              :key="item.id"
              type="button"
              class="template-option"
              :class="{ active: selectedTemplateId === item.id }"
              @click="selectedTemplateId = item.id"
            >
              <span class="template-swatch" :style="{ backgroundColor: item.accent }" />
              <strong>{{ item.name }}</strong>
              <small>{{ item.description }}</small>
            </button>
          </div>
          <label class="custom-template-upload">
            <input type="file" accept=".docx" @change="handleTemplateUpload" />
            <span>{{ uploadingTemplate ? '正在上传模板...' : '上传自己的 DOCX 模板' }}</span>
          </label>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="generating" :disabled="!selectedJobId" @click="createResume">
            基于真实资料生成
          </el-button>
          <span class="form-hint">生成可能调用大模型，请勿重复点击。</span>
        </el-form-item>
      </el-form>
    </section>

    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" class="result-alert" />
    <el-alert
      v-if="generationWarning"
      :title="generationWarning"
      type="warning"
      show-icon
      :closable="false"
      class="result-alert"
    />

    <section v-if="generating" class="loading-card">
      <el-icon class="is-loading" :size="32"><Loading /></el-icon>
      <p>正在选择真实项目、生成草稿并执行事实核查...</p>
    </section>

    <div v-if="resumeData && !generating" class="resume-layout">
      <section class="preview-panel">
        <div class="preview-header">
          <div>
            <h3>简历预览</h3>
            <span v-if="factCheckPassed" class="verified">✓ 已通过生成时事实核查</span>
            <span v-else-if="isTextOnly" class="text-only">已降级为可复制文本版</span>
          </div>
          <div class="preview-actions">
            <el-button size="small" @click="copyResumeText">复制简历文案</el-button>
            <el-button size="small" :loading="downloading" @click="downloadCurrent('markdown')">下载 Markdown</el-button>
            <el-button size="small" :loading="downloading" :disabled="!docxAvailable" @click="downloadCurrent('docx')">下载 DOCX</el-button>
            <el-button size="small" :loading="downloading" :disabled="!pdfAvailable" @click="downloadCurrent('pdf')">下载 PDF</el-button>
            <el-button size="small" type="primary" @click="clearCurrent">生成新版本</el-button>
          </div>
        </div>
        <pre class="resume-preview">{{ resumeData }}</pre>
      </section>

      <aside class="sidebar-panel">
        <section v-if="greetingText" class="side-card">
          <h4>招呼语</h4>
          <div class="greeting-text">{{ greetingText }}</div>
          <el-button size="small" type="primary" text @click="copyGreeting">复制</el-button>
        </section>

        <section v-if="selectedProjects.length" class="side-card">
          <h4>选中的真实项目</h4>
          <div v-for="(project, index) in selectedProjects" :key="`${project.project_name}-${index}`" class="project-item">
            <div class="project-rank">{{ index + 1 }}</div>
            <div class="project-info">
              <div>{{ project.project_name || '未命名项目' }}</div>
              <el-progress :percentage="scorePercent(project.relevance_score)" :stroke-width="6" />
            </div>
          </div>
        </section>

        <section class="side-card">
          <h4>生成历史</h4>
          <el-skeleton v-if="loadingHistory" :rows="3" animated />
          <el-empty v-else-if="!history.length" description="暂无真实生成记录" :image-size="60" />
          <button v-for="item in history" v-else :key="item.id" class="history-item" type="button" @click="openHistory(item.id)">
            <span>{{ item.job_title || '未命名岗位' }} · {{ item.company_name || '未知公司' }}</span>
            <small>v{{ item.version }} · {{ formatDate(item.created_at) }}</small>
          </button>
        </section>
      </aside>
    </div>

    <section v-else-if="!generating" class="history-only side-card">
      <h3>生成历史</h3>
      <el-skeleton v-if="loadingHistory" :rows="3" animated />
      <el-empty v-else-if="!history.length" description="暂无真实生成记录" />
      <button v-for="item in history" v-else :key="item.id" class="history-item" type="button" @click="openHistory(item.id)">
        <span>{{ item.job_title || '未命名岗位' }} · {{ item.company_name || '未知公司' }}</span>
        <small>v{{ item.version }} · {{ formatDate(item.created_at) }}</small>
      </button>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import { listJobs } from '../api/jobs'
import { downloadResumeFile, generateResume, getResume, getResumeHistory, listResumeTemplates, uploadResumeTemplate } from '../api/resume'

const route = useRoute()
const jobs = ref([])
const history = ref([])
const selectedJobId = ref(null)
const maxProjects = ref(3)
const templates = ref([])
const selectedTemplateId = ref('template-01')
const uploadingTemplate = ref(false)
const currentResumeId = ref(null)
const resumeData = ref('')
const greetingText = ref('')
const selectedProjects = ref([])
const factCheck = ref(null)
const outputMode = ref('document')
const generationWarning = ref('')
const docxAvailable = ref(false)
const pdfAvailable = ref(false)
const loadingJobs = ref(false)
const loadingHistory = ref(false)
const generating = ref(false)
const downloading = ref(false)
const errorMessage = ref('')

const factCheckPassed = computed(() => ['completed', 'stored_after_pass', 'deterministic_grounded', 'text_only_fallback'].includes(factCheck.value?.verification_status))
const isTextOnly = computed(() => outputMode.value === 'text_only' || factCheck.value?.verification_status === 'text_only_fallback')

const loadJobs = async () => {
  loadingJobs.value = true
  try {
    const response = await listJobs({ page: 1, page_size: 100 })
    if (response.code !== 0) throw new Error(response.message || '岗位加载失败')
    jobs.value = response.data.items || []
    const queryJobId = Number(route.query.jobId)
    if (Number.isInteger(queryJobId) && jobs.value.some((job) => Number(job.id) === queryJobId)) {
      selectedJobId.value = queryJobId
    }
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || error.message || '岗位加载失败，请稍后重试'
  } finally {
    loadingJobs.value = false
  }
}

const loadHistory = async () => {
  loadingHistory.value = true
  try {
    const response = await getResumeHistory()
    if (response.code !== 0) throw new Error(response.message || '简历历史加载失败')
    history.value = response.data.items || []
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || error.message || '简历历史加载失败，请稍后重试'
  } finally {
    loadingHistory.value = false
  }
}

const loadTemplates = async () => {
  try {
    const response = await listResumeTemplates()
    if (response.code !== 0) throw new Error(response.message || '模板加载失败')
    templates.value = response.data.items || []
    if (!templates.value.some((item) => item.id === selectedTemplateId.value)) {
      selectedTemplateId.value = templates.value[0]?.id || 'template-01'
    }
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || error.message || '模板加载失败，请稍后重试'
  }
}

const handleTemplateUpload = async (event) => {
  const file = event.target.files?.[0]
  if (!file) return
  uploadingTemplate.value = true
  try {
    const response = await uploadResumeTemplate(file)
    if (response.code !== 0) throw new Error(response.message || '模板上传失败')
    await loadTemplates()
    selectedTemplateId.value = response.data.id
    ElMessage.success('自定义模板已保存并选中')
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || error.message || '模板上传失败，请确认是有效 DOCX 文件'
  } finally {
    uploadingTemplate.value = false
    event.target.value = ''
  }
}

const applyResume = (data, fromHistory = false) => {
  currentResumeId.value = data.resume_id || data.id
  resumeData.value = data.resume_markdown || ''
  greetingText.value = data.greeting ?? data.greeting_text ?? ''
  selectedProjects.value = data.selected_projects || []
  factCheck.value = data.fact_check || (fromHistory ? { verification_status: 'stored_after_pass' } : null)
  outputMode.value = data.output_mode || (data.docx_path || data.pdf_path ? 'document' : 'text_only')
  generationWarning.value = data.generation_warning || ''
  docxAvailable.value = Boolean(data.docx_path)
  pdfAvailable.value = Boolean(data.pdf_path)
  if (data.template_id) selectedTemplateId.value = data.template_id
  if (data.job_id) selectedJobId.value = Number(data.job_id)
}

const createResume = async () => {
  generating.value = true
  errorMessage.value = ''
  clearCurrent(false)
  try {
    const response = await generateResume(selectedJobId.value, maxProjects.value, selectedTemplateId.value)
    if (response.code !== 0) throw new Error(response.message || '简历生成失败')
    applyResume(response.data)
    await loadHistory()
    ElMessage.success(isTextOnly.value ? '已生成可复制文本版材料并保存' : '定向简历已生成并保存')
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || error.message || '简历生成失败，请稍后重试'
  } finally {
    generating.value = false
  }
}

const openHistory = async (resumeId) => {
  errorMessage.value = ''
  try {
    const response = await getResume(resumeId)
    if (response.code !== 0) throw new Error(response.message || '简历读取失败')
    applyResume(response.data, true)
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || error.message || '简历读取失败，请稍后重试'
  }
}

const downloadCurrent = async (format = 'pdf') => {
  if (!currentResumeId.value) return
  downloading.value = true
  try {
    const blob = await downloadResumeFile(currentResumeId.value, format)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    const extension = format === 'markdown' ? 'md' : format
    anchor.download = `jobguard-resume-${currentResumeId.value}.${extension}`
    anchor.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || '简历下载失败，请稍后重试'
  } finally {
    downloading.value = false
  }
}

const copyResumeText = async () => {
  try {
    await navigator.clipboard.writeText(resumeData.value)
    ElMessage.success('简历文案已复制')
  } catch {
    ElMessage.error('复制失败，请手动选择文本')
  }
}

const copyGreeting = async () => {
  try {
    await navigator.clipboard.writeText(greetingText.value)
    ElMessage.success('招呼语已复制')
  } catch {
    ElMessage.error('复制失败，请手动选择文本')
  }
}

const clearCurrent = (clearError = true) => {
  currentResumeId.value = null
  resumeData.value = ''
  greetingText.value = ''
  selectedProjects.value = []
  factCheck.value = null
  outputMode.value = 'document'
  generationWarning.value = ''
  docxAvailable.value = false
  pdfAvailable.value = false
  if (clearError) errorMessage.value = ''
}

const scorePercent = (score) => Math.max(0, Math.min(100, Math.round(Number(score || 0) * 100)))
const formatDate = (date) => date ? new Date(date).toLocaleDateString('zh-CN') : ''

onMounted(() => Promise.all([loadJobs(), loadHistory(), loadTemplates()]))
</script>

<style scoped>
.resume-view { max-width: 1120px; margin: 0 auto; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; }
.page-header h2 { margin: 0 0 6px; color: #303133; }.page-header p { margin: 0; color: #909399; font-size: 13px; }
.generate-card, .loading-card, .preview-panel, .side-card { background: #fff; padding: 20px; border-radius: 10px; box-shadow: 0 1px 8px rgba(0,0,0,.06); }
.generate-card { margin-bottom: 16px; }.generate-card :deep(.el-form-item:last-child) { margin-bottom: 0; }
.template-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; width: 100%; }
.template-option { display: grid; grid-template-columns: 14px 1fr; gap: 4px 8px; padding: 12px; border: 1px solid #dcdfe6; border-radius: 8px; background: #fff; text-align: left; cursor: pointer; }
.template-option.active { border-color: #409eff; box-shadow: 0 0 0 2px rgba(64,158,255,.12); }
.template-swatch { grid-row: 1 / span 2; width: 12px; height: 100%; min-height: 38px; border-radius: 4px; }
.template-option strong { color: #303133; }.template-option small { color: #909399; line-height: 1.4; }
.custom-template-upload { display: inline-flex; margin-top: 10px; color: #409eff; cursor: pointer; font-size: 13px; }
.custom-template-upload input { display: none; }
.form-hint { margin-left: 10px; color: #909399; font-size: 12px; }.result-alert { margin-bottom: 16px; }
.loading-card { text-align: center; padding: 50px; color: #606266; }.resume-layout { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 18px; }
.preview-panel { padding: 0; overflow: hidden; }.preview-header { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; border-bottom: 1px solid #ebeef5; }
.preview-header h3 { margin: 0 0 4px; }.verified { color: #67c23a; font-size: 12px; }.text-only { color: #e6a23c; font-size: 12px; }.preview-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.resume-preview { margin: 0; padding: 28px 36px; white-space: pre-wrap; overflow-wrap: anywhere; font: 13px/1.75 system-ui, sans-serif; color: #303133; }
.sidebar-panel { display: flex; flex-direction: column; gap: 14px; }.side-card h4, .history-only h3 { margin: 0 0 12px; }
.greeting-text { padding: 12px; background: #f5f7fa; border-radius: 6px; color: #606266; font-size: 13px; line-height: 1.65; }
.project-item { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; }.project-rank { display: grid; place-items: center; width: 26px; height: 26px; border-radius: 50%; background: #409eff; color: #fff; }
.project-info { min-width: 0; flex: 1; font-size: 13px; }.history-item { width: 100%; padding: 9px 0; border: 0; border-bottom: 1px solid #f2f3f5; background: transparent; text-align: left; cursor: pointer; color: #303133; }
.history-item:hover { color: #409eff; }.history-item span, .history-item small { display: block; }.history-item small { margin-top: 3px; color: #909399; }.history-only { margin-top: 16px; }
@media (max-width: 820px) { .resume-layout { grid-template-columns: 1fr; }.form-hint { display: block; margin: 8px 0 0; }.preview-header { align-items: flex-start; gap: 10px; } }
</style>
