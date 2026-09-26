<template>
  <section class="page" data-module="equipment">
    <header class="page-head">
      <div>
        <h2>器材管理管理</h2>
        <p class="page-desc">维护拍摄器材，围绕器材编号、器材名称、器材类别、品牌型号做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记拍摄器材</button>
        <button class="btn" type="button" @click="exportRows">导出器材管理清单</button>
      </div>
    </header>

    <div class="lifecycle-strip">
      <span class="lifecycle-title">状态链路</span>
      <span v-for="line in lifecycleLines" :key="line" class="lifecycle-line">{{ line }}</span>
    </div>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ cellText(row, column) }}</td>
          <td class="row-actions">
            <template v-if="rowActions(row).length">
              <button
                v-for="action in rowActions(row)"
                :key="action"
                class="link"
                type="button"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
            </template>
            <span v-else class="muted-text">链路已终结</span>
            <details v-if="rowLogs(row).length" class="log-details">
              <summary>流转记录</summary>
              <ul>
                <li v-for="(log, index) in rowLogs(row)" :key="index">
                  {{ log.从 }} → {{ log.到 }}（{{ log.环节 }}）<template v-if="log.说明">：{{ log.说明 }}</template>
                </li>
              </ul>
            </details>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无器材管理数据，可先登记拍摄器材</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条器材管理记录</span>
      <span v-if="noticeMessage" class="ok-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { fetchJson, request } from '@/api/client'

type LogEntry = { 环节?: string; 从?: string; 到?: string; 说明?: string }
type Row = Record<string, unknown> & {
  id?: number
  status?: string
  available_actions?: string[]
  流转记录?: LogEntry[]
}

const ENDPOINT = '/api/equipment'
const columns = ["器材编号", "器材名称", "器材类别", "品牌型号", "所属租赁商", "日租金", "领用人员", "器材状态"]
const STATUS_COLUMN = '器材状态'

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const stats = ref([
  { label: '在库器材', value: 0 },
  { label: '已领用器材', value: 0 },
  { label: '维修中器材', value: 0 },
])
const lifecycleLines = ref<string[]>([])

function rowActions(row: Row): string[] {
  return Array.isArray(row.available_actions) ? row.available_actions : []
}

function rowLogs(row: Row): LogEntry[] {
  return Array.isArray(row.流转记录) ? row.流转记录 : []
}

function cellText(row: Row, column: string): string {
  // 器材状态列以状态机里的 status 为准，避免展示历史登记文本造成的误读。
  const value = column === STATUS_COLUMN ? row.status : row[column]
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

function refreshStats() {
  const counts: Record<string, number> = { 在库: 0, 已领用: 0, 维修中: 0 }
  for (const row of rows.value) {
    const status = String(row.status ?? '')
    if (status in counts) counts[status] += 1
  }
  stats.value = [
    { label: '在库器材', value: counts['在库'] },
    { label: '已领用器材', value: counts['已领用'] },
    { label: '维修中器材', value: counts['维修中'] },
  ]
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '拍摄器材登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  const values: Record<string, string> = { action }
  if (action === '维修失败') {
    const note = window.prompt('请填写维修失败原因（器材将退回送修前状态，原因会写入流转记录）')
    if (note === null) return
    values['处理说明'] = note
  }
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? payload.detail ?? '器材管理动作未生效，请稍后重试')
    }
    noticeMessage.value = String(payload.message ?? '')
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '器材管理操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const payload = await fetchJson<{ items?: Row[]; total?: number }>(`${ENDPOINT}?${query}`)
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    refreshStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '器材管理列表读取失败'
  }
}

async function loadLifecycle() {
  try {
    const data = await fetchJson<{ transitions: Record<string, Record<string, string>> }>(
      `${ENDPOINT}/lifecycle`,
    )
    lifecycleLines.value = Object.entries(data.transitions ?? {}).map(([status, rules]) => {
      const parts = Object.entries(rules).map(([action, target]) => `${action}→${target}`)
      return `${status}：${parts.length ? parts.join('，') : '链路终结'}`
    })
  } catch {
    lifecycleLines.value = []
  }
}

onMounted(() => {
  void reload()
  void loadLifecycle()
})
</script>

<style scoped>
.lifecycle-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  align-items: baseline;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 12px;
}
.lifecycle-title {
  font-weight: 600;
}
.lifecycle-line {
  color: var(--muted);
}
.muted-text {
  color: var(--muted);
  font-size: 12px;
}
.ok-text {
  color: #067647;
}
.log-details {
  display: inline-block;
  margin-left: 8px;
  font-size: 12px;
  color: var(--muted);
}
.log-details ul {
  margin: 4px 0 0;
  padding-left: 16px;
}
</style>
