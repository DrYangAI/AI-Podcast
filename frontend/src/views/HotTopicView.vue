<script setup lang="ts">
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { sourcesApi } from '../api/sources'
import { useHotlistStore } from '../stores/hotlist'
import type { HotTopicItem } from '../types/source'

const router = useRouter()
const store = useHotlistStore()

const SOURCE_OPTIONS = [
  { value: 'weibo', label: '微博热搜' },
  { value: 'baidu', label: '百度热搜' },
  { value: 'toutiao', label: '头条热榜' },
]

async function handleFetch() {
  if (store.selectedSources.length === 0) {
    ElMessage.warning('请至少选择一个热榜来源')
    return
  }
  try {
    const data = await store.fetchRecommendations()
    if (data.items.length === 0) {
      ElMessage.info('未找到健康相关的热门话题')
    } else {
      ElMessage.success(`从 ${data.total_scraped} 条热搜中筛选出 ${data.items.length} 个健康话题`)
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '获取推荐失败')
  }
}

async function handleCreateProject(topic: HotTopicItem) {
  try {
    const { data } = await sourcesApi.createProjectFromHotTopic({
      title: topic.title,
      health_angle: topic.health_angle,
      source_url: topic.url || undefined,
    })
    ElMessage.success('项目已创建')
    router.push(`/projects/${data.id}`)
  } catch {
    ElMessage.error('创建失败')
  }
}

function getSourceTagType(source: string) {
  const map: Record<string, string> = {
    weibo: 'danger',
    baidu: '',
    toutiao: 'warning',
  }
  return map[source] || 'info'
}

function formatRelevance(score: number) {
  return Math.round(score * 100)
}
</script>

<template>
  <div style="max-width: 1200px; margin: 0 auto;">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <h2 style="margin: 0;">热门健康话题推荐</h2>
      <div style="display: flex; gap: 12px; align-items: center;">
        <el-select
          v-model="store.selectedSources"
          multiple
          collapse-tags
          collapse-tags-tooltip
          placeholder="选择来源"
          style="width: 260px;"
        >
          <el-option
            v-for="opt in SOURCE_OPTIONS"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>
        <el-button type="primary" :loading="store.loading" @click="handleFetch">
          <el-icon v-if="!store.loading"><Search /></el-icon>
          {{ store.loading ? '正在抓取并分析...' : '获取推荐' }}
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="!store.loading && store.topics.length === 0"
      type="info"
      :closable="false"
      style="margin-bottom: 16px;"
    >
      <template #title>
        点击"获取推荐"按钮，系统将从微博、百度、头条热榜中抓取话题，并使用 AI 筛选出健康相关话题。
      </template>
    </el-alert>

    <el-skeleton v-if="store.loading" :rows="8" animated />

    <template v-if="!store.loading && store.topics.length > 0">
      <!-- Category filter -->
      <div style="margin-bottom: 16px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center;">
        <el-text type="info" size="small" style="margin-right: 4px;">分类筛选:</el-text>
        <el-check-tag
          v-for="cat in store.categories"
          :key="cat"
          :checked="store.activeCategory === cat"
          @change="store.activeCategory = cat"
        >
          {{ cat === 'all' ? '全部' : cat }}
        </el-check-tag>
        <el-text type="info" size="small" style="margin-left: auto;">
          共抓取 {{ store.totalScraped }} 条热搜，筛选出 {{ store.topics.length }} 个健康话题
        </el-text>
      </div>

      <!-- Results table -->
      <el-card shadow="never">
        <el-table :data="store.filteredTopics" stripe>
          <el-table-column label="#" width="50" type="index" />
          <el-table-column label="话题" min-width="200">
            <template #default="{ row }">
              <div>
                <span style="font-weight: 500;">{{ row.title }}</span>
                <el-link
                  v-if="row.url"
                  :href="row.url"
                  target="_blank"
                  type="info"
                  :underline="false"
                  style="font-size: 12px; margin-left: 6px;"
                >
                  原文
                </el-link>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="来源" width="100">
            <template #default="{ row }">
              <el-tag :type="getSourceTagType(row.source)" size="small">
                {{ row.source_name }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="分类" width="100">
            <template #default="{ row }">
              <el-tag type="info" size="small" effect="plain">{{ row.category }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="相关度" width="100">
            <template #default="{ row }">
              <el-progress
                :percentage="formatRelevance(row.relevance_score)"
                :stroke-width="6"
                :show-text="false"
                :color="row.relevance_score > 0.8 ? '#67c23a' : row.relevance_score > 0.5 ? '#e6a23c' : '#909399'"
                style="width: 60px; display: inline-block;"
              />
              <span style="font-size: 12px; margin-left: 4px; color: #909399;">
                {{ formatRelevance(row.relevance_score) }}%
              </span>
            </template>
          </el-table-column>
          <el-table-column label="建议角度" min-width="220">
            <template #default="{ row }">
              <el-text type="info" size="small">{{ row.health_angle }}</el-text>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="90" fixed="right">
            <template #default="{ row }">
              <el-button
                text
                size="small"
                type="primary"
                @click="handleCreateProject(row)"
              >
                创建项目
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>
  </div>
</template>
