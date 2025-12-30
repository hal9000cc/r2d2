import { reactive, toRef } from 'vue'
import { strategiesApi } from '@/services/strategiesApi'

// Global state for timeframes
const state = reactive({
  timeframes: {}, // { '1s': 1000, '1m': 60000, ... } in milliseconds
  timeframesList: [], // ['1s', '1m', ...] sorted by value
  isLoading: false,
  hasError: false,
  errorMessage: ''
})

export function useTimeframes() {
  /**
   * Load timeframes from API
   * @returns {Promise<boolean>} true if loaded successfully, false otherwise
   */
  const loadTimeframes = async () => {
    state.isLoading = true
    state.hasError = false
    state.errorMessage = ''

    try {
      const timeframesDict = await strategiesApi.getTimeframes()
      
      // Store the dictionary
      state.timeframes = timeframesDict
      
      // Create sorted list for UI (sort by value in milliseconds)
      state.timeframesList = Object.entries(timeframesDict)
        .sort((a, b) => a[1] - b[1])
        .map(([key]) => key)
      
      state.isLoading = false
      return true
    } catch (error) {
      console.error('Failed to load timeframes:', error)
      state.hasError = true
      state.errorMessage = error.message || 'Failed to load timeframes'
      state.isLoading = false
      return false
    }
  }

  /**
   * Get timeframe duration in seconds
   * @param {string} timeframe - Timeframe string (e.g., '1m', '1h')
   * @returns {number} Duration in seconds, or 0 if not found
   */
  const getTimeframeSeconds = (timeframe) => {
    const milliseconds = state.timeframes[timeframe]
    return milliseconds ? milliseconds / 1000 : 0
  }

  /**
   * Get timeframe duration in milliseconds
   * @param {string} timeframe - Timeframe string (e.g., '1m', '1h')
   * @returns {number} Duration in milliseconds, or 0 if not found
   */
  const getTimeframeMilliseconds = (timeframe) => {
    return state.timeframes[timeframe] || 0
  }

  /**
   * Check if timeframes are loaded
   * @returns {boolean}
   */
  const isReady = () => {
    return !state.isLoading && !state.hasError && state.timeframesList.length > 0
  }

  return {
    // State - use toRef to maintain reactivity
    timeframes: toRef(state, 'timeframes'),
    timeframesList: toRef(state, 'timeframesList'),
    isLoading: toRef(state, 'isLoading'),
    hasError: toRef(state, 'hasError'),
    errorMessage: toRef(state, 'errorMessage'),
    
    // Methods
    loadTimeframes,
    getTimeframeSeconds,
    getTimeframeMilliseconds,
    isReady
  }
}

