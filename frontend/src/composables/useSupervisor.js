import { ref, onUnmounted } from 'vue'
import { tradingApi } from '../services/tradingApi'

/**
 * Composable for managing the global supervisor WebSocket connection and error log.
 *
 * Subscribes to /api/v1/trading/supervisor/messages (Redis channel: supervisor:messages).
 * This channel is independent of any selected task — it receives all supervisor events.
 *
 * On mount: loads historical errors via REST GET /api/v1/trading/supervisor-errors.
 * On WS message: appends new entries to the errors list in real time.
 *
 * @returns {Object} Supervisor state and methods
 */
export function useSupervisor() {
  const supervisorErrors = ref([])
  const socket = ref(null)

  // Reconnection state
  const reconnectTimer = ref(null)
  const reconnectAttempts = ref(0)
  const isManualDisconnect = ref(false)
  const initialReconnectDelay = 1000
  const maxReconnectDelay = 16000

  // ------------------------------------------------------------------
  // REST: load historical errors
  // ------------------------------------------------------------------

  async function loadErrors() {
    try {
      const response = await tradingApi.getAllSupervisorErrors()
      if (response.success && Array.isArray(response.data)) {
        supervisorErrors.value = response.data
      }
    } catch (err) {
      console.error('[useSupervisor] Failed to load supervisor errors:', err)
    }
  }

  // ------------------------------------------------------------------
  // Reconnection helpers
  // ------------------------------------------------------------------

  function clearReconnectionState() {
    if (reconnectTimer.value) {
      clearTimeout(reconnectTimer.value)
      reconnectTimer.value = null
    }
    reconnectAttempts.value = 0
  }

  function attemptReconnect() {
    if (isManualDisconnect.value) return

    const delay = Math.min(
      initialReconnectDelay * Math.pow(2, reconnectAttempts.value),
      maxReconnectDelay
    )
    reconnectAttempts.value++

    console.log(`[useSupervisor] Reconnect attempt ${reconnectAttempts.value} in ${delay}ms`)

    reconnectTimer.value = setTimeout(() => {
      if (!isManualDisconnect.value) {
        connect()
      }
    }, delay)
  }

  // ------------------------------------------------------------------
  // WebSocket connection
  // ------------------------------------------------------------------

  function connect() {
    if (socket.value) {
      socket.value.close()
      socket.value = null
    }

    try {
      const ws = tradingApi.createSupervisorWebSocket()
      socket.value = ws

      ws.onopen = () => {
        console.log('[useSupervisor] WebSocket connected')
        clearReconnectionState()
      }

      ws.onmessage = (event) => {
        try {
          const entry = JSON.parse(event.data)
          // Assign sequential id based on current list length
          entry.id = supervisorErrors.value.length + 1
          supervisorErrors.value.push(entry)
        } catch (e) {
          console.error('[useSupervisor] Failed to parse WS message:', e)
        }
      }

      ws.onerror = (event) => {
        console.error('[useSupervisor] WebSocket error:', event)
      }

      ws.onclose = (event) => {
        socket.value = null
        const { wasClean, code } = event
        console.log(`[useSupervisor] WebSocket closed (code: ${code}, clean: ${wasClean})`)

        if (isManualDisconnect.value) return
        if (code !== 1000 || !wasClean) {
          attemptReconnect()
        }
      }
    } catch (e) {
      console.error('[useSupervisor] Failed to open WebSocket:', e)
      if (!isManualDisconnect.value) {
        attemptReconnect()
      }
    }
  }

  function disconnect() {
    isManualDisconnect.value = true
    clearReconnectionState()
    if (socket.value) {
      socket.value.close()
      socket.value = null
    }
  }

  function clearErrors() {
    supervisorErrors.value = []
  }

  // ------------------------------------------------------------------
  // Initialize: load REST data + connect WS
  // ------------------------------------------------------------------

  loadErrors()
  connect()

  onUnmounted(() => {
    disconnect()
  })

  return {
    supervisorErrors,
    loadErrors,
    clearErrors,
    connect,
    disconnect,
  }
}
