<template>
  <div id="app">
    <NavBar>
      <template #navbar-content>
        <!-- Content will be teleported here from views -->
      </template>
    </NavBar>
    <AppLayout v-if="isInitialDataReady" />
    <TimeframesErrorOverlay 
      :show="showErrorOverlay" 
      :message="errorMessage"
      :isRetrying="isRetrying"
      @retry="handleRetryLoadInitialData"
    />
  </div>
</template>

<script>
import { provide, ref, onMounted } from 'vue'
import NavBar from './components/NavBar.vue'
import AppLayout from './components/AppLayout.vue'
import TimeframesErrorOverlay from './components/TimeframesErrorOverlay.vue'
import { useTimeframes } from '@/composables/useTimeframes'
import { useInitialData } from '@/composables/useInitialData'
import { useAlert } from '@/composables/useAlert'

export default {
  name: 'App',
  components: {
    NavBar,
    AppLayout,
    TimeframesErrorOverlay
  },
  setup() {
    const timeframesComposable = useTimeframes()
    const initialData = useInitialData()
    const { error: showErrorAlert } = useAlert()
    
    const showErrorOverlay = ref(false)
    const errorMessage = ref('')
    const isRetrying = ref(false)

    // Provide timeframes composable to all child components
    provide('timeframes', timeframesComposable)

    const loadInitialData = async () => {
      const success = await initialData.loadAll()
      
      if (!success) {
        showErrorOverlay.value = true
        // Ensure errorMessage is always a string
        const errorMsg = initialData.errorMessage.value
        errorMessage.value = typeof errorMsg === 'string' ? errorMsg : (errorMsg?.message || String(errorMsg) || 'Failed to load initial data')
        showErrorAlert('Failed to load application data. Please check your connection.')
      } else {
        showErrorOverlay.value = false
      }
      
      return success
    }

    const handleRetryLoadInitialData = async () => {
      isRetrying.value = true
      await loadInitialData()
      isRetrying.value = false
    }

    onMounted(() => {
      loadInitialData()
    })

    return {
      showErrorOverlay,
      errorMessage,
      isRetrying,
      isInitialDataReady: initialData.isReady,
      handleRetryLoadInitialData
    }
  }
}
</script>

<style>
#app {
  display: flex;
  flex-direction: column;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
}
</style>

