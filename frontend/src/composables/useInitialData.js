import { ref, computed } from 'vue'
import { useTimeframes } from './useTimeframes'

/**
 * Composable for managing initial application data loading
 * Handles loading of all required data before the app can start
 */
export function useInitialData() {
  const timeframesComposable = useTimeframes()
  
  // Loading state
  const isLoading = ref(false)
  const hasError = ref(false)
  const errorMessage = ref('')
  
  /**
   * Load all initial data required for the application
   * @returns {Promise<boolean>} true if all data loaded successfully, false otherwise
   */
  const loadAll = async () => {
    isLoading.value = true
    hasError.value = false
    errorMessage.value = ''
    
    try {
      // Load timeframes
      const timeframesSuccess = await timeframesComposable.loadTimeframes()
      
      if (!timeframesSuccess) {
        hasError.value = true
        // timeframesComposable.errorMessage is a ref, need to use .value
        errorMessage.value = timeframesComposable.errorMessage.value || 'Failed to load timeframes'
        isLoading.value = false
        return false
      }
      
      // Add more initial data loading here in the future
      // Example:
      // const sourcesSuccess = await sourcesComposable.loadSources()
      // if (!sourcesSuccess) {
      //   hasError.value = true
      //   errorMessage.value = sourcesComposable.errorMessage || 'Failed to load sources'
      //   isLoading.value = false
      //   return false
      // }
      
      isLoading.value = false
      return true
    } catch (error) {
      console.error('Failed to load initial data:', error)
      hasError.value = true
      // Ensure errorMessage is always a string
      errorMessage.value = error?.message || String(error) || 'Failed to load initial data'
      isLoading.value = false
      return false
    }
  }
  
  /**
   * Check if all initial data is ready
   * @returns {boolean}
   */
  const isReady = computed(() => {
    // Check timeframes readiness
    if (!timeframesComposable.isReady()) {
      return false
    }
    
    // Add more readiness checks here in the future
    // Example:
    // if (!sourcesComposable.isReady()) {
    //   return false
    // }
    
    return true
  })
  
  return {
    // State
    isLoading,
    hasError,
    errorMessage,
    
    // Computed
    isReady,
    
    // Methods
    loadAll
  }
}

