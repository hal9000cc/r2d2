<template>
  <div id="app">
    <AppLayout />
    <TimeframesErrorOverlay 
      :show="showErrorOverlay" 
      :message="errorMessage"
      :isRetrying="isRetrying"
      @retry="handleRetryLoadTimeframes"
    />
  </div>
</template>

<script>
import { provide, ref, onMounted } from 'vue'
import AppLayout from './components/AppLayout.vue'
import TimeframesErrorOverlay from './components/TimeframesErrorOverlay.vue'
import { useTimeframes } from '@/composables/useTimeframes'
import { useAlert } from '@/composables/useAlert'

export default {
  name: 'App',
  components: {
    AppLayout,
    TimeframesErrorOverlay
  },
  setup() {
    const timeframesComposable = useTimeframes()
    const { error: showErrorAlert } = useAlert()
    
    const showErrorOverlay = ref(false)
    const errorMessage = ref('')
    const isRetrying = ref(false)

    // Provide timeframes composable to all child components
    provide('timeframes', timeframesComposable)

    const loadTimeframes = async () => {
      const success = await timeframesComposable.loadTimeframes()
      
      if (!success) {
        showErrorOverlay.value = true
        errorMessage.value = timeframesComposable.errorMessage || 'Failed to load timeframes'
        showErrorAlert('Failed to load application data. Please check your connection.')
      } else {
        showErrorOverlay.value = false
      }
      
      return success
    }

    const handleRetryLoadTimeframes = async () => {
      isRetrying.value = true
      await loadTimeframes()
      isRetrying.value = false
    }

    onMounted(() => {
      loadTimeframes()
    })

    return {
      showErrorOverlay,
      errorMessage,
      isRetrying,
      handleRetryLoadTimeframes
    }
  }
}
</script>

<style>
/* Global styles are imported from assets/styles.css */
</style>

