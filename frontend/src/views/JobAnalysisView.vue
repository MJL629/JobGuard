<template>
  <div class="analysis-view">
    <div class="page-header">
      <h2>岗位分析</h2>
      <el-tag v-if="!analyzing && !report" type="info">等待分析</el-tag>
      <el-tag v-else-if="analyzing" type="warning">正在分析</el-tag>
    </div>

    <div class="analysis-layout">
      <div class="main-panel">
        <!-- Input -->
        <div class="input-card" v-if="!report && !analyzing">
          <h3>粘贴岗位链接或岗位描述</h3>
          <el-input
            v-model="jobUrl"
            type="textarea"
            :rows="6"
            placeholder="请粘贴 BOSS 直聘、拉勾等平台的岗位链接，或粘贴完整岗位描述……"
          />
          <div style="margin-top: 12px; display: flex; gap: 8px;">
            <el-button type="primary" :icon="Search" @click="startAnalysis" :disabled="!jobUrl.trim()" :loading="analyzing">
              开始分析
            </el-button>
            <el-button @click="loadMockData">加载演示岗位</el-button>
          </div>
        </div>

        <!-- Progress -->
        <div v-if="analyzing" class="progress-card">
          <el-steps :active="currentStep" align-center>
            <el-step title="岗位解析" description="提取岗位信息" />
            <el-step title="企业背调" description="核查企业信息" />
            <el-step title="风险分析" description="评估求职风险" />
            <el-step title="分析完成" description="生成分析报告" />
          </el-steps>
          <div class="step-detail" v-if="stepMessage">{{ stepMessage }}</div>
        </div>

        <!-- Report -->
        <div v-if="report" class="report-container">
          <!-- Summary Card -->
          <div class="summary-card" :class="riskClass">
            <div class="summary-left">
              <div class="risk-badge">{{ riskLabel }}</div>
              <div class="company-name">{{ report.company_name }}</div>
              <div class="job-title">{{ report.job_title }}</div>
            </div>
            <div class="summary-right">
              <div class="stars">
                <span v-for="i in 5" :key="i" class="star" :class="{ filled: i <= report.recommendation_index }">★</span>
              </div>
              <div class="recommendation">{{ report.recommendation_text }}</div>
            </div>
          </div>

          <!-- Dimensions -->
          <div class="dimensions-grid">
            <div class="dim-card" v-for="dim in dimensionCards" :key="dim.key">
              <div class="dim-header">
                <span class="dim-icon">{{ dim.icon }}</span>
                <span class="dim-label">{{ dim.label }}</span>
                <el-rate :model-value="dim.score" disabled show-score text-color="#ff9900" />
              </div>
              <div class="dim-body">{{ dim.assessment }}</div>
            </div>
          </div>

          <!-- Red Flags & Positives -->
          <div class="two-col">
            <div class="flags-card red" v-if="report.red_flags && report.red_flags.length">
              <h4>风险信号</h4>
              <ul>
                <li v-for="(f, i) in report.red_flags" :key="i">{{ f }}</li>
              </ul>
            </div>
            <div class="flags-card green" v-if="report.positive_points && report.positive_points.length">
              <h4>积极因素</h4>
              <ul>
                <li v-for="(p, i) in report.positive_points" :key="i">{{ p }}</li>
              </ul>
            </div>
          </div>

          <!-- Advice -->
          <div class="advice-card" v-if="report.advice">
            <h4>求职建议</h4>
            <p>{{ report.advice }}</p>
          </div>

          <!-- Actions -->
          <div class="actions">
            <el-button type="primary" @click="generateResumeForJob">为该岗位生成简历</el-button>
            <el-button @click="resetAnalysis">分析其他岗位</el-button>
          </div>
        </div>
      </div>

      <aside class="history-panel">
        <h3>分析历史</h3>
        <div v-if="analysisHistory.length === 0" class="empty-hint">暂无历史分析</div>
        <div
          v-for="item in analysisHistory"
          :key="item.id"
          class="history-item"
          @click="loadAnalysisRecord(item.id)"
        >
          <div class="history-title">{{ item.job_title }}</div>
          <div class="history-meta">{{ item.company_name }}</div>
          <div class="history-footer">
            <span>{{ riskText(item.risk_level) }}｜推荐 {{ item.recommendation_index || '-' }} 星</span>
            <span>{{ formatDate(item.created_at) }}</span>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { analyzeJob, getAnalysisHistory, getAnalysisRecord, getJobDetail } from '../api/jobs'
import { useUserStore } from '../stores/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const jobUrl = ref('')
const analyzing = ref(false)
const currentStep = ref(0)
const stepMessage = ref('')
const report = ref(null)
const selectedJobId = ref(null)
const analysisHistory = ref([])

const riskClass = computed(() => {
  const map = { low: 'risk-low', medium: 'risk-medium', high: 'risk-high', critical: 'risk-critical' }
  return map[report.value?.risk_level] || ''
})

const riskLabel = computed(() => {
  const map = { low: '低风险', medium: '中等风险', high: '高风险', critical: '严重风险' }
  return map[report.value?.risk_level] || '风险未知'
})

const dimensionCards = computed(() => {
  if (!report.value?.dimensions) return []
  const dims = report.value.dimensions
  const cards = []
  const defs = [
    { key: 'social_insurance', label: '社保情况', icon: '🏢' },
    { key: 'labor_disputes', label: '劳动争议', icon: '⚖️' },
    { key: 'online_reputation', label: '网络口碑', icon: '💬' },
    { key: 'jd_analysis', label: '岗位描述分析', icon: '📋' },
    { key: 'match_with_user', label: '用户匹配', icon: '🎯' },
  ]
  for (const d of defs) {
    if (dims[d.key]) {
      cards.push({ ...d, assessment: dims[d.key].assessment, score: dims[d.key].score || 3 })
    }
  }
  return cards
})

const startAnalysis = async () => {
  analyzing.value = true
  report.value = null
  currentStep.value = 0
  stepMessage.value = '正在解析岗位并生成背调报告……'
  try {
    const res = await analyzeJob(userStore.user.id, jobUrl.value, 'text')
    if (res.code !== 0) throw new Error(res.message || '岗位分析失败')
    const data = res.data
    report.value = normalizeReport(data)
    selectedJobId.value = data.job_id || selectedJobId.value
    await loadAnalysisHistory()
    currentStep.value = 3
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error.message || '岗位分析失败')
  } finally {
    analyzing.value = false
  }
}

const generateResumeForJob = () => {
  router.push({ name: 'Resume', query: selectedJobId.value ? { job_id: selectedJobId.value } : {} })
}

const resetAnalysis = () => {
  report.value = null
  jobUrl.value = ''
  selectedJobId.value = null
}

const loadMockData = () => {
  jobUrl.value = `Java 后端开发工程师｜远景科技
薪资：15K-25K/月
地点：北京市海淀区
要求：熟悉 Java、Spring Boot、MySQL，具备 1-3 年开发经验
福利：五险一金、年终奖、弹性工作
岗位描述：负责微服务架构设计与开发，能够处理高并发场景，要求抗压能力强并能快速适应业务变化。`
}

const formatJobText = (job) => {
  const requirements = (job.requirements || []).map(req => {
    if (typeof req === 'string') return req
    return req.skill_name || req.name || req.text || JSON.stringify(req)
  }).join('\n')
  return `${job.job_title}｜${job.company_name}
地点：${job.location || '未填写'}
薪资：${job.salary_min || ''}-${job.salary_max || ''}/月
方向：${job.job_category || ''} ${job.sub_category || ''}
要求：
${requirements || job.jd_text || ''}`
}

const normalizeReport = (data) => {
  const jobInfo = data.job_info || {}
  const raw = data.report || data
  return {
    ...raw,
    company_name: raw.company_name || jobInfo.company_name || '',
    job_title: raw.job_title || jobInfo.job_title || '',
    recommendation_text: raw.recommendation_text || raw.recommendation || '建议结合面试进一步确认',
  }
}

const loadAnalysisHistory = async () => {
  const res = await getAnalysisHistory(userStore.user.id)
  analysisHistory.value = res.data?.items || []
}

const loadAnalysisRecord = async (id) => {
  try {
    const res = await getAnalysisRecord(id, userStore.user.id)
    if (res.code !== 0) throw new Error(res.message || '读取失败')
    const data = res.data
    selectedJobId.value = data.job_id
    report.value = {
      ...(data.analysis || {}),
      company_name: data.company_name,
      job_title: data.job_title,
      risk_level: data.risk_level,
      recommendation_index: data.recommendation_index,
      match_score: data.match_score,
    }
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error.message || '历史分析读取失败')
  }
}

const formatDate = (d) => {
  if (!d) return ''
  return new Date(d).toLocaleDateString()
}

const riskText = (risk) => {
  const map = { low: '低风险', medium: '中等风险', high: '高风险', critical: '严重风险' }
  return map[risk] || '风险未知'
}

onMounted(async () => {
  await loadAnalysisHistory()
  const id = Number(route.params.id || route.query.job_id)
  if (!id) return
  selectedJobId.value = id
  try {
    const res = await getJobDetail(id)
    if (res.code !== 0) throw new Error(res.message || '岗位读取失败')
    jobUrl.value = formatJobText(res.data)
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error.message || '岗位信息读取失败')
  }
})
</script>

<style scoped>
.analysis-view { max-width: 1180px; margin: 0 auto; }
.page-header { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; }
.page-header h2 { font-size: 20px; color: #303133; }

.analysis-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 18px;
  align-items: start;
}

.main-panel { min-width: 0; }

.input-card {
  background: #fff; padding: 24px; border-radius: 8px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.06);
}
.input-card h3 { margin-bottom: 12px; font-size: 16px; }

.progress-card {
  background: #fff; padding: 32px 24px; border-radius: 8px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.06);
}
.step-detail { text-align: center; margin-top: 20px; color: #909399; font-size: 14px; }

/* Summary */
.summary-card {
  display: flex; justify-content: space-between; align-items: center;
  padding: 24px; border-radius: 8px; margin-bottom: 20px;
}
.risk-low { background: #f0f9eb; border-left: 4px solid #67c23a; }
.risk-medium { background: #fdf6ec; border-left: 4px solid #e6a23c; }
.risk-high { background: #fef0f0; border-left: 4px solid #f56c6c; }
.risk-critical { background: #fde2e2; border-left: 4px solid #f56c6c; }

.risk-badge { font-size: 12px; font-weight: 700; letter-spacing: 1px; margin-bottom: 4px; }
.risk-low .risk-badge { color: #67c23a; }
.risk-medium .risk-badge { color: #e6a23c; }
.risk-high .risk-badge, .risk-critical .risk-badge { color: #f56c6c; }

.company-name { font-size: 18px; font-weight: 600; color: #303133; }
.job-title { font-size: 14px; color: #606266; margin-top: 4px; }

.stars { text-align: right; }
.star { font-size: 28px; color: #e4e7ed; }
.star.filled { color: #f7ba2a; }
.recommendation { font-size: 14px; color: #606266; text-align: right; margin-top: 4px; }

/* Dimensions */
.dimensions-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
  margin-bottom: 20px;
}
.dim-card {
  background: #fff; padding: 16px; border-radius: 8px;
  box-shadow: 0 1px 6px rgba(0,0,0,0.06);
}
.dim-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.dim-icon { font-size: 18px; }
.dim-label { font-weight: 600; font-size: 14px; color: #303133; flex: 1; }
.dim-body { font-size: 13px; color: #606266; line-height: 1.5; }

/* Two column */
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 20px; }
.flags-card {
  background: #fff; padding: 16px; border-radius: 8px;
  box-shadow: 0 1px 6px rgba(0,0,0,0.06);
}
.flags-card.red { border-top: 3px solid #f56c6c; }
.flags-card.green { border-top: 3px solid #67c23a; }
.flags-card h4 { margin-bottom: 8px; font-size: 15px; }
.flags-card ul { padding-left: 20px; }
.flags-card li { font-size: 13px; color: #606266; line-height: 1.8; }

.advice-card {
  background: #ecf5ff; padding: 16px; border-radius: 8px;
  margin-bottom: 20px;
}
.advice-card h4 { margin-bottom: 8px; font-size: 15px; }
.advice-card p { font-size: 14px; color: #606266; line-height: 1.6; }

.actions { display: flex; gap: 12px; }

.history-panel {
  background: #fff;
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 1px 6px rgba(0,0,0,0.06);
  position: sticky;
  top: 0;
}

.history-panel h3 {
  font-size: 15px;
  margin-bottom: 12px;
  color: #303133;
}

.history-item {
  padding: 10px 0;
  border-bottom: 1px solid #f2f3f5;
  cursor: pointer;
}

.history-item:hover .history-title { color: #409eff; }
.history-title { font-size: 13px; font-weight: 600; color: #303133; line-height: 1.4; }
.history-meta { font-size: 12px; color: #909399; margin-top: 4px; }
.history-footer { display: flex; justify-content: space-between; margin-top: 6px; font-size: 12px; color: #606266; }
.empty-hint { font-size: 13px; color: #c0c4cc; text-align: center; padding: 12px; }

@media (max-width: 960px) {
  .analysis-layout { grid-template-columns: 1fr; }
  .history-panel { position: static; }
}
</style>
