<template>
  <div class="agent-ops" v-loading="loading">
    <div class="page-header">
      <div>
        <h2>Agent 运行与评估</h2>
        <p>查看真实执行图、工具可用性、失败步骤与确定性评估，不用“感觉不错”代替指标。</p>
      </div>
      <el-button @click="loadData">刷新</el-button>
    </div>

    <el-alert v-if="errorMessage" :title="errorMessage" type="error" :closable="false" show-icon />

    <div class="metric-grid">
      <div class="metric-card"><span>运行总数</span><strong>{{ metrics.runs_total ?? '-' }}</strong></div>
      <div class="metric-card"><span>流程成功率</span><strong>{{ percent(metrics.workflow_success_rate) }}</strong></div>
      <div class="metric-card"><span>工具成功率</span><strong>{{ percent(metrics.tool_success_rate) }}</strong></div>
      <div class="metric-card"><span>平均响应</span><strong>{{ duration(metrics.average_duration_ms) }}</strong></div>
    </div>

    <el-alert
      class="truth-alert"
      type="warning"
      :closable="false"
      show-icon
      title="真实性边界"
      :description="`${metrics.cost_status || '成本尚未取得'}；${metrics.accuracy_status || '内容准确率需要离线集或人工标注'}`"
    />

    <div class="two-columns">
      <section class="panel">
        <h3>生产 LangGraph</h3>
        <p>运行时：{{ graph.runtime || '-' }} · 单次编译：{{ graph.compiled_once ? '是' : '否' }}</p>
        <div class="flow" v-if="graph.nodes?.length">
          <template v-for="(node, index) in graph.nodes" :key="node">
            <el-tag size="large">{{ node }}</el-tag><span v-if="index < graph.nodes.length - 1">→</span>
          </template>
        </div>
        <p class="muted">{{ graph.note }}</p>
      </section>

      <section class="panel">
        <h3>工具与人机确认</h3>
        <el-table :data="tools" size="small" max-height="320">
          <el-table-column prop="name" label="工具" min-width="190" />
          <el-table-column label="类别" width="100"><template #default="scope">{{ categoryLabel(scope.row.category) }}</template></el-table-column>
          <el-table-column label="执行" width="90"><template #default="scope">{{ scope.row.execution_mode === 'write' ? '写入' : '只读' }}</template></el-table-column>
          <el-table-column label="确认" width="90"><template #default="scope"><el-tag :type="scope.row.requires_confirmation ? 'warning' : 'success'" size="small">{{ scope.row.requires_confirmation ? '需要' : '无需' }}</el-tag></template></el-table-column>
          <el-table-column label="MCP" width="80"><template #default="scope">{{ scope.row.expose_via_mcp ? '是' : '否' }}</template></el-table-column>
        </el-table>
      </section>
    </div>

    <section class="panel">
      <h3>最近运行</h3>
      <el-table :data="runs" size="small">
        <el-table-column label="时间" min-width="170"><template #default="scope">{{ formatTime(scope.row.created_at) }}</template></el-table-column>
        <el-table-column label="工作流" width="130"><template #default="scope">{{ workflowLabel(scope.row.workflow) }}</template></el-table-column>
        <el-table-column prop="intent" label="意图/工具" min-width="170" />
        <el-table-column label="状态" width="100"><template #default="scope"><el-tag :type="scope.row.status === 'completed' ? 'success' : scope.row.status === 'running' ? 'warning' : 'danger'" size="small">{{ statusLabel(scope.row.status) }}</el-tag></template></el-table-column>
        <el-table-column label="耗时" width="100"><template #default="scope">{{ duration(scope.row.duration_ms) }}</template></el-table-column>
        <el-table-column label="工具" width="100"><template #default="scope">{{ scope.row.tool_success_count }}/{{ scope.row.tool_calls_count }}</template></el-table-column>
        <el-table-column prop="failure_step" label="失败步骤" min-width="140" />
        <el-table-column prop="error_type" label="错误类型" min-width="130" />
      </el-table>
      <el-empty v-if="!runs.length" description="还没有 Agent 运行记录" />
    </section>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { getAgentGraph, getAgentMetrics, getAgentRuns, getAgentTools } from '../api/agent'

const loading = ref(false)
const errorMessage = ref('')
const graph = ref({})
const metrics = ref({})
const tools = ref([])
const runs = ref([])

const percent = (value) => value == null ? '-' : `${Math.round(value * 100)}%`
const duration = (value) => value == null ? '-' : value >= 1000 ? `${(value / 1000).toFixed(1)} 秒` : `${value} ms`
const formatTime = (value) => value ? new Date(`${value}Z`).toLocaleString('zh-CN', { hour12: false }) : '-'
const workflowLabel = (value) => ({ chat: '对话', tool_execution: '工具执行', job_analysis: '岗位分析', resume_generation: '简历生成' }[value] || value || '-')
const statusLabel = (value) => ({ completed: '已完成', failed: '失败', running: '运行中' }[value] || value || '-')
const categoryLabel = (value) => ({ evidence: '证据核验', search: '信息检索', analyze: '分析', profile: '画像', generate: '生成' }[value] || value || '-')

const loadData = async () => {
  loading.value = true
  errorMessage.value = ''
  try {
    const [graphResponse, toolResponse, runResponse, metricResponse] = await Promise.all([
      getAgentGraph(), getAgentTools(), getAgentRuns(), getAgentMetrics(),
    ])
    graph.value = graphResponse.data || {}
    tools.value = toolResponse.data?.items || []
    runs.value = runResponse.data?.items || []
    metrics.value = metricResponse.data || {}
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || 'Agent 运行数据加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>

<style scoped>
.agent-ops { max-width: 1200px; margin: 0 auto; }
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 18px; }
.page-header h2 { margin: 0 0 6px; color: #303133; }
.page-header p, .muted { color: #909399; font-size: 13px; margin: 0; }
.metric-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin: 18px 0; }
.metric-card, .panel { background: #fff; border-radius: 10px; box-shadow: 0 1px 8px rgba(0,0,0,.06); }
.metric-card { padding: 18px; display: flex; flex-direction: column; gap: 8px; }
.metric-card span { color: #909399; font-size: 13px; }.metric-card strong { color: #315f82; font-size: 25px; }
.truth-alert { margin-bottom: 16px; }.two-columns { display: grid; grid-template-columns: 1fr 1.4fr; gap: 16px; }
.panel { padding: 18px; margin-bottom: 16px; }.panel h3 { margin: 0 0 14px; color: #303133; }
.flow { display: flex; align-items: center; gap: 8px; margin: 14px 0; flex-wrap: wrap; }
@media (max-width: 900px) { .metric-grid { grid-template-columns: 1fr 1fr; }.two-columns { grid-template-columns: 1fr; } }
</style>
