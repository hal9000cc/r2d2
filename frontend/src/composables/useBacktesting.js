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
  
  // Reconnection state
  const reconnectAttempts = ref(0)
  const initialReconnectDelay = 1000 // Initial delay in ms
  const maxReconnectDelay = 8000 // Maximum delay in ms (8 seconds)
  const reconnectTimer = ref(null)
  const isManualDisconnect = ref(false) // Flag to distinguish manual vs automatic disconnect
  const currentReconnectTaskId = ref(null) // Track which taskId we're reconnecting for
  
  // Messages state
  const wsMessages = ref([]) // Messages from WebSocket
  const localMessages = ref([]) // Local messages (errors, etc.)
  
  // Backtesting state
  const isBacktestingRunning = ref(false)
  const backtestProgress = ref(0)
  const backtestProgressState = ref('idle') // 'idle' | 'running' | 'completed' | 'error'
  const backtestProgressErrorMessage = ref('')
  const backtestProgressErrorType = ref(null) // 'error' | 'cancel' | null
  const backtestProgressDateStart = ref(null) // ISO string: date_start from backtesting_progress
  const backtestProgressCurrentTime = ref(null) // ISO string: current_time from backtesting_progress
  const backtestProgressResultId = ref(null) // Result ID from backtesting_started/backtesting_progress
  
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
   * Clear reconnection state
   */
  function clearReconnectionState() {
    if (reconnectTimer.value) {
      clearTimeout(reconnectTimer.value)
      reconnectTimer.value = null
    }
    reconnectAttempts.value = 0
    currentReconnectTaskId.value = null
  }
  
  /**
   * Attempt to reconnect WebSocket with exponential backoff
   */
  function attemptReconnect(targetTaskId) {
    // Don't reconnect if manually disconnected or no taskId
    if (isManualDisconnect.value || !targetTaskId) {
      return
    }
    
    // Don't reconnect if taskId changed (different task selected)
    if (targetTaskId !== taskId.value) {
      return
    }
    
    // Track which taskId we're reconnecting for
    currentReconnectTaskId.value = targetTaskId
    
    // Calculate delay with exponential backoff (capped at maxReconnectDelay)
    const delay = Math.min(
      initialReconnectDelay * Math.pow(2, reconnectAttempts.value),
      maxReconnectDelay
    )
    
    reconnectAttempts.value++
    
    console.log(`Attempting to reconnect WebSocket for task ${targetTaskId} (attempt ${reconnectAttempts.value}) in ${delay}ms`)
    
    reconnectTimer.value = setTimeout(() => {
      // Check again if we should still reconnect
      if (!isManualDisconnect.value && targetTaskId === taskId.value && targetTaskId === currentReconnectTaskId.value) {
        connect(targetTaskId)
      }
    }, delay)
  }
  
  /**
   * Check if WebSocket is connected and attempt reconnection if needed
   * This should be called before API calls to ensure connection is active
   */
  function ensureConnection() {
    const currentTaskId = taskId.value
    if (!currentTaskId) {
      return
    }
    
    // Check if socket exists and is in OPEN state
    const socket = messagesSocket.value
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      // Connection is broken, attempt to reconnect
      if (socket) {
        // Socket exists but not open, clear it
        messagesSocket.value = null
      }
      
      // Only start reconnection if not already reconnecting for this task
      if (currentReconnectTaskId.value !== currentTaskId) {
        console.log('WebSocket connection is not active, attempting to reconnect before API call')
        attemptReconnect(currentTaskId)
      }
    }
  }
  
  /**
   * Connect to WebSocket for task messages
   */
  function connect(taskId) {
    // Close previous socket if any
    if (messagesSocket.value) {
      // Don't set isManualDisconnect here - we want to reconnect
      messagesSocket.value.close()
      messagesSocket.value = null
    }
    
    if (!taskId) {
      return
    }
    
    // Clear reconnection state on manual connect (not from reconnection attempt)
    if (!currentReconnectTaskId.value) {
      clearReconnectionState()
      isManualDisconnect.value = false
    }
    
    const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8202'
    const wsUrl = baseUrl.replace(/^http/i, 'ws') + `/api/v1/backtesting/tasks/${taskId}/messages`
    
    // Store taskId in closure for event handlers
    const connectTaskId = taskId
    
    try {
      const socket = new WebSocket(wsUrl)
      messagesSocket.value = socket
      
      socket.onopen = () => {
        console.log(`Messages WebSocket connected for task ${connectTaskId}`)
        // Reset reconnection state on successful connection
        clearReconnectionState()
        
        // Notify user if we just reconnected
        if (reconnectAttempts.value > 0) {
          addLocalMessage({
            level: 'warning',
            message: `WebSocket connection restored`
          })
        }
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
              backtestProgressDateStart.value = null
              backtestProgressCurrentTime.value = null
              
              // Save result_id from backtesting_started event
              if (data.result_id) {
                backtestProgressResultId.value = data.result_id
              }
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
                
                // Save date_start, current_time, and result_id from progress message
                if (data.date_start) {
                  backtestProgressDateStart.value = data.date_start
                }
                if (data.current_time) {
                  backtestProgressCurrentTime.value = data.current_time
                }
                if (data.result_id) {
                  backtestProgressResultId.value = data.result_id
                }
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
        // onerror usually follows onclose, so reconnection will be handled there
      }
      
      socket.onclose = (event) => {
        messagesSocket.value = null
        const wasClean = event.wasClean
        const code = event.code
        
        console.log(`Messages WebSocket disconnected for task ${connectTaskId} (code: ${code}, wasClean: ${wasClean})`)
        
        // Don't reconnect if manually disconnected
        if (isManualDisconnect.value) {
          return
        }
        
        // Don't reconnect if taskId changed (different task selected)
        if (connectTaskId !== taskId.value) {
          return
        }
        
        // Reconnect if:
        // 1. Not a normal closure (code !== 1000)
        // 2. Or if it was a normal closure but we didn't initiate it (unexpected)
        if (code !== 1000 || !wasClean) {
          // Only show message on first disconnect
          if (reconnectAttempts.value === 0) {
            addLocalMessage({
              level: 'warning',
              message: `WebSocket connection lost. Attempting to reconnect...`
            })
          }
          attemptReconnect(connectTaskId)
        }
      }
    } catch (e) {
      console.error('Failed to open messages WebSocket:', e)
      // If initial connection fails, try to reconnect
      if (!isManualDisconnect.value && connectTaskId === taskId.value) {
        attemptReconnect(connectTaskId)
      }
    }
  }
  
  /**
   * Disconnect WebSocket
   */
  function disconnect() {
    // Set flag to prevent reconnection
    isManualDisconnect.value = true
    
    // Clear any pending reconnection attempts
    clearReconnectionState()
    
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
    backtestProgressDateStart.value = null
    backtestProgressCurrentTime.value = null
    backtestProgressResultId.value = null
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
    backtestProgressDateStart.value = null
    backtestProgressCurrentTime.value = null
    backtestProgressResultId.value = null
  }
  
  // Watch taskId changes and reconnect
  // immediate: true ensures connection on mount if taskId is already set
  watch(taskId, (newTaskId, oldTaskId) => {
    if (newTaskId !== oldTaskId) {
      // Stop reconnection for old taskId
      disconnect()
      clearMessages()
      if (newTaskId) {
        // Reset manual disconnect flag before connecting to new task
        isManualDisconnect.value = false
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
    backtestProgressDateStart,
    backtestProgressCurrentTime,
    backtestProgressResultId,
    
    // Methods
    connect,
    disconnect,
    ensureConnection,
    clearMessages,
    clearAllMessages,
    addLocalMessage,
    setBacktestingStarted,
    resetBacktestingState
  }
}
