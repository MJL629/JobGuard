<template>
  <div class="profile-view" v-loading="loading">
    <div class="page-header">
      <div>
        <h2>我的求职画像</h2>
        <p>画像会由对话和简历解析持续补充，你也可以在这里核对和修改。</p>
      </div>
      <el-tag :type="completeness >= 60 ? 'success' : 'warning'">
        完整度 {{ completeness }}%
      </el-tag>
    </div>

    <el-alert
      v-if="errorMessage"
      :title="errorMessage"
      type="error"
      show-icon
      :closable="false"
      style="margin-bottom: 16px"
    />

    <div class="profile-layout">
      <div class="form-panel">
        <section class="section-card">
          <h3>基本信息</h3>
          <el-form :model="basic" label-width="100px">
            <el-row :gutter="16">
              <el-col :span="12"><el-form-item label="姓名"><el-input v-model="basic.full_name" /></el-form-item></el-col>
              <el-col :span="12">
                <el-form-item label="性别">
                  <el-select v-model="basic.gender" clearable style="width: 100%">
                    <el-option label="男" value="男" />
                    <el-option label="女" value="女" />
                    <el-option label="不便透露" value="不便透露" />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="16">
              <el-col :span="12"><el-form-item label="学历"><el-input v-model="basic.degree" placeholder="本科/硕士等" /></el-form-item></el-col>
              <el-col :span="12"><el-form-item label="专业"><el-input v-model="basic.major" /></el-form-item></el-col>
            </el-row>
            <el-row :gutter="16">
              <el-col :span="12"><el-form-item label="学校"><el-input v-model="basic.school" /></el-form-item></el-col>
              <el-col :span="12"><el-form-item label="毕业年份"><el-input-number v-model="basic.graduation_year" :min="1980" :max="2100" style="width: 100%" /></el-form-item></el-col>
            </el-row>
            <el-form-item label="当前城市"><el-input v-model="basic.current_city" /></el-form-item>
          </el-form>
        </section>

        <section class="section-card">
          <h3>求职偏好</h3>
          <el-form :model="preferences" label-width="100px">
            <el-form-item label="岗位方向">
              <el-select v-model="preferences.preferred_job_types" multiple allow-create filterable style="width: 100%" placeholder="例如：后端开发、AI 算法" />
            </el-form-item>
            <el-form-item label="意向城市">
              <el-select v-model="preferences.preferred_locations" multiple allow-create filterable style="width: 100%" placeholder="例如：广州、深圳" />
            </el-form-item>
            <el-row :gutter="16">
              <el-col :span="12"><el-form-item label="最低月薪"><el-input-number v-model="basic.expected_salary_min" :min="0" :step="1000" style="width: 100%" /></el-form-item></el-col>
              <el-col :span="12"><el-form-item label="最高月薪"><el-input-number v-model="basic.expected_salary_max" :min="0" :step="1000" style="width: 100%" /></el-form-item></el-col>
            </el-row>
            <el-row :gutter="16">
              <el-col :span="12"><el-form-item label="休息制度"><el-select v-model="preferences.weekend_preference" clearable style="width: 100%"><el-option label="必须双休" value="必须双休" /><el-option label="可接受单休" value="可接受单休" /><el-option label="不限" value="不限" /></el-select></el-form-item></el-col>
              <el-col :span="12"><el-form-item label="加班接受度"><el-select v-model="preferences.overtime_tolerance" clearable style="width: 100%"><el-option label="不接受" value="不接受" /><el-option label="偶尔可以" value="偶尔" /><el-option label="可以接受" value="接受" /></el-select></el-form-item></el-col>
            </el-row>
            <el-row :gutter="16">
              <el-col :span="12"><el-form-item label="强度上限"><el-select v-model="preferences.labor_intensity" clearable style="width: 100%"><el-option label="排斥长期/高强度" value="排斥高强度" /><el-option label="接受中等强度" value="接受中等" /><el-option label="不限" value="无所谓" /></el-select></el-form-item></el-col>
              <el-col :span="12"><el-form-item label="公司规模"><el-input v-model="preferences.company_scale_pref" placeholder="大厂/中型/初创/不限" /></el-form-item></el-col>
            </el-row>
            <el-form-item label="远程办公"><el-input v-model="preferences.remote_work" placeholder="不接受/混合/完全远程" /></el-form-item>
          </el-form>
          <div class="save-bar">
            <el-button type="primary" :loading="saving" @click="saveProfile">保存画像</el-button>
          </div>
        </section>
      </div>

      <aside class="summary-panel">
        <section class="summary-card">
          <h3>画像概览</h3>
          <el-progress :percentage="completeness" :stroke-width="12" />
          <p>岗位方向：{{ preferences.preferred_job_types?.join('、') || '待补充' }}</p>
          <p>意向城市：{{ preferences.preferred_locations?.join('、') || '待补充' }}</p>
          <p>期望月薪：{{ salaryText }}</p>
          <p>工作强度：{{ workloadText }}</p>
        </section>

        <section class="summary-card">
          <h3>项目经历（{{ projects.length }}）</h3>
          <div v-if="!projects.length" class="empty">还没有项目，请上传简历或通过对话补充。</div>
          <div v-for="project in projects" :key="project.id" class="list-item">
            <strong>{{ project.project_name }}</strong>
            <span>{{ (project.tech_stack || []).join('、') }}</span>
          </div>
        </section>

        <section class="summary-card">
          <h3>技能（{{ skills.length }}）</h3>
          <div class="tag-list">
            <el-tag v-for="skill in skills" :key="skill.skill_name" size="small">{{ skill.skill_name }}</el-tag>
            <span v-if="!skills.length" class="empty">待补充</span>
          </div>
        </section>

        <section class="summary-card">
          <h3>上传简历</h3>
          <el-upload
            drag
            action="#"
            :auto-upload="false"
            :show-file-list="false"
            accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp"
            :on-change="handleFileChange"
            :disabled="uploading"
          >
            <el-icon :size="34"><UploadFilled /></el-icon>
            <div>{{ uploading ? '正在识别并解析...' : '点击或拖入 PDF、DOCX、文本或简历图片' }}</div>
          </el-upload>
          <div v-if="resumes.length" class="resume-list">
            <div v-for="item in resumes" :key="item.id" class="resume-item">
              <div>
                <strong>{{ item.original_name }}</strong>
                <small>{{ parseStatusText(item.parse_status) }} · {{ item.extracted_chars || 0 }} 字</small>
                <small v-if="item.parse_error" class="parse-warning">{{ item.parse_error }}</small>
              </div>
              <el-button
                v-if="!item.is_primary"
                size="small"
                text
                type="primary"
                @click="makePrimary(item.id)"
              >设为主简历</el-button>
              <el-tag v-else size="small" type="success">主简历</el-tag>
            </div>
          </div>
          <div v-if="followUpQuestions.length" class="follow-up-box">
            <strong>简历解析后的深挖问题</strong>
            <ol>
              <li v-for="question in followUpQuestions" :key="question">{{ question }}</li>
            </ol>
            <router-link to="/chat">去对话中继续补充画像</router-link>
          </div>
        </section>

        <section class="summary-card">
          <h3>补充经历（{{ experiences.length }}）</h3>
          <p class="empty">没有简历也可以补充项目、实习、比赛、科研和工作经历；对话助手也会继续追问。</p>
          <div v-for="item in experiences" :key="item.id" class="list-item">
            <strong>{{ item.title }}</strong>
            <span>{{ experienceTypeText(item.experience_type) }}{{ item.role ? ` · ${item.role}` : '' }}</span>
          </div>
          <el-button size="small" type="primary" plain @click="experienceDialogVisible = true">手动补充经历</el-button>
        </section>
      </aside>
    </div>

    <el-dialog v-model="experienceDialogVisible" title="补充真实经历" width="520px">
      <el-form :model="experienceForm" label-width="90px">
        <el-form-item label="经历类型">
          <el-select v-model="experienceForm.experience_type" style="width: 100%">
            <el-option label="项目" value="project" /><el-option label="实习" value="internship" />
            <el-option label="比赛" value="competition" /><el-option label="科研" value="research" />
            <el-option label="工作" value="work" /><el-option label="证书" value="credential" />
            <el-option label="奖项" value="award" /><el-option label="组织协作" value="leadership" />
            <el-option label="其他" value="other" />
          </el-select>
        </el-form-item>
        <el-form-item label="名称"><el-input v-model="experienceForm.title" /></el-form-item>
        <el-form-item label="组织/单位"><el-input v-model="experienceForm.organization" /></el-form-item>
        <el-form-item label="你的角色"><el-input v-model="experienceForm.role" /></el-form-item>
        <el-form-item label="做了什么"><el-input v-model="experienceForm.actions" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="真实成果"><el-input v-model="experienceForm.achievements" type="textarea" :rows="2" placeholder="没有量化结果可留空，不会要求模型编造" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="experienceDialogVisible = false">取消</el-button><el-button type="primary" @click="saveExperience">保存</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import { addMyExperience, getMyProfile, getMyResumeStatus, setPrimaryResume, updateMyProfile, uploadMyResume } from '../api/profile'

const loading = ref(false)
const saving = ref(false)
const uploading = ref(false)
const errorMessage = ref('')
const completeness = ref(0)
const projects = ref([])
const skills = ref([])
const resumes = ref([])
const experiences = ref([])
const followUpQuestions = ref([])
const experienceDialogVisible = ref(false)
const experienceForm = reactive({ experience_type: 'project', title: '', organization: '', role: '', actions: '', achievements: '' })
const pollingResumeIds = new Set()
let viewUnmounted = false

const basic = reactive({
  full_name: '', gender: '', degree: '', major: '', school: '',
  graduation_year: null, current_city: '', expected_salary_min: null,
  expected_salary_max: null,
})

const preferences = reactive({
  preferred_job_types: [], preferred_locations: [], weekend_preference: '',
  overtime_tolerance: '', labor_intensity: '', company_scale_pref: '', remote_work: '',
})

const salaryText = computed(() => {
  if (!basic.expected_salary_min && !basic.expected_salary_max) return '待补充'
  return `${basic.expected_salary_min || '?'} - ${basic.expected_salary_max || '?'} 元`
})

const workloadText = computed(() => {
  const overtime = preferences.overtime_tolerance
  const intensity = preferences.labor_intensity
  if (overtime === '偶尔' && intensity === '排斥高强度') return '可接受偶尔正常加班；不接受长期或高强度加班'
  if (overtime === '接受' && intensity === '排斥高强度') return '可接受一般加班；不接受长期或高强度加班'
  if (overtime === '不接受') return '不接受加班'
  const parts = []
  if (overtime) parts.push(`加班：${overtime}`)
  if (intensity) parts.push(`强度：${intensity}`)
  return parts.join('；') || '待补充'
})

const applyProfile = (profile) => {
  Object.assign(basic, profile.basic || {})
  Object.assign(preferences, {
    preferred_job_types: [], preferred_locations: [], weekend_preference: '',
    overtime_tolerance: '', labor_intensity: '', company_scale_pref: '', remote_work: '',
    ...(profile.preferences || {}),
  })
  projects.value = profile.projects || []
  skills.value = profile.skills || []
  resumes.value = profile.resumes || []
  experiences.value = profile.experiences || []
  completeness.value = profile.completeness || 0
}

const loadProfile = async () => {
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await getMyProfile()
    applyProfile(response.data)
    resumes.value
      .filter((item) => ['pending', 'processing'].includes(item.parse_status))
      .forEach((item) => pollResumeUntilDone(item.id, false))
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || '画像加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

const saveProfile = async () => {
  saving.value = true
  errorMessage.value = ''
  try {
    const response = await updateMyProfile({ ...basic, ...preferences })
    applyProfile(response.data)
    ElMessage.success('画像已保存')
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || '画像保存失败，请稍后重试'
  } finally {
    saving.value = false
  }
}

const handleFileChange = async (uploadFile) => {
  const file = uploadFile.raw
  if (!file) return
  uploading.value = true
  errorMessage.value = ''
  try {
    const response = await uploadMyResume(file)
    followUpQuestions.value = response.data.follow_up_questions || []
    const fileInfo = response.data.file || {}
    const method = fileInfo.ocr_used ? '（已使用本地 OCR）' : ''
    if (response.data.parse_status === 'parsed') {
      ElMessage.success(`简历已保存并解析${method}，识别 ${fileInfo.extracted_chars || 0} 字，画像完整度 ${response.data.completeness}%`)
    } else if (['pending', 'processing'].includes(response.data.parse_status)) {
      const resumeId = response.data.resume?.id
      ElMessage.info(`简历已保存${method}，正在后台解析；完成后画像会自动刷新`)
      pollResumeUntilDone(resumeId, true)
    } else {
      ElMessage.warning('简历原文件和识别文本已保存，但结构化画像需要复核；你仍可继续上传其他简历或手动补充。')
    }
    await loadProfile()
  } catch (error) {
    const detail = error.response?.data?.detail
    errorMessage.value = detail?.message || detail || '简历上传或解析失败，请确认文件内容后重试'
  } finally {
    uploading.value = false
  }
}

const wait = (milliseconds) => new Promise((resolve) => window.setTimeout(resolve, milliseconds))

const pollResumeUntilDone = async (resumeId, notifyWhenDone = true) => {
  if (!resumeId || pollingResumeIds.has(resumeId)) return
  pollingResumeIds.add(resumeId)
  let consecutiveFailures = 0
  try {
    for (let attempt = 0; attempt < 150 && !viewUnmounted; attempt += 1) {
      await wait(2000)
      if (viewUnmounted) return
      try {
        const response = await getMyResumeStatus(resumeId)
        const status = response.data?.parse_status
        consecutiveFailures = 0
        if (status === 'parsed') {
          followUpQuestions.value = response.data.follow_up_questions || []
          await loadProfile()
          if (notifyWhenDone) {
            ElMessage.success(`简历解析完成，求职画像已自动更新至 ${response.data.completeness || 0}%`)
          }
          return
        }
        if (status === 'needs_review') {
          await loadProfile()
          errorMessage.value = response.data.resume?.parse_error || '简历结构化解析需要复核，原文件和识别文字已保留'
          return
        }
      } catch (error) {
        consecutiveFailures += 1
        if (consecutiveFailures >= 5) {
          errorMessage.value = '暂时无法获取简历解析进度，请稍后刷新页面；后台任务不会因此取消'
          return
        }
      }
    }
    if (!viewUnmounted) {
      errorMessage.value = '简历仍在后台解析，你可以继续使用其他页面，稍后返回画像页查看结果'
    }
  } finally {
    pollingResumeIds.delete(resumeId)
  }
}

const makePrimary = async (resumeId) => {
  try {
    const response = await setPrimaryResume(resumeId)
    if (response.code !== 0) throw new Error(response.message || '设置失败')
    await loadProfile()
    ElMessage.success('主简历已切换')
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || error.message || '主简历切换失败'
  }
}

const saveExperience = async () => {
  if (!experienceForm.title.trim()) return ElMessage.warning('请填写经历名称')
  try {
    const response = await addMyExperience({ ...experienceForm, evidence_text: experienceForm.actions, verification_status: 'user_confirmed' })
    if (response.code !== 0) throw new Error(response.message || '保存失败')
    Object.assign(experienceForm, { experience_type: 'project', title: '', organization: '', role: '', actions: '', achievements: '' })
    experienceDialogVisible.value = false
    await loadProfile()
    ElMessage.success('真实经历已保存')
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || error.message || '经历保存失败'
  }
}

const parseStatusText = (status) => ({ parsed: '已解析', needs_review: '需复核', pending: '等待解析', processing: '解析中' }[status] || status)
const experienceTypeText = (type) => ({ project: '项目', internship: '实习', competition: '比赛', research: '科研', work: '工作', credential: '证书', award: '奖项', leadership: '组织协作', other: '其他' }[type] || type)

onMounted(loadProfile)
onBeforeUnmount(() => { viewUnmounted = true })
</script>

<style scoped>
.profile-view { max-width: 1100px; margin: 0 auto; }
.resume-list { display: grid; gap: 8px; margin-top: 12px; }
.resume-item { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; padding: 10px; border: 1px solid #ebeef5; border-radius: 7px; }
.resume-item strong, .resume-item small { display: block; overflow-wrap: anywhere; }
.resume-item small { margin-top: 3px; color: #909399; }.resume-item .parse-warning { color: #e6a23c; }
.follow-up-box { margin-top: 14px; padding: 12px; border-radius: 8px; background: #f0f7ff; color: #315f82; font-size: 13px; }
.follow-up-box ol { margin: 8px 0; padding-left: 20px; color: #4b5563; }
.follow-up-box li { margin: 6px 0; line-height: 1.5; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.page-header h2 { margin: 0 0 6px; color: #303133; }
.page-header p { margin: 0; color: #909399; font-size: 13px; }
.profile-layout { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 20px; }
.section-card, .summary-card { background: #fff; padding: 20px; border-radius: 10px; box-shadow: 0 1px 8px rgba(0,0,0,.06); margin-bottom: 16px; }
.section-card h3, .summary-card h3 { margin: 0 0 16px; color: #303133; font-size: 16px; }
.save-bar { text-align: right; }
.summary-card p { color: #606266; font-size: 13px; }
.list-item { display: flex; flex-direction: column; gap: 4px; padding: 8px 0; border-bottom: 1px solid #ebeef5; font-size: 13px; }
.list-item span, .empty { color: #909399; font-size: 12px; }
.tag-list { display: flex; flex-wrap: wrap; gap: 6px; }
@media (max-width: 900px) { .profile-layout { grid-template-columns: 1fr; } }
</style>
