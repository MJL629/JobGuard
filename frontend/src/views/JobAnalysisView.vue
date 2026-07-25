<template>
  <div class="analysis-view">
    <div class="page-header">
      <h2>Job Analysis</h2>
      <el-tag v-if="!analyzing && !report" type="info">Ready</el-tag>
      <el-tag v-else-if="analyzing" type="warning">Analyzing...</el-tag>
    </div>

    <!-- Input -->
    <div class="input-card" v-if="!report && !analyzing">
      <h3>Paste a Job Link or Description</h3>
      <el-input
        v-model="jobUrl"
        type="textarea"
        :rows="4"
        placeholder="Paste a BOSS Zhipin / Lagou job link, or paste the full job description..."
      />
      <div style="margin-top: 12px; display: flex; gap: 8px;">
        <el-button type="primary" :icon="Search" @click="startAnalysis" :disabled="!jobUrl.trim()" :loading="analyzing">
          Analyze Job
        </el-button>
        <el-button @click="loadMockData">Load Demo</el-button>
      </div>
    </div>

    <!-- Progress -->
    <div v-if="analyzing" class="progress-card">
      <el-steps :active="currentStep" align-center>
        <el-step title="Parsing" description="Extracting job info" />
        <el-step title="Background Check" description="Checking company" />
        <el-step title="Risk Analysis" description="Evaluating risks" />
        <el-step title="Complete" description="Report ready" />
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
          <h4>⚠️ Red Flags</h4>
          <ul>
            <li v-for="(f, i) in report.red_flags" :key="i">{{ f }}</li>
          </ul>
        </div>
        <div class="flags-card green" v-if="report.positive_points && report.positive_points.length">
          <h4>✅ Positive Points</h4>
          <ul>
            <li v-for="(p, i) in report.positive_points" :key="i">{{ p }}</li>
          </ul>
        </div>
      </div>

      <!-- Advice -->
      <div class="advice-card" v-if="report.advice">
        <h4>💡 Advice</h4>
        <p>{{ report.advice }}</p>
      </div>

      <!-- Actions -->
      <div class="actions">
        <el-button type="primary" @click="generateResumeForJob">Generate Resume for This Job</el-button>
        <el-button @click="resetAnalysis">Analyze Another Job</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const jobUrl = ref('')
const analyzing = ref(false)
const currentStep = ref(0)
const stepMessage = ref('')
const report = ref(null)

const riskClass = computed(() => {
  const map = { low: 'risk-low', medium: 'risk-medium', high: 'risk-high', critical: 'risk-critical' }
  return map[report.value?.risk_level] || ''
})

const riskLabel = computed(() => {
  const map = { low: 'LOW RISK', medium: 'MEDIUM RISK', high: 'HIGH RISK', critical: 'CRITICAL' }
  return map[report.value?.risk_level] || 'UNKNOWN'
})

const dimensionCards = computed(() => {
  if (!report.value?.dimensions) return []
  const dims = report.value.dimensions
  const cards = []
  const defs = [
    { key: 'social_insurance', label: 'Social Insurance', icon: '🏢' },
    { key: 'labor_disputes', label: 'Labor Disputes', icon: '⚖️' },
    { key: 'online_reputation', label: 'Reputation', icon: '💬' },
    { key: 'jd_analysis', label: 'JD Analysis', icon: '📋' },
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

  // Simulate analysis progress
  const steps = [
    { step: 0, msg: 'Extracting job information...', delay: 800 },
    { step: 1, msg: 'Checking social insurance and business records...', delay: 1200 },
    { step: 1, msg: 'Searching labor dispute records...', delay: 1000 },
    { step: 2, msg: 'Analyzing online reputation...', delay: 1000 },
    { step: 2, msg: 'Analyzing JD for red flags...', delay: 800 },
    { step: 3, msg: 'Generating final report...', delay: 600 },
  ]

  for (const s of steps) {
    currentStep.value = s.step
    stepMessage.value = s.msg
    await new Promise(r => setTimeout(r, s.delay))
  }

  // Mock report data
  report.value = {
    company_name: 'TechCorp Ltd.',
    job_title: 'Java Backend Developer',
    risk_level: 'medium',
    recommendation_index: 3,
    recommendation_text: 'Consider Carefully',
    summary: 'Moderate risk. The company has a few labor disputes and mixed online reviews. The JD shows some overtime signals.',
    red_flags: ['2 labor disputes in 12 months', 'JD contains overtime hints ("high pressure tolerance")'],
    positive_points: ['Competitive salary range', 'Good location in tech hub'],
    advice: 'If you decide to apply, ask about work-life balance during the interview. Verify the actual working hours with current employees if possible.',
    dimensions: {
      social_insurance: { assessment: '45 participants, declining trend in 6 months', score: 2 },
      labor_disputes: { assessment: '2 cases in 12 months (unpaid wages)', score: 2 },
      online_reputation: { assessment: 'Mixed reviews, some complaints about overtime', score: 3 },
      jd_analysis: { assessment: 'Contains overtime signals, salary range seems reasonable', score: 3 },
    },
  }

  analyzing.value = false
}

const generateResumeForJob = () => {
  // Navigate to resume page with job info
}

const resetAnalysis = () => {
  report.value = null
  jobUrl.value = ''
}

const loadMockData = () => {
  jobUrl.value = `Java Backend Developer - TechCorp Ltd.
Salary: 15K-25K/month
Location: Beijing, Haidian
Requirements: Java, Spring Boot, MySQL, 1-3 years experience
Benefits: Five insurances, year-end bonus, flexible hours
JD: Responsible for microservice architecture design and development. Need to handle high concurrency scenarios. Looking for someone who can work under pressure and embrace changes.`
}
</script>

<style scoped>
.analysis-view { max-width: 900px; margin: 0 auto; }
.page-header { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; }
.page-header h2 { font-size: 20px; color: #303133; }

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
</style>
