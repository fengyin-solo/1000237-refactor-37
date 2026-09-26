<template>
  <section class="page" data-module="equipment">
    <header class="page-head">
      <div>
        <h2>器材管理</h2>
        <p class="page-desc">维护拍摄器材从在库、领用到送修、退租的链路：每个状态可执行的动作由状态机统一下发，失败原因与流转记录逐条可查。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="toggleCreate">登记拍摄器材</button>
        <button class="btn" type="button" @click="exportRows">导出器材管理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <section v-if="showTransitions" class="panel">
      <h3 class="panel-title">状态流转对照（每个状态可走的环节）</h3>
      <ul class="transition-list">
        <li v-for="(rules, status) in transitions" :key="status">
          <strong>{{ status }}</strong>
          <template v-if="Object.keys(rules).length">
            <span v-for="(target, action) in rules" :key="action" class="transition-item">
              {{ action }} → {{ target }}
            </span>
          </template>
          <span v-else class="muted">终态，无后续动作</span>
        </li>
      </ul>
    </section>

    <form v-if="showCreate" class="panel create-panel" @submit.prevent="submitCreate">
      <h3 class="panel-title">登记拍摄器材</h3>
      <div class="create-fields">
        <label v-for="field in createFields" :key="field" class="filter-item">
          <span>{{ field }}{{ requiredFields.includes(field) ? '（必填）' : '' }}</span>
          <input v-model="createForm[field]" :placeholder="`填写${field}`" />
        </label>
      </div>
      <div class="create-actions">
        <button class="btn primary" type="submit">提交登记</button>
        <button class="btn ghost" type="button" @click="toggleCreate">取消</button>
      </div>
    </form>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>器材编号</span>
        <input v-model="keyword" placeholder="按器材编号检索" />
      </label>
      <label class="filter-item">
        <span>器材状态</span>
        <select v-model="status">
          <option value="">全部状态</option>
          <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
      <button class="btn ghost" type="button" @click="showTransitions = !showTransitions">状态流转说明</button>
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
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in row.available_actions ?? []"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <span v-if="!(row.available_actions ?? []).length" class="muted">已退租，链路结束</span>
            <button class="link" type="button" @click="openDetail(row)">流转记录</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无器材管理数据，可先登记拍摄器材</td>
        </tr>
      </tbody>
    </table>

    <section v-if="detail" class="panel">
      <h3 class="panel-title">
        流转记录：{{ detail['器材编号'] }}（当前状态：{{ detail.status }}）
        <button class="link" type="button" @click="detail = null">收起</button>
      </h3>
      <table class="data-table">
        <thead>
          <tr><th>时间</th><th>动作</th><th>从</th><th>到</th><th>结果</th><th>原因</th></tr>
        </thead>
        <tbody>
          <tr v-for="(record, index) in detail.history ?? []" :key="index">
            <td>{{ record.at }}</td>
            <td>{{ record.action }}</td>
            <td>{{ record.from_status }}</td>
            <td>{{ record.to_status }}</td>
            <td>{{ record.ok ? '成功' : '被拦下' }}</td>
            <td>{{ record.reason || '—' }}</td>
          </tr>
          <tr v-if="!(detail.history ?? []).length">
            <td colspan="6" class="empty-state">暂无流转记录（历史器材数据，尚未记录过操作）</td>
          </tr>
        </tbody>
      </table>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条器材管理记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

interface HistoryRecord {
  at: string
  action: string
  from_status: string
  to_status: string
  ok: boolean
  reason: string
}

interface Row {
  id: number | string
  status?: string
  available_actions?: string[]
  history?: HistoryRecord[]
  [key: string]: unknown
}

const ENDPOINT = '/api/equipment'
const columns = ["器材编号", "器材名称", "器材类别", "品牌型号", "所属租赁商", "日租金", "领用人员", "器材状态"]
const statuses = ["在库", "已领用", "维修中", "已退租"]
const requiredFields = ["器材编号", "器材名称", "器材类别"]
const createFields = [...requiredFields, "品牌型号", "所属租赁商"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const status = ref('')
const stats = ref([{ label: '在库器材', value: 0 }, { label: '已领用器材', value: 0 }, { label: '维修中器材', value: 0 }])
const transitions = ref<Record<string, Record<string, string>>>({})
const showTransitions = ref(false)
const showCreate = ref(false)
const createForm = ref<Record<string, string>>(Object.fromEntries(createFields.map((field) => [field, ''])))
const detail = ref<Row | null>(null)

function errorText(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback
}

function resetFilters() {
  keyword.value = ''
  status.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function toggleCreate() {
  showCreate.value = !showCreate.value
  errorMessage.value = ''
}

async function submitCreate() {
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createForm.value }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? '拍摄器材登记失败')
    }
    showCreate.value = false
    createForm.value = Object.fromEntries(createFields.map((field) => [field, '']))
    await reload()
  } catch (error) {
    errorMessage.value = errorText(error, '拍摄器材登记失败')
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  let remark = ''
  if (action === '送修失败') {
    const input = window.prompt('请填写送修失败原因（维修方反馈或故障情况）')
    if (input === null) {
      return
    }
    remark = input.trim()
    if (!remark) {
      errorMessage.value = '「送修失败」需要填写原因，说明维修方反馈或故障情况'
      return
    }
  }
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action }, remark }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? '器材管理动作未生效')
    }
    await reload()
    if (detail.value && detail.value.id === row.id) {
      await openDetail(row)
    }
  } catch (error) {
    errorMessage.value = errorText(error, '器材管理操作失败')
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('拍摄器材明细读取失败')
    }
    detail.value = (await response.json()) as Row
  } catch (error) {
    errorMessage.value = errorText(error, '拍摄器材明细读取失败')
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value) {
    query.set('keyword', keyword.value)
  }
  if (status.value) {
    query.set('status', status.value)
  }
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('拍摄器材列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    await refreshStats()
  } catch (error) {
    errorMessage.value = errorText(error, '器材管理列表读取失败')
  }
}

async function refreshStats() {
  try {
    const response = await request(`${ENDPOINT}?size=200`)
    if (!response.ok) {
      return
    }
    const payload = await response.json()
    const items = (payload.items ?? []) as Row[]
    stats.value = [
      { label: '在库器材', value: items.filter((row) => row.status === '在库').length },
      { label: '已领用器材', value: items.filter((row) => row.status === '已领用').length },
      { label: '维修中器材', value: items.filter((row) => row.status === '维修中').length },
    ]
  } catch {
    // 统计卡片刷新失败不影响列表使用
  }
}

async function loadTransitions() {
  try {
    const response = await request(`${ENDPOINT}/transitions`)
    if (!response.ok) {
      return
    }
    const payload = await response.json()
    transitions.value = payload.transitions ?? {}
  } catch {
    // 流转说明加载失败不影响列表使用
  }
}

onMounted(() => {
  void reload()
  void loadTransitions()
})
</script>

<style scoped>
.panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 12px;
}
.panel-title {
  font-size: 13px;
  margin: 0 0 8px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.transition-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
}
.transition-item {
  display: inline-block;
  margin-left: 8px;
  padding: 2px 8px;
  border: 1px solid var(--border);
  border-radius: 10px;
  color: var(--muted);
}
.muted {
  color: var(--muted);
  font-size: 12px;
  margin-left: 8px;
}
.create-fields {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 10px;
}
.create-actions {
  display: flex;
  gap: 8px;
}
</style>
