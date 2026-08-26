<template>
  <div class="job-list-view">
    <div class="page-header">
      <h2>岗位推荐</h2>
      <el-tag type="success">共 {{ total }} 个岗位</el-tag>
    </div>

    <!-- Filter Bar -->
    <div class="filter-bar">
      <el-select v-model="category" placeholder="岗位大类" clearable style="width: 160px">
        <el-option label="研发工程" value="engineering" />
        <el-option label="算法" value="algorithm" />
        <el-option label="产品、数据与测试" value="product_data_testing" />
        <el-option label="安全" value="security" />
      </el-select>
      <el-select v-model="subCategory" placeholder="细分方向" clearable style="width: 150px">
        <el-option label="后端开发" value="backend" />
        <el-option label="前端开发" value="frontend" />
        <el-option label="全栈开发" value="fullstack" />
        <el-option label="人工智能基础设施" value="ai_infra" />
        <el-option label="运维开发" value="devops" />
        <el-option label="大模型算法" value="llm_algo" />
        <el-option label="智能体算法" value="agent_algo" />
        <el-option label="数据分析" value="data_analysis" />
        <el-option label="人工智能产品经理" value="ai_pm" />
      </el-select>
      <el-select v-model="location" placeholder="工作城市" clearable style="width: 130px">
        <el-option label="北京" value="beijing" />
        <el-option label="上海" value="shanghai" />
        <el-option label="杭州" value="hangzhou" />
        <el-option label="深圳" value="shenzhen" />
        <el-option label="广州" value="guangzhou" />
      </el-select>
      <el-input-number v-model="salaryMin" :min="0" :step="5000" placeholder="最低月薪" style="width: 150px" />
      <el-button type="primary" :icon="Search" @click="searchJobs">搜索</el-button>
      <el-button :icon="Refresh" @click="loadJobs">刷新</el-button>
    </div>

    <!-- Job Cards -->
    <div class="job-cards" v-loading="loading">
      <div class="job-card" v-for="job in jobs" :key="job.id">
        <div class="card-main">
          <div class="card-left">
            <div class="card-title">{{ job.job_title }}</div>
            <div class="card-company">
              <el-icon><OfficeBuilding /></el-icon>
              {{ job.company_name }}
            </div>
            <div class="card-tags">
              <el-tag size="small" v-if="job.sub_category">{{ job.sub_category }}</el-tag>
              <el-tag size="small" type="info" v-if="job.location">
                <el-icon><Location /></el-icon> {{ job.location }}
              </el-tag>
              <el-tag size="small" type="warning" v-if="job.salary_min">
                {{ formatSalary(job.salary_min) }}-{{ formatSalary(job.salary_max) }}
              </el-tag>
            </div>
          </div>
          <div class="card-right">
            <div class="match-score" v-if="job.match_score">
              <el-progress type="circle" :percentage="job.match_score" :width="60" :color="matchColor(job.match_score)" />
              <span class="match-label">匹配度</span>
            </div>
            <div class="card-actions">
              <el-button size="small" type="primary" @click="analyzeJob(job)">分析岗位</el-button>
              <el-button size="small" @click="generateResume(job)">生成简历</el-button>
            </div>
          </div>
        </div>
        <div class="card-requirements" v-if="job.requirements && job.requirements.length">
          <el-tag size="small" v-for="req in job.requirements.slice(0, 6)" :key="String(req)" class="req-tag" effect="plain">{{ requirementText(req) }}</el-tag>
        </div>
        <div class="match-reasons" v-if="job.match_reasons?.length">{{ job.match_reasons.join('；') }}</div>
      </div>
    </div>

    <!-- Pagination -->
    <div class="pagination-wrap" v-if="total > pageSize">
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="prev, pager, next"
        @current-change="loadJobs"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { recommendJobs } from '../api/jobs'
import { useUserStore } from '../stores/user'

const router = useRouter()
const userStore = useUserStore()
const category = ref('')
const subCategory = ref('')
const location = ref('')
const salaryMin = ref(null)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const jobs = ref([])
const loading = ref(false)

const loadJobs = async () => {
  loading.value = true
  try {
    const res = await recommendJobs(userStore.user.id, {
      page: page.value,
      page_size: pageSize.value,
      category: category.value || undefined,
      sub_category: subCategory.value || undefined,
      location: location.value || undefined,
      salary_min: salaryMin.value ?? undefined,
    })
    jobs.value = res.data?.items || []
    total.value = res.data?.total || 0
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '岗位加载失败')
  } finally {
    loading.value = false
  }
}

const searchJobs = () => { page.value = 1; loadJobs() }

const analyzeJob = (job) => {
  router.push({ name: 'JobAnalysis', params: { id: job.id } })
}

const generateResume = (job) => {
  router.push({ name: 'Resume', query: { job_id: job.id } })
}

const formatSalary = (val) => {
  if (!val) return '?'
  return (val / 1000).toFixed(0) + 'K'
}

const matchColor = (score) => {
  if (score >= 80) return '#67c23a'
  if (score >= 60) return '#409eff'
  return '#e6a23c'
}

const requirementText = (req) => typeof req === 'string' ? req : (req?.skill_name || req?.name || req?.text || '岗位要求')

onMounted(loadJobs)
</script>

<style scoped>
.job-list-view { max-width: 900px; margin: 0 auto; }
.page-header { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; }
.page-header h2 { font-size: 20px; color: #303133; }

.filter-bar {
  display: flex; gap: 10px; flex-wrap: wrap;
  padding: 16px; background: #fff; border-radius: 8px;
  margin-bottom: 16px; box-shadow: 0 1px 6px rgba(0,0,0,0.06);
}

.job-cards { display: flex; flex-direction: column; gap: 12px; }

.job-card {
  background: #fff; border-radius: 8px; padding: 16px 20px;
  box-shadow: 0 1px 6px rgba(0,0,0,0.06);
  transition: box-shadow 0.2s;
}
.job-card:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.1); }

.card-main { display: flex; justify-content: space-between; align-items: flex-start; }
.card-title { font-size: 16px; font-weight: 600; color: #303133; margin-bottom: 4px; }
.card-company { font-size: 13px; color: #909399; display: flex; align-items: center; gap: 4px; margin-bottom: 8px; }
.card-tags { display: flex; gap: 6px; flex-wrap: wrap; }

.card-right { display: flex; align-items: center; gap: 16px; }
.match-label { font-size: 11px; color: #909399; display: block; text-align: center; margin-top: 2px; }
.card-actions { display: flex; gap: 6px; }

.card-requirements { margin-top: 12px; display: flex; gap: 6px; flex-wrap: wrap; }
.req-tag { font-size: 12px; }
.match-reasons { margin-top: 10px; color: #606266; font-size: 12px; }

.pagination-wrap { margin-top: 20px; display: flex; justify-content: center; }
</style>
