<template>
  <div class="profile-view">
    <div class="page-header">
      <h2>我的求职画像</h2>
      <el-tag v-if="completeness >= 60" type="success">完整度 {{ completeness }}%</el-tag>
      <el-tag v-else type="warning">完整度 {{ completeness }}%，请继续完善</el-tag>
    </div>

    <div class="profile-layout">
      <!-- Left: Form -->
      <div class="form-panel">
        <!-- Basic Info -->
        <div class="section-card">
          <h3>基本信息</h3>
          <el-form :model="basic" label-width="110px">
            <el-row :gutter="16">
              <el-col :span="12">
                <el-form-item label="姓名"><el-input v-model="basic.full_name" placeholder="请输入姓名" /></el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="性别">
                  <el-select v-model="basic.gender" style="width: 100%">
                    <el-option label="男" value="male" />
                    <el-option label="女" value="female" />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="16">
              <el-col :span="12">
                <el-form-item label="最高学历">
                  <el-select v-model="basic.degree" style="width: 100%">
                    <el-option label="专科" value="associate" />
                    <el-option label="本科" value="bachelor" />
                    <el-option label="硕士" value="master" />
                    <el-option label="博士" value="phd" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="专业"><el-input v-model="basic.major" placeholder="例如：计算机科学与技术" /></el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="16">
              <el-col :span="12">
                <el-form-item label="毕业院校"><el-input v-model="basic.school" placeholder="请输入毕业院校" /></el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="毕业年份"><el-input-number v-model="basic.graduation_year" :min="2000" :max="2030" style="width: 100%" /></el-form-item>
              </el-col>
            </el-row>
            <el-form-item label="当前城市"><el-input v-model="basic.current_city" placeholder="例如：北京" /></el-form-item>
          </el-form>
        </div>

        <!-- Job Preferences -->
        <div class="section-card">
          <h3>求职偏好</h3>
          <el-form :model="prefs" label-width="110px">
            <el-row :gutter="16">
              <el-col :span="12">
                <el-form-item label="最低月薪">
                  <el-input-number v-model="prefs.expected_salary_min" :min="0" :step="1000" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="最高月薪">
                  <el-input-number v-model="prefs.expected_salary_max" :min="0" :step="1000" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-form-item label="期望城市">
              <el-select v-model="prefs.preferred_locations" multiple placeholder="请选择城市" style="width: 100%">
                <el-option label="北京" value="beijing" />
                <el-option label="上海" value="shanghai" />
                <el-option label="杭州" value="hangzhou" />
                <el-option label="深圳" value="shenzhen" />
                <el-option label="广州" value="guangzhou" />
              </el-select>
            </el-form-item>
            <el-form-item label="求职方向">
              <el-select v-model="prefs.preferred_job_types" multiple placeholder="请选择方向" style="width: 100%">
                <el-option label="后端开发" value="backend" />
                <el-option label="前端开发" value="frontend" />
                <el-option label="全栈开发" value="fullstack" />
                <el-option label="人工智能与机器学习" value="ai_ml" />
                <el-option label="运维开发" value="devops" />
              </el-select>
            </el-form-item>
          </el-form>
        </div>

        <!-- Work Intensity -->
        <div class="section-card">
          <h3>工作强度偏好</h3>
          <el-form :model="prefs" label-width="130px">
            <el-form-item label="休息制度">
              <el-radio-group v-model="prefs.weekend_preference">
                <el-radio value="must_double">必须双休</el-radio>
                <el-radio value="accept_single">可以接受单休</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="加班接受度">
              <el-radio-group v-model="prefs.overtime_tolerance">
                <el-radio value="none">不能接受</el-radio>
                <el-radio value="occasional">可接受偶尔加班</el-radio>
                <el-radio value="accept">可以接受</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="公司规模">
              <el-radio-group v-model="prefs.company_scale_pref">
                <el-radio value="big">大型企业</el-radio>
                <el-radio value="medium">中型企业</el-radio>
                <el-radio value="startup">初创企业</el-radio>
                <el-radio value="any">不限</el-radio>
              </el-radio-group>
            </el-form-item>
          </el-form>
        </div>

        <div class="save-bar">
          <el-button type="primary" size="large" @click="saveProfile">保存画像</el-button>
        </div>
      </div>

      <!-- Right: Summary -->
      <div class="summary-panel">
        <div class="summary-card">
          <h3>画像摘要</h3>
          <el-progress :percentage="completeness" :color="progressColor" :stroke-width="12" />
          <div class="summary-items">
            <div class="summary-item">
              <span class="s-label">学历</span>
              <span class="s-value">{{ degreeLabel }}</span>
            </div>
            <div class="summary-item">
              <span class="s-label">院校</span>
              <span class="s-value">{{ basic.school || '-' }}</span>
            </div>
            <div class="summary-item">
              <span class="s-label">期望月薪</span>
              <span class="s-value">{{ salaryLabel }}</span>
            </div>
            <div class="summary-item">
              <span class="s-label">期望城市</span>
              <span class="s-value">{{ preferredCityLabels }}</span>
            </div>
          </div>
        </div>

        <div class="summary-card">
          <h3>项目经历（{{ projects.length }}）</h3>
          <div v-if="projects.length === 0" class="empty">暂无项目经历，可以上传简历或通过对话补充。</div>
          <div v-for="p in projects" :key="p.id" class="project-item">
            <div class="p-name">{{ p.project_name }}</div>
            <div class="p-tech">{{ (p.tech_stack || []).slice(0, 4).join(', ') }}</div>
          </div>
        </div>

        <div class="summary-card">
          <h3>技能（{{ skills.length }}）</h3>
          <div class="skill-tags">
            <el-tag v-for="s in skills" :key="s.skill_name" size="small">{{ s.skill_name }}</el-tag>
            <span v-if="skills.length === 0" class="empty">暂无技能信息</span>
          </div>
        </div>

        <div class="upload-card">
          <h3>上传简历</h3>
          <el-upload drag action="#" :auto-upload="false" :show-file-list="false" :on-change="handleFileChange">
            <el-icon :size="40"><UploadFilled /></el-icon>
            <div>将简历拖到这里，或点击选择文件</div>
            <template #tip>支持 PDF、TXT 或 Markdown 格式</template>
          </el-upload>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getProfile, updateProfile, uploadResume } from '../api/profile'
import { useUserStore } from '../stores/user'

const userStore = useUserStore()
const completeness = ref(0)
const progressColor = computed(() => completeness.value >= 60 ? '#67c23a' : '#e6a23c')

const basic = ref({
  full_name: '', gender: '', degree: '', major: '', school: '',
  graduation_year: null, current_city: '',
})

const prefs = ref({
  expected_salary_min: null, expected_salary_max: null,
  preferred_locations: [], preferred_job_types: [],
  weekend_preference: '', overtime_tolerance: '', company_scale_pref: '',
})

const projects = ref([])
const skills = ref([])

const degreeLabel = computed(() => ({
  associate: '专科', bachelor: '本科', master: '硕士', phd: '博士',
}[basic.value.degree] || '-'))

const preferredCityLabels = computed(() => {
  const cityMap = { beijing: '北京', shanghai: '上海', hangzhou: '杭州', shenzhen: '深圳', guangzhou: '广州' }
  return prefs.value.preferred_locations?.map(city => cityMap[city] || city).join('、') || '-'
})

const salaryLabel = computed(() => {
  const min = prefs.value.expected_salary_min
  const max = prefs.value.expected_salary_max
  if (!min && !max) return '-'
  return `${min || '?'} - ${max || '?'} 元/月`
})

const loadProfile = async () => {
  const userId = userStore.user?.id
  if (!userId) return
  try {
    const res = await getProfile(userId)
    const data = res.data || {}
    basic.value = { ...basic.value, ...(data.basic || {}) }
    const b = data.basic || {}
    prefs.value = {
      ...prefs.value,
      ...(data.preferences || {}),
      expected_salary_min: b.expected_salary_min ?? null,
      expected_salary_max: b.expected_salary_max ?? null,
      preferred_locations: data.preferences?.preferred_locations || [],
      preferred_job_types: data.preferences?.preferred_job_types || [],
    }
    projects.value = data.projects || []
    skills.value = data.skills || []
    completeness.value = data.completeness || 0
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '画像加载失败')
  }
}

const saveProfile = async () => {
  try {
    await updateProfile(userStore.user.id, { ...basic.value, ...prefs.value })
    await loadProfile()
    ElMessage.success('画像已保存，下次登录仍会保留')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '保存失败')
  }
}

const handleFileChange = async (file) => {
  try {
    ElMessage.info('正在解析并保存简历，请稍候')
    await uploadResume(userStore.user.id, file.raw)
    await loadProfile()
    ElMessage.success('简历与画像已保存')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '简历上传失败')
  }
}

onMounted(loadProfile)
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
