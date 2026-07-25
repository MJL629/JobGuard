<template>
  <div class="job-list-view">
    <div class="page-header">
      <h2>Job Recommendations</h2>
      <el-tag type="success">12 jobs available</el-tag>
    </div>

    <!-- Filter Bar -->
    <div class="filter-bar">
      <el-select v-model="category" placeholder="Category" clearable style="width: 160px">
        <el-option label="Engineering" value="engineering" />
        <el-option label="Algorithm" value="algorithm" />
        <el-option label="Product/Data/Test" value="product_data_testing" />
        <el-option label="Security" value="security" />
      </el-select>
      <el-select v-model="subCategory" placeholder="Sub-category" clearable style="width: 150px">
        <el-option label="Backend" value="backend" />
        <el-option label="Frontend" value="frontend" />
        <el-option label="Full Stack" value="fullstack" />
        <el-option label="AI Infra" value="ai_infra" />
        <el-option label="DevOps" value="devops" />
        <el-option label="LLM Algorithm" value="llm_algo" />
        <el-option label="Agent Algorithm" value="agent_algo" />
        <el-option label="Data Analysis" value="data_analysis" />
        <el-option label="AI Product Manager" value="ai_pm" />
      </el-select>
      <el-select v-model="location" placeholder="Location" clearable style="width: 130px">
        <el-option label="Beijing" value="beijing" />
        <el-option label="Shanghai" value="shanghai" />
        <el-option label="Hangzhou" value="hangzhou" />
        <el-option label="Shenzhen" value="shenzhen" />
        <el-option label="Guangzhou" value="guangzhou" />
      </el-select>
      <el-input-number v-model="salaryMin" :min="0" :step="5000" placeholder="Min salary" style="width: 150px" />
      <el-button type="primary" :icon="Search">Search</el-button>
      <el-button :icon="Refresh" @click="loadJobs">Refresh</el-button>
    </div>

    <!-- Job Cards -->
    <div class="job-cards">
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
              <span class="match-label">Match</span>
            </div>
            <div class="card-actions">
              <el-button size="small" type="primary" @click="analyzeJob(job)">Analyze</el-button>
              <el-button size="small" @click="generateResume(job)">Resume</el-button>
            </div>
          </div>
        </div>
        <div class="card-requirements" v-if="job.requirements && job.requirements.length">
          <el-tag size="small" v-for="req in job.requirements.slice(0, 6)" :key="req" class="req-tag" effect="plain">{{ req }}</el-tag>
        </div>
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

const router = useRouter()
const category = ref('')
const subCategory = ref('')
const location = ref('')
const salaryMin = ref(null)
const page = ref(1)
const pageSize = ref(20)
const total = ref(12)

const jobs = ref([
  {
    id: 1, company_name: 'TechCorp Ltd.', job_title: 'Java Backend Developer',
    sub_category: 'Backend', location: 'Beijing', salary_min: 15000, salary_max: 25000,
    match_score: 88,
    requirements: ['Java', 'Spring Boot', 'MySQL', 'Redis', 'Microservices', 'Docker'],
  },
  {
    id: 2, company_name: 'WebCo Tech', job_title: 'Frontend Developer (React)',
    sub_category: 'Frontend', location: 'Hangzhou', salary_min: 12000, salary_max: 20000,
    match_score: 72,
    requirements: ['React', 'TypeScript', 'CSS', 'Webpack', 'Node.js'],
  },
  {
    id: 3, company_name: 'AI Labs', job_title: 'LLM Application Engineer',
    sub_category: 'LLM Algorithm', location: 'Beijing', salary_min: 25000, salary_max: 40000,
    match_score: 65,
    requirements: ['Python', 'PyTorch', 'LangChain', 'RAG', 'Prompt Engineering'],
  },
  {
    id: 4, company_name: 'DataFlow Inc.', job_title: 'Backend Engineer (Go)',
    sub_category: 'Backend', location: 'Shanghai', salary_min: 18000, salary_max: 30000,
    match_score: 81,
    requirements: ['Go', 'gRPC', 'Kubernetes', 'PostgreSQL', 'Kafka'],
  },
  {
    id: 5, company_name: 'CloudBase', job_title: 'DevOps Engineer',
    sub_category: 'DevOps', location: 'Shenzhen', salary_min: 20000, salary_max: 35000,
    match_score: 58,
    requirements: ['Docker', 'Kubernetes', 'CI/CD', 'Terraform', 'AWS'],
  },
  {
    id: 6, company_name: 'SafeNet', job_title: 'Security Engineer',
    sub_category: 'Cybersecurity', location: 'Beijing', salary_min: 22000, salary_max: 35000,
    match_score: 45,
    requirements: ['Network Security', 'Penetration Testing', 'WAF', 'SIEM'],
  },
])

const loadJobs = () => { /* API call placeholder */ }

const analyzeJob = (job) => {
  router.push({ name: 'JobAnalysis', query: { job: job.job_title, company: job.company_name } })
}

const generateResume = (job) => {
  router.push({ name: 'Resume', query: { job: job.job_title } })
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

.pagination-wrap { margin-top: 20px; display: flex; justify-content: center; }
</style>
