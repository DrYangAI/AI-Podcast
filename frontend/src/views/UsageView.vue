<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { usageApi, type UsageSummary, type PricingEntry } from '../api/usage'

const loading = ref(false)
const summary = ref<UsageSummary | null>(null)
const days = ref<number | null>(null)   // null = 全部

const pricing = ref<PricingEntry[]>([])
const pricingOpen = ref(false)
const savingPricing = ref(false)

const unitLabel: Record<string, string> = {
  image: '元/张', char: '元/万字', token_in: '元/百万token(输入)', token_out: '元/百万token(输出)',
}
const typeName: Record<string, string> = { image: '图片', tts: '语音', text: '文本' }

const totalText = computed(() =>
  summary.value ? `¥${summary.value.total_cost.toFixed(2)}` : '—')

async function loadSummary() {
  loading.value = true
  try {
    const { data } = await usageApi.getSummary(days.value ? { days: days.value } : {})
    summary.value = data
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载费用失败')
  } finally {
    loading.value = false
  }
}

async function loadPricing() {
  try {
    const { data } = await usageApi.getPricing()
    pricing.value = data.entries
  } catch { /* ignore */ }
}

async function savePricing() {
  savingPricing.value = true
  try {
    await usageApi.savePricing(pricing.value)
    ElMessage.success('价格表已保存,费用已按新单价重算')
    await loadSummary()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    savingPricing.value = false
  }
}

function barWidth(cost: number): string {
  const max = Math.max(...(summary.value?.by_model.map(m => m.cost) || [1]), 0.0001)
  return `${Math.max(2, Math.round((cost / max) * 100))}%`
}

onMounted(async () => {
  await loadSummary()
  await loadPricing()
})
</script>

<template>
  <div v-loading="loading" style="max-width: 1100px;">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
      <h2 style="margin: 0;">费用核算</h2>
      <div>
        <el-radio-group v-model="days" size="small" @change="loadSummary">
          <el-radio-button :value="null">全部</el-radio-button>
          <el-radio-button :value="7">近 7 天</el-radio-button>
          <el-radio-button :value="30">近 30 天</el-radio-button>
        </el-radio-group>
        <el-button size="small" style="margin-left: 8px;" @click="loadSummary">刷新</el-button>
      </div>
    </div>
    <el-alert type="info" :closable="false" style="margin-bottom: 16px;">
      所有金额均为<b>估算</b>(用量 × 价格表),以火山引擎/各平台实际账单为准。价格表可在下方编辑,改后立即按新单价重算全部历史。
    </el-alert>

    <!-- 总计 + 按类型 -->
    <el-row :gutter="16" style="margin-bottom: 16px;">
      <el-col :span="8">
        <el-card shadow="never">
          <div style="color: #909399; font-size: 13px;">累计费用(估算)</div>
          <div style="font-size: 32px; font-weight: 700; color: #303133;">{{ totalText }}</div>
          <div style="color: #c0c4cc; font-size: 12px;">{{ summary?.record_count || 0 }} 条用量记录</div>
        </el-card>
      </el-col>
      <el-col :span="16">
        <el-card shadow="never">
          <div style="color: #909399; font-size: 13px; margin-bottom: 8px;">按类型</div>
          <div v-if="summary && summary.by_type.length" style="display: flex; gap: 24px;">
            <div v-for="t in summary.by_type" :key="t.provider_type">
              <span style="color: #606266;">{{ t.type_name }}</span>
              <span style="font-weight: 600; margin-left: 6px;">¥{{ t.cost.toFixed(2) }}</span>
            </div>
          </div>
          <el-empty v-else :image-size="40" description="暂无用量" />
        </el-card>
      </el-col>
    </el-row>

    <!-- 按模型明细 -->
    <el-card shadow="never" style="margin-bottom: 16px;">
      <template #header><span style="font-weight: 600;">按模型明细</span></template>
      <el-table v-if="summary && summary.by_model.length" :data="summary.by_model" size="small">
        <el-table-column label="类型" width="70">
          <template #default="{ row }">{{ row.type_name }}</template>
        </el-table-column>
        <el-table-column prop="provider_key" label="Provider" width="150" />
        <el-table-column prop="model_id" label="模型" min-width="220" show-overflow-tooltip />
        <el-table-column label="用量" width="140">
          <template #default="{ row }">{{ row.quantity.toLocaleString() }} {{ row.unit }}</template>
        </el-table-column>
        <el-table-column label="费用(估算)" width="200">
          <template #default="{ row }">
            <div style="display: flex; align-items: center; gap: 8px;">
              <div style="height: 8px; background: #409eff; border-radius: 4px;" :style="{ width: barWidth(row.cost) }"></div>
              <span style="font-weight: 600; white-space: nowrap;">¥{{ row.cost.toFixed(2) }}</span>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else :image-size="60" description="还没有产生费用。去生成图片/语音/文章后这里就会出现明细。" />
    </el-card>

    <!-- 按天 -->
    <el-card v-if="summary && summary.by_day.length" shadow="never" style="margin-bottom: 16px;">
      <template #header><span style="font-weight: 600;">按天</span></template>
      <el-table :data="summary.by_day" size="small" max-height="240">
        <el-table-column prop="day" label="日期" width="140" />
        <el-table-column label="费用(估算)">
          <template #default="{ row }">¥{{ row.cost.toFixed(2) }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 价格表(可编辑) -->
    <el-card shadow="never">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span style="font-weight: 600;">价格表(单价可编辑)</span>
          <el-button size="small" @click="pricingOpen = !pricingOpen">{{ pricingOpen ? '收起' : '展开编辑' }}</el-button>
        </div>
      </template>
      <el-collapse-transition>
        <div v-show="pricingOpen">
          <el-alert type="warning" :closable="false" style="margin-bottom: 12px;">
            火山引擎没有公开的单价查询接口,无法自动同步。价格调整后请在这里手动改单价(改完自动重算费用)。
            model 留空表示"该 Provider 任意模型"的兜底价。
          </el-alert>
          <el-table :data="pricing" size="small">
            <el-table-column label="类型" width="70">
              <template #default="{ row }">{{ typeName[row.provider_type] || row.provider_type }}</template>
            </el-table-column>
            <el-table-column prop="provider_key" label="Provider" width="150" />
            <el-table-column prop="model_id" label="模型(空=兜底)" min-width="200" show-overflow-tooltip />
            <el-table-column label="计价单位" width="170">
              <template #default="{ row }">{{ unitLabel[row.unit] || row.unit }}</template>
            </el-table-column>
            <el-table-column label="单价" width="130">
              <template #default="{ row }">
                <el-input-number v-model="row.price" :min="0" :step="0.01" :precision="4" size="small" controls-position="right" style="width: 110px;" />
              </template>
            </el-table-column>
            <el-table-column prop="note" label="说明" min-width="180" show-overflow-tooltip />
          </el-table>
          <div style="margin-top: 12px; text-align: right;">
            <el-button type="primary" size="small" :loading="savingPricing" @click="savePricing">保存价格表并重算</el-button>
          </div>
        </div>
      </el-collapse-transition>
    </el-card>
  </div>
</template>
