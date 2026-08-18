<template>
  <div class="analysis-view">
    <div class="page-header">
      <div>
        <h2>岗位避雷分析</h2>
        <p>支持粘贴 JD、公开岗位链接或上传岗位截图；企业外部事实会单独标记核验状态。</p>
      </div>
      <el-tag :type="report ? riskTagType : 'info'">{{ report ? riskLabel : '等待分析' }}</el-tag>
    </div>

    <el-alert
      title="可信度说明"
      description="系统会实时查询可公开访问的来源并保留链接；遇到登录、验证码或反爬限制时会明确标成受访问控制。不会虚构社保人数、仲裁数量或公司口碑。"
      type="warning"
      show-icon
      :closable="false"
      style="margin-bottom: 16px"
    />

    <section class="input-card">
      <h3>输入岗位描述或公开链接</h3>
      <el-input
        v-model="jobText"
        type="textarea"
        :rows="8"
        placeholder="粘贴完整 JD，或输入一个 http/https 公开岗位链接..."
        :disabled="analyzing"
      />
      <div class="input-actions">
        <el-button type="primary" :loading="analyzing" :disabled="!jobText.trim()" @click="startAnalysis">
          开始真实分析
        </el-button>
        <el-upload
          action="#"
          :auto-upload="false"
          :show-file-list="false"
          accept=".png,.jpg,.jpeg,.webp"
          :on-change="analyzeScreenshot"
          :disabled="analyzing"
        >
          <el-button :disabled="analyzing">上传岗位截图</el-button>
        </el-upload>
        <el-button :disabled="analyzing" @click="fillExample">填入示例 JD</el-button>
        <el-button v-if="report" :disabled="analyzing" @click="resetAnalysis">清空结果</el-button>
      </div>
    </section>

    <el-alert
      v-if="errorMessage"
      :title="errorMessage"
      type="error"
      show-icon
      :closable="false"
      style="margin-top: 16px"
    />

    <section v-if="analyzing" class="loading-card">
      <el-icon class="is-loading" :size="30"><Loading /></el-icon>
      <p>正在读取来源、解析岗位原文并识别风险信号，请稍候...</p>
    </section>

    <div v-if="report && !analyzing" class="report-container">
      <section class="summary-card" :class="`risk-${report.risk_level}`">
        <div>
          <div class="risk-title">{{ riskLabel }}</div>
          <h3>{{ report.company_name || jobInfo.company_name || '未知企业' }}</h3>
          <p>{{ report.job_title || jobInfo.job_title || '未知岗位' }}</p>
        </div>
        <div class="recommendation">
          <strong>建议指数 {{ report.recommendation_index || '-' }}/5</strong>
          <span>{{ report.recommendation_text }}</span>
        </div>
      </section>

      <el-alert
        v-if="['jd_only', 'jd_source_fetched'].includes(report.verification_status)"
        title="本报告仅核验了 JD 原文"
        description="JD 之外的每个维度会分别显示实时查询结果或访问限制，不应把无结果理解为企业无风险。"
        type="info"
        show-icon
        :closable="false"
        style="margin-bottom: 16px"
      />

      <el-alert
        v-else-if="report.verification_status === 'live_sources_queried'"
        title="已执行实时外部来源查询"
        description="页面会逐项区分有结果、无结果和受访问控制；查询无结果不等于企业无风险。"
        type="success"
        show-icon
        :closable="false"
        style="margin-bottom: 16px"
      />

      <el-alert
        v-else-if="report.verification_status === 'official_job_evidence'"
        title="岗位来源已核验，企业风险事实尚未核验"
        description="该岗位可追溯到政府开放数据；这不代表企业的社保、劳动争议、工商风险或口碑已经通过核验。"
        type="warning"
        show-icon
        :closable="false"
        style="margin-bottom: 16px"
      />

      <el-alert
        v-else-if="report.verification_status === 'official_company_evidence'"
        title="报告已读取企业官方证据"
        description="仅带“官方来源”标记的维度属于已核验事实，其他维度仍保持未知。"
        type="success"
        show-icon
        :closable="false"
        style="margin-bottom: 16px"
      />

      <section class="summary-text">
        <h3>分析摘要</h3>
        <p>{{ report.summary }}</p>
      </section>

      <div class="dimensions-grid">
        <section v-for="dimension in dimensions" :key="dimension.key" class="dimension-card">
          <div class="dimension-header">
            <span>{{ dimension.icon }} {{ dimension.label }}</span>
            <el-tag :type="dimension.tagType" size="small">
              {{ dimension.verificationLabel }}
            </el-tag>
          </div>
          <p>{{ dimension.assessment || '暂无结果' }}</p>
          <div v-if="dimension.evidence?.length" class="evidence-list">
            <span>原文信号：</span>
            <el-tag v-for="item in dimension.evidence" :key="item" type="warning" size="small">{{ item }}</el-tag>
          </div>
        </section>
      </div>

      <div class="two-col">
        <section class="list-card danger">
          <h3>需要核实</h3>
          <ul v-if="report.red_flags?.length">
            <li v-for="flag in report.red_flags" :key="flag">{{ flag }}</li>
          </ul>
          <p v-else class="empty">JD 原文中暂未发现明确红旗，但不代表企业已经通过背调。</p>
        </section>
        <section class="list-card advice">
          <h3>面试建议</h3>
          <p>{{ report.advice }}</p>
        </section>
      </div>

      <section class="sources-card">
        <h3>可核验来源</h3>
        <div v-if="report.sources?.length">
          <a v-for="source in report.sources" :key="source.url" :href="source.url" target="_blank" rel="noopener noreferrer">
            {{ source.title || source.url }} · {{ sourceStatusLabel(source.status) }}（{{ source.supports || '仅支持页面内容' }}）
          </a>
        </div>
        <p v-else class="empty">暂无已读取的外部来源。本报告不会用模型记忆冒充联网搜索。</p>
      </section>

      <section v-if="report.tool_trace?.length" class="sources-card">
        <h3>Agent 工具调用记录</h3>
        <div v-for="trace in report.tool_trace" :key="trace.tool_name" class="verification-task">
          <strong>{{ trace.tool_name }}</strong>
          <p>
            状态：{{ toolStatusLabel(trace.status) }}；核验级别：{{ trace.verification_status }}；
            返回来源 {{ trace.source_count || 0 }} 条；实时适配器 {{ trace.live_queries?.length || 0 }} 个。
          </p>
        </div>
      </section>

      <section v-if="report.verification_tasks?.length" class="sources-card">
        <h3>受访问控制的免费官方核验入口</h3>
        <div v-for="task in report.verification_tasks" :key="task.title" class="verification-task">
          <a :href="task.url" target="_blank" rel="noopener noreferrer">{{ task.dimension }} · {{ task.title }}</a>
          <p>搜索：{{ task.search_term }}。{{ task.instructions }}</p>
        </div>
      </section>

      <div class="report-actions">
        <el-button v-if="analysisResult.job_id" type="primary" @click="generateResumeForJob">基于此岗位生成简历</el-button>
        <el-button @click="resetAnalysis">分析另一个岗位</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Loading } from '@element-plus/icons-vue'
import { analyzeJob, analyzeJobImage, getJobDetail } from '../api/jobs'

const route = useRoute()
const router = useRouter()
const jobText = ref('')
const analyzing = ref(false)
const errorMessage = ref('')
const analysisResult = ref(null)
const sourceJobId = ref(null)

const report = computed(() => analysisResult.value?.report || null)
const jobInfo = computed(() => analysisResult.value?.job_info || {})

const riskLabel = computed(() => ({
  low: '暂未发现明显红旗', medium: '存在需核实信号', high: '高风险信号', critical: '严重风险',
}[report.value?.risk_level] || '未知风险'))

const riskTagType = computed(() => ({ low: 'success', medium: 'warning', high: 'danger', critical: 'danger' }[report.value?.risk_level] || 'info'))

const toolStatusLabel = (status) => ({
  success: '调用成功',
  no_evidence: '调用成功但暂无证据',
  failed: '调用失败',
  skipped_no_database: '未连接证据库',
}[status] || status || '未知')

const sourceStatusLabel = (status) => ({
  official: '官方来源',
  fetched: '已读取',
  reported: '公开来源',
  success_with_results: '实时查询有结果',
  success_no_results: '实时查询无结果',
  temporarily_unavailable: '本次查询不可用',
}[status] || '已读取')

const verificationMeta = (key, value = {}) => {
  if (key === 'jd_analysis') return { label: '基于 JD 原文', type: 'success' }
  if (value.verified) return { label: '官方来源', type: 'success' }
  return ({
    live_results: { label: '已联网查询', type: 'warning' },
    success_no_results: { label: '已查询无结果', type: 'info' },
    queried_no_results: { label: '已查询无结果', type: 'info' },
    access_controlled: { label: '受访问控制', type: 'warning' },
    not_publicly_available: { label: '无公开统一接口', type: 'info' },
    temporarily_unavailable: { label: '本次查询失败', type: 'danger' },
  }[value.status] || { label: '未核验', type: 'info' })
}

const dimensions = computed(() => {
  const raw = report.value?.dimensions || {}
  const definitions = [
    ['jd_analysis', 'JD 原文风险', '📋'],
    ['social_insurance', '社保信息', '🏢'],
    ['labor_disputes', '劳动争议', '⚖️'],
    ['business_risk', '工商风险', '🔎'],
    ['online_reputation', '网络口碑', '💬'],
    ['official_jobs', '官方招聘记录', '🏛️'],
    ['public_transactions', '官方公共交易记录', '📑'],
  ]
  return definitions.map(([key, label, icon]) => {
    const meta = verificationMeta(key, raw[key])
    return {
      key, label, icon,
      verified: Boolean(raw[key]?.verified),
      verificationLabel: meta.label,
      tagType: meta.type,
      assessment: raw[key]?.assessment,
      evidence: raw[key]?.evidence_phrases || [],
    }
  })
})

const startAnalysis = async () => {
  if (!jobText.value.trim()) return
  analyzing.value = true
  errorMessage.value = ''
  analysisResult.value = null
  try {
    const input = jobText.value.trim()
    const messageType = /^https?:\/\/\S+$/i.test(input) ? 'url' : 'text'
    const response = await analyzeJob(input, messageType, sourceJobId.value)
    if (response.code !== 0) throw new Error(response.message || '岗位分析失败')
    analysisResult.value = response.data
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || error.message || '岗位分析失败，请稍后重试'
  } finally {
    analyzing.value = false
  }
}

const analyzeScreenshot = async (uploadFile) => {
  const file = uploadFile.raw
  if (!file) return
  analyzing.value = true
  errorMessage.value = ''
  analysisResult.value = null
  try {
    const response = await analyzeJobImage(file)
    if (response.code !== 0) throw new Error(response.message || '岗位截图分析失败')
    analysisResult.value = response.data
  } catch (error) {
    const detail = error.response?.data?.detail
    errorMessage.value = detail?.message || detail || error.message || '岗位截图识别失败，请上传清晰图片'
  } finally {
    analyzing.value = false
  }
}

const fillExample = () => {
  jobText.value = `公司：示例科技有限公司
岗位：Java 后端开发工程师
薪资：15K-40K/月
地点：广州
岗位职责：负责微服务系统设计与开发，处理高并发业务。
任职要求：熟悉 Java、Spring Boot、MySQL；抗压能力强，拥抱变化，以结果为导向；可以接受高强度工作。
工作制度：大小周，项目紧急时需随时响应。
福利：五险一金、年终奖。`
}

const loadSourceJob = async () => {
  const jobId = Number(route.params.id)
  if (!Number.isInteger(jobId) || jobId <= 0) return
  try {
    const response = await getJobDetail(jobId)
    const job = response.data
    sourceJobId.value = job.id
    jobText.value = [
      `公司：${job.company_name || '未提供'}`,
      `岗位：${job.job_title || '未提供'}`,
      `薪资：${job.salary_min || '未提供'}-${job.salary_max || '未提供'}`,
      `地点：${job.location || '未提供'}`,
      job.requirements?.length ? `任职要求：${job.requirements.join('；')}` : '',
      job.jd_text || '',
    ].filter(Boolean).join('\n')
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || '数据库岗位载入失败，请返回岗位列表后重试'
  }
}

const resetAnalysis = () => {
  analysisResult.value = null
  errorMessage.value = ''
  jobText.value = ''
}

const generateResumeForJob = () => {
  router.push({ name: 'Resume', query: { jobId: analysisResult.value.job_id || sourceJobId.value } })
}

onMounted(loadSourceJob)
</script>

<style scoped>
.analysis-view { max-width: 960px; margin: 0 auto; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; }
.page-header h2 { margin: 0 0 6px; color: #303133; }
.page-header p { margin: 0; color: #909399; font-size: 13px; }
.input-card, .loading-card, .summary-text, .dimension-card, .list-card, .sources-card { background: #fff; padding: 20px; border-radius: 10px; box-shadow: 0 1px 8px rgba(0,0,0,.06); }
.input-card h3, .summary-text h3, .list-card h3, .sources-card h3 { margin: 0 0 12px; }
.input-actions { display: flex; gap: 8px; margin-top: 12px; }
.loading-card { margin-top: 16px; text-align: center; color: #606266; }
.report-container { margin-top: 18px; }
.summary-card { display: flex; justify-content: space-between; padding: 22px; border-radius: 10px; margin-bottom: 16px; }
.summary-card h3 { margin: 8px 0 4px; }.summary-card p { margin: 0; }
.risk-low { background: #f0f9eb; }.risk-medium { background: #fdf6ec; }.risk-high, .risk-critical { background: #fef0f0; }
.risk-title { font-weight: 700; }.recommendation { display: flex; flex-direction: column; text-align: right; gap: 6px; }
.summary-text { margin-bottom: 16px; }.summary-text p, .dimension-card p, .list-card p { color: #606266; line-height: 1.7; }
.dimensions-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px; }
.dimension-header { display: flex; justify-content: space-between; align-items: center; font-weight: 600; }
.evidence-list { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; font-size: 12px; color: #909399; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px; }
.danger { border-top: 3px solid #f56c6c; }.advice { border-top: 3px solid #409eff; }
.list-card li { margin-bottom: 8px; color: #606266; }.empty { color: #909399; font-size: 13px; }
.sources-card a { display: block; margin-bottom: 6px; }.report-actions { display: flex; gap: 8px; margin-top: 16px; }
@media (max-width: 760px) { .dimensions-grid, .two-col { grid-template-columns: 1fr; } }
</style>
