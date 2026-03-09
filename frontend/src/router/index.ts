import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'dashboard',
      component: () => import('../views/DashboardView.vue'),
    },
    {
      path: '/projects',
      name: 'projects',
      component: () => import('../views/ProjectListView.vue'),
    },
    {
      path: '/projects/:id',
      name: 'project-detail',
      component: () => import('../views/ProjectDetailView.vue'),
      children: [
        {
          path: '',
          name: 'project-pipeline',
          component: () => import('../views/PipelineView.vue'),
        },
        {
          path: 'article',
          name: 'project-article',
          component: () => import('../views/ArticleEditorView.vue'),
        },
        {
          path: 'segments',
          name: 'project-segments',
          component: () => import('../views/SegmentManagerView.vue'),
        },
        {
          path: 'images',
          name: 'project-images',
          component: () => import('../views/ImageGalleryView.vue'),
        },
        {
          path: 'script',
          name: 'project-script',
          component: () => import('../views/ScriptEditorView.vue'),
        },
        {
          path: 'audio',
          name: 'project-audio',
          component: () => import('../views/AudioManagerView.vue'),
        },
        {
          path: 'video',
          name: 'project-video',
          component: () => import('../views/VideoPreviewView.vue'),
        },
      ],
    },
    {
      path: '/sources',
      name: 'sources',
      component: () => import('../views/SourceManagerView.vue'),
    },
    {
      path: '/hotlist',
      name: 'hotlist',
      component: () => import('../views/HotTopicView.vue'),
    },
    {
      path: '/settings/providers',
      name: 'provider-settings',
      component: () => import('../views/ProviderSettingsView.vue'),
    },
  ],
})

export default router
