import { reactive, toRef } from 'vue'
import { strategiesApi } from '@/services/strategiesApi'
import { Timeframe } from '@/lib/Timeframe'

// Global state for timeframes
const state = reactive({
  timeframes: {}, // { '1s': Timeframe, '1m': Timeframe, ... }
  timeframesList: [], // [Timeframe, ...] sorted by valueMilliseconds
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
      
      // Create Timeframe objects and store in dictionary
      const timeframesObj = {}
      const timeframesArray = []
      
      for (const [key, milliseconds] of Object.entries(timeframesDict)) {
        const timeframe = new Timeframe(key, milliseconds)
        timeframesObj[key] = timeframe
        timeframesArray.push(timeframe)
      }
      
      // Sort by value in milliseconds
      timeframesArray.sort((a, b) => a.valueMilliseconds - b.valueMilliseconds)
      
      state.timeframes = timeframesObj
      state.timeframesList = timeframesArray
      
      state.isLoading = false
      return true
    } catch (error) {
      console.error('Failed to load timeframes:', error)
      state.hasError = true
      // Ensure errorMessage is always a string
      // Handle different error types: Error objects, TypeError, network errors, etc.
      let errorMsg = 'Failed to load timeframes'
      if (error instanceof Error) {
        errorMsg = error.message || error.toString() || errorMsg
      } else if (typeof error === 'string') {
        errorMsg = error
      } else if (error) {
        errorMsg = String(error)
      }
      state.errorMessage = errorMsg
      state.isLoading = false
      return false
    }
  }

  /**
   * Get Timeframe object by string value
   * @param {string} timeframeValue - Timeframe string (e.g., '1m', '1h')
   * @returns {Timeframe|null} Timeframe object or null if not found
   */
  const getTimeframe = (timeframeValue) => {
    return state.timeframes[timeframeValue] || null
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
    getTimeframe,
    isReady
  }
}

