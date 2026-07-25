<template>
  <div class="profile-view">
    <div class="page-header">
      <h2>My Profile</h2>
      <el-tag v-if="completeness >= 60" type="success">{{ completeness }}% Complete</el-tag>
      <el-tag v-else type="warning">{{ completeness }}% - Needs More Info</el-tag>
    </div>

    <div class="profile-layout">
      <!-- Left: Form -->
      <div class="form-panel">
        <!-- Basic Info -->
        <div class="section-card">
          <h3>Basic Information</h3>
          <el-form :model="basic" label-width="110px">
            <el-row :gutter="16">
              <el-col :span="12">
                <el-form-item label="Name"><el-input v-model="basic.full_name" placeholder="Your name" /></el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="Gender">
                  <el-select v-model="basic.gender" style="width: 100%">
                    <el-option label="Male" value="male" />
                    <el-option label="Female" value="female" />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="16">
              <el-col :span="12">
                <el-form-item label="Degree">
                  <el-select v-model="basic.degree" style="width: 100%">
                    <el-option label="Associate" value="associate" />
                    <el-option label="Bachelor" value="bachelor" />
                    <el-option label="Master" value="master" />
                    <el-option label="PhD" value="phd" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="Major"><el-input v-model="basic.major" placeholder="e.g. Computer Science" /></el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="16">
              <el-col :span="12">
                <el-form-item label="School"><el-input v-model="basic.school" placeholder="Your university" /></el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="Graduation Year"><el-input-number v-model="basic.graduation_year" :min="2000" :max="2030" style="width: 100%" /></el-form-item>
              </el-col>
            </el-row>
            <el-form-item label="Current City"><el-input v-model="basic.current_city" placeholder="e.g. Beijing" /></el-form-item>
          </el-form>
        </div>

        <!-- Job Preferences -->
        <div class="section-card">
          <h3>Job Preferences</h3>
          <el-form :model="prefs" label-width="110px">
            <el-row :gutter="16">
              <el-col :span="12">
                <el-form-item label="Min Salary (K/mo)">
                  <el-input-number v-model="prefs.expected_salary_min" :min="0" :step="1000" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="Max Salary (K/mo)">
                  <el-input-number v-model="prefs.expected_salary_max" :min="0" :step="1000" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-form-item label="Preferred Cities">
              <el-select v-model="prefs.preferred_locations" multiple placeholder="Select cities" style="width: 100%">
                <el-option label="Beijing" value="beijing" />
                <el-option label="Shanghai" value="shanghai" />
                <el-option label="Hangzhou" value="hangzhou" />
                <el-option label="Shenzhen" value="shenzhen" />
                <el-option label="Guangzhou" value="guangzhou" />
              </el-select>
            </el-form-item>
            <el-form-item label="Job Direction">
              <el-select v-model="prefs.preferred_job_types" multiple placeholder="Select directions" style="width: 100%">
                <el-option label="Backend" value="backend" />
                <el-option label="Frontend" value="frontend" />
                <el-option label="Full Stack" value="fullstack" />
                <el-option label="AI/ML" value="ai_ml" />
                <el-option label="DevOps" value="devops" />
              </el-select>
            </el-form-item>
          </el-form>
        </div>

        <!-- Work Intensity -->
        <div class="section-card">
          <h3>Work Intensity Preferences</h3>
          <el-form :model="prefs" label-width="130px">
            <el-form-item label="Weekend">
              <el-radio-group v-model="prefs.weekend_preference">
                <el-radio value="must_double">Must have weekends off</el-radio>
                <el-radio value="accept_single">Accept single day off</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="Overtime">
              <el-radio-group v-model="prefs.overtime_tolerance">
                <el-radio value="none">Cannot accept</el-radio>
                <el-radio value="occasional">Occasional OK</el-radio>
                <el-radio value="accept">Accept</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="Company Size">
              <el-radio-group v-model="prefs.company_scale_pref">
                <el-radio value="big">Big Tech</el-radio>
                <el-radio value="medium">Medium</el-radio>
                <el-radio value="startup">Startup</el-radio>
                <el-radio value="any">Any</el-radio>
              </el-radio-group>
            </el-form-item>
          </el-form>
        </div>

        <div class="save-bar">
          <el-button type="primary" size="large" @click="saveProfile">Save Profile</el-button>
        </div>
      </div>

      <!-- Right: Summary -->
      <div class="summary-panel">
        <div class="summary-card">
          <h3>Profile Summary</h3>
          <el-progress :percentage="completeness" :color="progressColor" :stroke-width="12" />
          <div class="summary-items">
            <div class="summary-item">
              <span class="s-label">Degree</span>
              <span class="s-value">{{ basic.degree || '-' }}</span>
            </div>
            <div class="summary-item">
              <span class="s-label">School</span>
              <span class="s-value">{{ basic.school || '-' }}</span>
            </div>
            <div class="summary-item">
              <span class="s-label">Salary</span>
              <span class="s-value">{{ prefs.expected_salary_min || '?' }} - {{ prefs.expected_salary_max || '?' }}K</span>
            </div>
            <div class="summary-item">
              <span class="s-label">Cities</span>
              <span class="s-value">{{ prefs.preferred_locations?.join(', ') || '-' }}</span>
            </div>
          </div>
        </div>

        <div class="summary-card">
          <h3>Projects ({{ projects.length }})</h3>
          <div v-if="projects.length === 0" class="empty">No projects yet. Upload your resume or add via chat.</div>
          <div v-for="p in projects" :key="p.id" class="project-item">
            <div class="p-name">{{ p.project_name }}</div>
            <div class="p-tech">{{ (p.tech_stack || []).slice(0, 4).join(', ') }}</div>
          </div>
        </div>

        <div class="summary-card">
          <h3>Skills ({{ skills.length }})</h3>
          <div class="skill-tags">
            <el-tag v-for="s in skills" :key="s.skill_name" size="small">{{ s.skill_name }}</el-tag>
            <span v-if="skills.length === 0" class="empty">No skills yet</span>
          </div>
        </div>

        <div class="upload-card">
          <h3>Upload Resume</h3>
          <el-upload drag action="#" :auto-upload="false" :on-change="handleFileChange">
            <el-icon :size="40"><UploadFilled /></el-icon>
            <div>Drop resume file or click to upload</div>
            <template #tip>PDF, TXT, or Markdown</template>
          </el-upload>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const completeness = ref(45)
const progressColor = computed(() => completeness.value >= 60 ? '#67c23a' : '#e6a23c')

const basic = ref({
  full_name: 'Zhang San',
  gender: 'male',
  degree: 'bachelor',
  major: 'Computer Science',
  school: 'Tsinghua University',
  graduation_year: 2024,
  current_city: 'Beijing',
})

const prefs = ref({
  expected_salary_min: 15000,
  expected_salary_max: 25000,
  preferred_locations: ['beijing', 'hangzhou'],
  preferred_job_types: ['backend', 'ai_ml'],
  weekend_preference: 'must_double',
  overtime_tolerance: 'occasional',
  company_scale_pref: 'any',
})

const projects = ref([
  { id: 1, project_name: 'E-commerce Platform', tech_stack: ['Java', 'Spring Boot', 'MySQL', 'Redis'] },
  { id: 2, project_name: 'Online Education System', tech_stack: ['Java', 'Vue.js', 'WebSocket'] },
])

const skills = ref([
  { skill_name: 'Java' }, { skill_name: 'Python' }, { skill_name: 'Spring Boot' },
  { skill_name: 'MySQL' }, { skill_name: 'Redis' }, { skill_name: 'Docker' },
])

const saveProfile = () => {
  completeness.value = Math.min(100, completeness.value + 10)
}

const handleFileChange = (file) => {
  console.log('File selected:', file.name)
}
</script>

<style scoped>
.profile-view { max-width: 1000px; margin: 0 auto; }
.page-header { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; }
.page-header h2 { font-size: 20px; color: #303133; }

.profile-layout { display: grid; grid-template-columns: 1fr 300px; gap: 20px; }

.section-card {
  background: #fff; padding: 20px; border-radius: 8px;
  box-shadow: 0 1px 6px rgba(0,0,0,0.06); margin-bottom: 16px;
}
.section-card h3 { font-size: 15px; margin-bottom: 16px; color: #303133; border-bottom: 1px solid #ebeef5; padding-bottom: 8px; }

.save-bar { text-align: right; }

.summary-card, .upload-card {
  background: #fff; padding: 16px; border-radius: 8px;
  box-shadow: 0 1px 6px rgba(0,0,0,0.06); margin-bottom: 16px;
}
.summary-card h3, .upload-card h3 {
  font-size: 14px; margin-bottom: 12px; color: #303133;
}

.summary-items { margin-top: 12px; }
.summary-item { display: flex; justify-content: space-between; padding: 6px 0; font-size: 13px; border-bottom: 1px solid #f5f7fa; }
.s-label { color: #909399; }
.s-value { color: #303133; font-weight: 500; }

.project-item { padding: 8px 0; border-bottom: 1px solid #f5f7fa; }
.p-name { font-size: 13px; font-weight: 600; }
.p-tech { font-size: 12px; color: #909399; margin-top: 2px; }

.skill-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.empty { font-size: 13px; color: #c0c4cc; }
</style>
