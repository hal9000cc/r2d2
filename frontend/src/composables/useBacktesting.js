import { ref, computed, watch, onUnmounted } from 'vue'

/**
 * Composable for managing backtesting WebSocket connection, messages, and state
 * 
 * @param {import('vue').Ref<number|null>} taskId - Reactive task ID
 * @returns {Object} Backtesting state and methods
 */
export function useBacktesting(taskId) {
  // WebSocket connection
  const messagesSocket = ref(null)
  
  // Messages state
  const wsMessages = ref([]) // Messages from WebSocket
  const localMessages = ref([]) // Local messages (errors, etc.)
  
  // Backtesting state
  const isBacktestingRunning = ref(false)
  const backtestProgress = ref(0)
  const backtestProgressState = ref('idle') // 'idle' | 'running' | 'completed' | 'error'
  const backtestProgressErrorMessage = ref('')
  const backtestProgressErrorType = ref(null) // 'error' | 'cancel' | null
  
  // Computed: combined messages sorted by timestamp
  const allMessages = computed(() => {
    const combined = [...localMessages.value, ...wsMessages.value]
    return combined.sort((a, b) => {
      const timeA = new Date(a.timestamp).getTime()
      const timeB = new Date(b.timestamp).getTime()
      return timeA - timeB
    })
  })
  
  // Computed: total messages count
  const messagesCount = computed(() => {
    return localMessages.value.length + wsMessages.value.length
  })
  
  /**
   * Connect to WebSocket for task messages
   */
  function connect(taskId) {
    // Close previous socket if any
    if (messagesSocket.value) {
      disconnect()
    }
    
    if (!taskId) {
      return
    }
    
    const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8202'
    const wsUrl = baseUrl.replace(/^http/i, 'ws') + `/api/v1/backtesting/tasks/${taskId}/messages`
    
    try {
      const socket = new WebSocket(wsUrl)
      messagesSocket.value = socket
      
      socket.onopen = () => {
        console.log(`Messages WebSocket connected for task ${taskId}`)
      }
      
      socket.onmessage = (event) => {
        try {
          const packet = JSON.parse(event.data)
          
          // New format: {timestamp, type, data}
          if (!packet.timestamp || !packet.type || !packet.data) {
            console.warn('Invalid message format:', packet)
            return
          }
          
          // Handle message type (for messages panel)
          if (packet.type === 'message') {
            const data = packet.data
            if (data.level && data.message) {
              wsMessages.value.push({
                timestamp: packet.timestamp,
                level: data.level,
                message: data.message
              })
            }
          }
          
          // Handle event type (for state management)
          if (packet.type === 'event') {
            const data = packet.data
            const event = data.event
            
            if (event === 'backtesting_error') {
              backtestProgressState.value = 'error'
              backtestProgressErrorType.value = 'error'
              backtestProgressErrorMessage.value = 'Backtesting error occurred'
              isBacktestingRunning.value = false
            } else if (event === 'backtesting_started') {
              isBacktestingRunning.value = true
              backtestProgressState.value = 'running'
              backtestProgress.value = 0
              backtestProgressErrorMessage.value = ''
              backtestProgressErrorType.value = null
            } else if (event === 'backtesting_progress') {
              // Only update progress if backtesting is running
              if (backtestProgressState.value === 'running' && isBacktestingRunning.value) {
                // Validate and clamp progress value
                let progress = data.progress
                if (typeof progress !== 'number' || isNaN(progress)) {
                  addLocalMessage({
                    level: 'error',
                    message: `Invalid progress value received: ${progress}`
                  })
                  return
                }
                // Clamp to [0, 100]
                progress = Math.max(0, Math.min(100, progress))
                backtestProgress.value = progress
              } else {
                // Progress update received outside of running state - log as error
                addLocalMessage({
                  level: 'error',
                  message: `Progress update received but backtesting is not running (state: ${backtestProgressState.value})`
                })
              }
            } else if (event === 'backtesting_completed') {
              isBacktestingRunning.value = false
              backtestProgressState.value = 'completed'
              backtestProgress.value = 100
            }
          }
        } catch (e) {
          console.error('Failed to parse message from WebSocket:', e)
        }
      }
      
      socket.onerror = (event) => {
        console.error('Messages WebSocket error:', event)
      }
      
      socket.onclose = () => {
        messagesSocket.value = null
        console.log(`Messages WebSocket disconnected for task ${taskId}`)
      }
    } catch (e) {
      console.error('Failed to open messages WebSocket:', e)
    }
  }
  
  /**
   * Disconnect WebSocket
   */
  function disconnect() {
    if (messagesSocket.value) {
      messagesSocket.value.close()
      messagesSocket.value = null
    }
  }
  
  /**
   * Clear WebSocket messages
   */
  function clearMessages() {
    wsMessages.value = []
  }
  
  /**
   * Clear all messages (WebSocket + local)
   */
  function clearAllMessages() {
    wsMessages.value = []
    localMessages.value = []
  }
  
  /**
   * Add local message (for errors, warnings, etc.)
   */
  function addLocalMessage(message) {
    localMessages.value.push({
      timestamp: new Date().toISOString(),
      level: message.level || 'info',
      message: message.message || message
    })
  }
  
  /**
   * Set backtesting state to started (called immediately after API call)
   */
  function setBacktestingStarted() {
    isBacktestingRunning.value = true
    backtestProgressState.value = 'running'
    backtestProgress.value = 0
    backtestProgressErrorMessage.value = ''
    backtestProgressErrorType.value = null
  }
  
  /**
   * Reset backtesting state (called on error or cancellation)
   */
  function resetBacktestingState() {
    isBacktestingRunning.value = false
    backtestProgressState.value = 'idle'
    backtestProgress.value = 0
    backtestProgressErrorMessage.value = ''
    backtestProgressErrorType.value = null
  }
  
  // Watch taskId changes and reconnect
  // immediate: true ensures connection on mount if taskId is already set
  watch(taskId, (newTaskId, oldTaskId) => {
    if (newTaskId !== oldTaskId) {
      disconnect()
      clearMessages()
      if (newTaskId) {
        connect(newTaskId)
      }
    }
  }, { immediate: true })
  
  // Disconnect on unmount
  onUnmounted(() => {
    disconnect()
  })
  
  return {
    // Messages
    allMessages,
    messagesCount,
    wsMessages,
    localMessages,
    
    // Backtesting state
    isBacktestingRunning,
    backtestProgress,
    backtestProgressState,
    backtestProgressErrorMessage,
    backtestProgressErrorType,
    
    // Methods
    connect,
    disconnect,
    clearMessages,
    clearAllMessages,
    addLocalMessage,
    setBacktestingStarted,
    resetBacktestingState
  }
}
