<template>
  <div class="job-list-view">
    <div class="page-header">
      <div>
        <h2>岗位推荐</h2>
        <p>岗位来自数据库；只对有证据的方向、城市、薪资和技能评分，未知项不再计中性分。</p>
      </div>
      <div class="header-tags">
        <el-tag type="success">{{ total }} 个岗位</el-tag>
        <el-tag v-if="mode === 'recommend'" type="info">画像完整度 {{ profileCompleteness }}%</el-tag>
      </div>
    </div>

    <section class="filter-bar">
      <el-radio-group v-model="mode" @change="switchMode">
        <el-radio-button value="recommend">按画像推荐</el-radio-button>
        <el-radio-button value="all">全部岗位</el-radio-button>
      </el-radio-group>
      <el-input v-model="subCategory" placeholder="岗位方向" clearable style="width: 150px" />
      <el-input v-model="location" placeholder="工作城市" clearable style="width: 130px" />
      <el-input-number v-model="salaryMin" :min="0" :step="1000" placeholder="最低薪资" style="width: 150px" />
      <el-button type="primary" @click="searchJobs">筛选</el-button>
      <el-button @click="resetFilters">重置</el-button>
    </section>

    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" />

    <div v-loading="loading" class="job-cards">
      <el-empty v-if="!loading && !jobs.length" description="没有找到符合条件的岗位" />
      <article v-for="job in jobs" :key="job.id" class="job-card">
        <div class="card-main">
          <div class="card-content">
            <h3>{{ job.job_title }}</h3>
            <p class="company">{{ job.company_name }}</p>
            <div class="card-tags">
              <el-tag v-if="job.sub_category" size="small">{{ job.sub_category }}</el-tag>
              <el-tag v-if="job.location" size="small" type="info">{{ job.location }}</el-tag>
              <el-tag v-if="job.source_type === 'beijing_hr_open_data'" size="small" type="success">北京市人社公开数据</el-tag>
              <el-tag v-if="job.salary_min || job.salary_max" size="small" type="warning">
                {{ formatSalary(job.salary_min) }} - {{ formatSalary(job.salary_max) }}
              </el-tag>
            </div>
            <div v-if="job.posted_at || job.expires_at || job.source_url" class="source-meta">
              <span v-if="job.posted_at">发布：{{ formatDate(job.posted_at) }}</span>
              <span v-if="job.expires_at">截止：{{ formatDate(job.expires_at) }}</span>
              <a v-if="job.source_url" :href="job.source_url" target="_blank" rel="noopener noreferrer">查看官方来源</a>
            </div>
            <div v-if="job.requirements?.length" class="requirements">
              <span v-for="requirement in job.requirements.slice(0, 6)" :key="requirement">{{ requirement }}</span>
            </div>
          </div>

          <div class="card-side">
            <div v-if="job.match_score !== undefined && job.match_score !== null" class="match-score">
              <strong>{{ job.match_score }}%</strong>
              <span>画像匹配</span>
            </div>
            <div v-else-if="job.match_score === null" class="match-score pending-score">
              <strong>暂不评分</strong>
              <span>证据覆盖 {{ job.evidence_coverage || 0 }}%</span>
            </div>
            <el-tag v-if="job.hard_constraint_status === 'conflict'" type="danger" size="small">存在硬条件冲突</el-tag>
            <el-tag v-else-if="job.match_score !== undefined" type="info" size="small">证据覆盖 {{ job.evidence_coverage || 0 }}%</el-tag>
            <div class="actions">
              <el-button type="primary" size="small" @click="openAnalysis(job)">避雷分析</el-button>
              <el-button size="small" @click="openResume(job)">定向简历</el-button>
            </div>
          </div>
        </div>

        <div v-if="job.match_reasons?.length || job.match_concerns?.length" class="explanation">
          <div v-if="job.match_reasons?.length" class="reason">匹配：{{ job.match_reasons.join('；') }}</div>
          <div v-if="job.match_concerns?.length" class="concern">需确认：{{ job.match_concerns.join('；') }}</div>
        </div>
      </article>
    </div>

    <div v-if="total > pageSize" class="pagination-wrap">
      <el-pagination v-model:current-page="page" :page-size="pageSize" :total="total" layout="prev, pager, next" @current-change="loadJobs" />
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { listJobs, recommendJobs } from '../api/jobs'

const router = useRouter()
const mode = ref('recommend')
const subCategory = ref('')
const location = ref('')
const salaryMin = ref(null)
const page = ref(1)
const pageSize = 20
const total = ref(0)
const profileCompleteness = ref(0)
const jobs = ref([])
const loading = ref(false)
const errorMessage = ref('')

const hasFilters = () => Boolean(subCategory.value || location.value || salaryMin.value)

const loadJobs = async () => {
  loading.value = true
  errorMessage.value = ''
  try {
    let response
    if (mode.value === 'recommend' && !hasFilters()) {
      response = await recommendJobs({ page: page.value, page_size: pageSize })
      profileCompleteness.value = response.data.profile_completeness || 0
    } else {
      response = await listJobs({
        sub_category: subCategory.value || undefined,
        location: location.value || undefined,
        salary_min: salaryMin.value || undefined,
        page: page.value,
        page_size: pageSize,
      })
    }
    jobs.value = response.data.items || []
    total.value = response.data.total || 0
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || '岗位加载失败，请稍后重试'
    jobs.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

const switchMode = () => { page.value = 1; loadJobs() }
const searchJobs = () => { page.value = 1; loadJobs() }
const resetFilters = () => {
  subCategory.value = ''
  location.value = ''
  salaryMin.value = null
  page.value = 1
  loadJobs()
}

const openAnalysis = (job) => router.push({ name: 'JobAnalysis', params: { id: job.id } })
const openResume = (job) => router.push({ name: 'Resume', query: { jobId: job.id } })
const formatSalary = (value) => value ? `${Math.round(value / 1000)}K` : '面议'
const formatDate = (value) => value ? String(value).slice(0, 10) : '未知'

onMounted(loadJobs)
</script>

<style scoped>
.job-list-view { max-width: 960px; margin: 0 auto; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; }
.page-header h2 { margin: 0 0 6px; }.page-header p { margin: 0; color: #909399; font-size: 13px; }
.header-tags { display: flex; gap: 8px; }.filter-bar { display: flex; flex-wrap: wrap; gap: 10px; padding: 16px; background: #fff; border-radius: 10px; margin-bottom: 16px; box-shadow: 0 1px 8px rgba(0,0,0,.06); }
.job-cards { min-height: 180px; display: flex; flex-direction: column; gap: 12px; margin-top: 16px; }
.job-card { background: #fff; padding: 18px 20px; border-radius: 10px; box-shadow: 0 1px 8px rgba(0,0,0,.06); overflow: hidden; }
.card-main { display: flex; justify-content: space-between; gap: 20px; }.card-content { min-width: 0; flex: 1; }
.card-content h3 { margin: 0 0 6px; color: #303133; }.company { margin: 0 0 10px; color: #606266; }
.card-tags, .requirements { display: flex; flex-wrap: wrap; gap: 6px; min-width: 0; }.requirements { margin-top: 10px; max-width: 100%; overflow: hidden; }
.requirements span {
  max-width: 100%;
  padding: 3px 8px;
  background: #f5f7fa;
  border-radius: 4px;
  color: #606266;
  font-size: 12px;
  line-height: 1.45;
  white-space: normal;
  word-break: break-word;
  overflow-wrap: anywhere;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.source-meta { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 9px; color: #909399; font-size: 12px; }
.source-meta a { color: #409eff; text-decoration: none; }.source-meta a:hover { text-decoration: underline; }
.card-side { min-width: 145px; display: flex; flex-direction: column; align-items: flex-end; gap: 14px; }
.match-score { display: flex; flex-direction: column; align-items: flex-end; }.match-score strong { color: #409eff; font-size: 24px; }.match-score span { color: #909399; font-size: 12px; }
.pending-score strong { color: #909399; font-size: 17px; }
.actions { display: flex; gap: 6px; }.explanation { margin-top: 14px; padding-top: 12px; border-top: 1px solid #ebeef5; font-size: 12px; line-height: 1.7; word-break: break-word; overflow-wrap: anywhere; }
.reason { color: #529b2e; }.concern { color: #b88230; }.pagination-wrap { display: flex; justify-content: center; margin-top: 20px; }
@media (max-width: 700px) { .card-main { flex-direction: column; }.card-side { align-items: flex-start; }.match-score { align-items: flex-start; } }
</style>
