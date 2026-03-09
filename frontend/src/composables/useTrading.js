import { ref, computed, watch, onUnmounted } from 'vue'

/**
 * Composable for managing live trading WebSocket connection, messages, and state.
 *
 * Handles WS events from trading_worker.py:
 *   - trading_started → isTradingRunning = true
 *   - trading_stopped → isTradingRunning = false
 *   - progress → updates lastProgressTime (used for incremental results loading)
 *
 * @param {import('vue').Ref<number|null>} taskId - Reactive task ID
 * @returns {Object} Trading state and methods
 */
export function useTrading(taskId) {
  // WebSocket connection
  const messagesSocket = ref(null)

  // Reconnection state
  const reconnectAttempts = ref(0)
  const initialReconnectDelay = 1000
  const maxReconnectDelay = 8000
  const reconnectTimer = ref(null)
  const isManualDisconnect = ref(false)
  const currentReconnectTaskId = ref(null)

  // Messages state
  const wsMessages = ref([])
  const localMessages = ref([])

  // Trading state
  const isTradingRunning = ref(false)
  const tradingResultId = ref(null)
  const lastProgressTime = ref(null) // ISO string: current_time from progress event

  // Computed: combined messages sorted by timestamp
  const allMessages = computed(() => {
    const combined = [...localMessages.value, ...wsMessages.value]
    return combined.sort((a, b) => {
      return new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    })
  })

  const messagesCount = computed(() => {
    return localMessages.value.length + wsMessages.value.length
  })

  // ------------------------------------------------------------------
  // Reconnection helpers
  // ------------------------------------------------------------------

  function clearReconnectionState() {
    if (reconnectTimer.value) {
      clearTimeout(reconnectTimer.value)
      reconnectTimer.value = null
    }
    reconnectAttempts.value = 0
    currentReconnectTaskId.value = null
  }

  function attemptReconnect(targetTaskId) {
    if (isManualDisconnect.value || !targetTaskId) return
    if (targetTaskId !== taskId.value) return

    currentReconnectTaskId.value = targetTaskId

    const delay = Math.min(
      initialReconnectDelay * Math.pow(2, reconnectAttempts.value),
      maxReconnectDelay
    )
    reconnectAttempts.value++

    console.log(`[useTrading] Reconnect attempt ${reconnectAttempts.value} for task ${targetTaskId} in ${delay}ms`)

    reconnectTimer.value = setTimeout(() => {
      if (!isManualDisconnect.value && targetTaskId === taskId.value && targetTaskId === currentReconnectTaskId.value) {
        connect(targetTaskId)
      }
    }, delay)
  }

  function ensureConnection() {
    const currentTaskId = taskId.value
    if (!currentTaskId) return

    const socket = messagesSocket.value
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      if (socket) messagesSocket.value = null
      if (currentReconnectTaskId.value !== currentTaskId) {
        console.log('[useTrading] Connection not active, reconnecting...')
        attemptReconnect(currentTaskId)
      }
    }
  }

  // ------------------------------------------------------------------
  // WebSocket connection
  // ------------------------------------------------------------------

  function connect(connTaskId) {
    if (messagesSocket.value) {
      messagesSocket.value.close()
      messagesSocket.value = null
    }

    if (!connTaskId) return

    if (!currentReconnectTaskId.value) {
      clearReconnectionState()
      isManualDisconnect.value = false
    }

    const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8202'
    const wsUrl = baseUrl.replace(/^http/i, 'ws') + `/api/v1/trading/tasks/${connTaskId}/messages`

    try {
      const socket = new WebSocket(wsUrl)
      messagesSocket.value = socket

      socket.onopen = () => {
        console.log(`[useTrading] WebSocket connected for task ${connTaskId}`)
        clearReconnectionState()
        if (reconnectAttempts.value > 0) {
          addLocalMessage({ level: 'warning', message: 'WebSocket connection restored' })
        }
      }

      socket.onmessage = (event) => {
        try {
          const packet = JSON.parse(event.data)

          if (!packet.timestamp || !packet.type || !packet.data) {
            console.warn('[useTrading] Invalid message format:', packet)
            return
          }

          if (packet.type === 'message') {
            const data = packet.data
            if (data.level && data.message) {
              wsMessages.value.push({
                timestamp: packet.timestamp,
                broker_time: packet.broker_time || null,
                level: data.level,
                message: data.message,
              })
            }
          }

          if (packet.type === 'event') {
            const data = packet.data
            const evtName = data.event

            if (evtName === 'trading_started') {
              isTradingRunning.value = true
              if (data.result_id) tradingResultId.value = data.result_id
            } else if (evtName === 'trading_stopped') {
              isTradingRunning.value = false
              if (data.result_id) tradingResultId.value = data.result_id
            } else if (evtName === 'progress') {
              if (data.result_id) tradingResultId.value = data.result_id
              // Trigger incremental results reload via watcher on lastProgressTime
              if (data.current_time) {
                lastProgressTime.value = data.current_time
              } else {
                // No current_time — still bump to trigger reload
                lastProgressTime.value = new Date().toISOString()
              }
            }
          }
        } catch (e) {
          console.error('[useTrading] Failed to parse WS message:', e)
        }
      }

      socket.onerror = (event) => {
        console.error('[useTrading] WebSocket error:', event)
      }

      socket.onclose = (event) => {
        messagesSocket.value = null
        const { wasClean, code } = event

        console.log(`[useTrading] WebSocket closed for task ${connTaskId} (code: ${code}, clean: ${wasClean})`)

        if (isManualDisconnect.value) return
        if (connTaskId !== taskId.value) return

        if (code !== 1000 || !wasClean) {
          if (reconnectAttempts.value === 0) {
            addLocalMessage({ level: 'warning', message: 'WebSocket connection lost. Attempting to reconnect...' })
          }
          attemptReconnect(connTaskId)
        }
      }
    } catch (e) {
      console.error('[useTrading] Failed to open WebSocket:', e)
      if (!isManualDisconnect.value && connTaskId === taskId.value) {
        attemptReconnect(connTaskId)
      }
    }
  }

  function disconnect() {
    isManualDisconnect.value = true
    clearReconnectionState()
    if (messagesSocket.value) {
      messagesSocket.value.close()
      messagesSocket.value = null
    }
  }

  // ------------------------------------------------------------------
  // Messages helpers
  // ------------------------------------------------------------------

  function clearMessages() {
    wsMessages.value = []
  }

  function clearAllMessages() {
    wsMessages.value = []
    localMessages.value = []
  }

  function addLocalMessage(message) {
    localMessages.value.push({
      timestamp: new Date().toISOString(),
      level: message.level || 'info',
      message: message.message || message,
    })
  }

  // ------------------------------------------------------------------
  // State helpers
  // ------------------------------------------------------------------

  /**
   * Call immediately after startTask() API to optimistically set running state.
   */
  function setTradingStarted(resultId) {
    isTradingRunning.value = true
    if (resultId) tradingResultId.value = resultId
    lastProgressTime.value = null
  }

  /**
   * Reset all trading state (called when task is stopped or deselected).
   */
  function resetTradingState() {
    isTradingRunning.value = false
    tradingResultId.value = null
    lastProgressTime.value = null
  }

  // ------------------------------------------------------------------
  // Watch taskId: reconnect when task changes
  // ------------------------------------------------------------------

  watch(taskId, (newId, oldId) => {
    if (newId !== oldId) {
      disconnect()
      clearMessages()
      if (newId) {
        isManualDisconnect.value = false
        connect(newId)
      }
    }
  }, { immediate: true })

  onUnmounted(() => {
    disconnect()
  })

  return {
    // Messages
    allMessages,
    messagesCount,
    wsMessages,
    localMessages,

    // Trading state
    isTradingRunning,
    tradingResultId,
    lastProgressTime,

    // Methods
    connect,
    disconnect,
    ensureConnection,
    clearMessages,
    clearAllMessages,
    addLocalMessage,
    setTradingStarted,
    resetTradingState,
  }
}
