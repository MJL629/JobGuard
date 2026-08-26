<template>
  <div class="trace-view">
    <div class="page-header">
      <h2>Agent运行记录</h2>
      <el-tag type="success">{{ summary.trace_count }} 条链路</el-tag>
      <el-button size="small" @click="loadTraces" :loading="loading">刷新</el-button>
    </div>

    <div class="trace-grid">
      <section class="panel">
        <h3>最近请求</h3>
        <div v-if="summary.traces.length === 0" class="empty-hint">暂无运行记录</div>
        <div v-for="trace in summary.traces" :key="trace.trace_id" class="trace-item">
          <div class="trace-title">
            <span>{{ trace.request_id || trace.trace_id }}</span>
            <el-tag size="small" :type="trace.status === 'ok' ? 'success' : 'danger'">{{ trace.status === 'ok' ? '成功' : '异常' }}</el-tag>
          </div>
          <div class="trace-meta">
            <span>{{ trace.latency_ms || 0 }} ms</span>
            <span>{{ trace.events }} 个事件</span>
            <span>{{ formatTime(trace.ended_at) }}</span>
          </div>
        </div>
      </section>

      <section class="panel">
        <h3>节点耗时</h3>
        <div v-if="summary.spans.length === 0" class="empty-hint">暂无节点统计</div>
        <div v-for="span in summary.spans" :key="span.name" class="span-row">
          <div>
            <div class="span-name">{{ span.name }}</div>
            <div class="span-count">{{ span.count }} 次调用</div>
          </div>
          <div class="span-latency">{{ span.avg_ms }} ms</div>
        </div>
      </section>
    </div>

    <section class="panel event-panel">
      <h3>事件明细</h3>
      <el-table :data="summary.events" size="small" height="360">
        <el-table-column prop="timestamp" label="时间" width="180">
          <template #default="{ row }">{{ formatTime(row.timestamp) }}</template>
        </el-table-column>
        <el-table-column prop="event" label="事件" width="150" />
        <el-table-column prop="name" label="节点" width="180" />
        <el-table-column prop="kind" label="类型" width="120" />
        <el-table-column prop="latency_ms" label="耗时(ms)" width="100" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">{{ row.status === 'error' ? '异常' : '成功' }}</template>
        </el-table-column>
        <el-table-column label="摘要">
          <template #default="{ row }">{{ row.output_summary || row.input_summary || row.model || row.error || '' }}</template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getAgentTraces } from '../api/observability'

const loading = ref(false)
const summary = ref({ trace_count: 0, event_count: 0, traces: [], spans: [], events: [] })

const loadTraces = async () => {
  loading.value = true
  try {
    const res = await getAgentTraces({ limit: 500 })
    summary.value = res.data || summary.value
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '运行记录加载失败')
  } finally {
    loading.value = false
  }
}

const formatTime = (value) => {
  if (!value) return ''
  return new Date(value).toLocaleString()
}

onMounted(loadTraces)
</script>

<style scoped>
.trace-view { max-width: 1180px; margin: 0 auto; }
.page-header { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; }
.page-header h2 { font-size: 20px; color: #303133; }
.trace-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
.panel { background: #fff; border-radius: 8px; padding: 16px; box-shadow: 0 1px 6px rgba(0,0,0,0.06); }
.panel h3 { font-size: 15px; margin-bottom: 12px; color: #303133; }
.trace-item { padding: 10px 0; border-bottom: 1px solid #f2f3f5; }
.trace-title { display: flex; justify-content: space-between; gap: 12px; font-size: 13px; font-weight: 600; color: #303133; }
.trace-meta { display: flex; gap: 12px; margin-top: 6px; font-size: 12px; color: #909399; }
.span-row { display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid #f2f3f5; }
.span-name { font-size: 13px; color: #303133; }
.span-count { font-size: 12px; color: #909399; margin-top: 4px; }
.span-latency { font-size: 15px; font-weight: 700; color: #409eff; }
.event-panel { margin-bottom: 24px; }
.empty-hint { font-size: 13px; color: #c0c4cc; text-align: center; padding: 24px; }
@media (max-width: 960px) {
  .trace-grid { grid-template-columns: 1fr; }
}
</style>
