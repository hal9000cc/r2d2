<template>
  <div class="messages-panel">
    <h3>Messages</h3>
    <div class="messages-content" ref="messagesContainer">
      <div v-if="messages.length === 0" class="empty-state">
        <p>No messages</p>
      </div>
      <div
        v-for="(message, index) in messages"
        :key="index"
        class="message-item"
        :class="`message-${message.level}`"
      >
        <span class="message-time">{{ formatTime(message.timestamp) }}</span>
        <span class="message-level">{{ message.level.toUpperCase() }}</span>
        <span class="message-text">{{ message.message }}</span>
      </div>
    </div>
  </div>
</template>

<script>
import { activeStrategiesApi } from '../services/activeStrategiesApi'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8202'
const WS_BASE_URL = API_BASE_URL.replace('http://', 'ws://').replace('https://', 'wss://')

export default {
  name: 'MessagesPanel',
  props: {
    activeStrategyId: {
      type: Number,
      default: null
    }
  },
  data() {
    return {
      messages: [],
      websocket: null,
      messagesContainer: null
    }
  },
  watch: {
    activeStrategyId: {
      handler(newId, oldId) {
        if (newId !== oldId) {
          this.loadMessages(newId)
        }
      },
      immediate: true
    }
  },
  mounted() {
    this.messagesContainer = this.$refs.messagesContainer
  },
  beforeUnmount() {
    this.disconnectWebSocket()
  },
  methods: {
    async loadMessages(strategyId) {
      if (!strategyId) {
        this.messages = []
        this.disconnectWebSocket()
        return
      }

      try {
        // Disconnect old WebSocket
        this.disconnectWebSocket()

        // Load initial messages via HTTP
        this.messages = await activeStrategiesApi.getMessages(strategyId)
        this.scrollToBottom()

        // Connect to WebSocket for real-time updates
        this.connectWebSocket(strategyId)
      } catch (error) {
        console.error('Failed to load messages:', error)
        this.messages = []
      }
    },
    connectWebSocket(strategyId) {
      if (!strategyId) return

      const wsUrl = `${WS_BASE_URL}/api/v1/strategies/${strategyId}/messages`
      
      try {
        this.websocket = new WebSocket(wsUrl)

        this.websocket.onopen = () => {
          console.log('WebSocket connected for strategy', strategyId)
        }

        this.websocket.onmessage = (event) => {
          try {
            const message = JSON.parse(event.data)
            const wasAtBottom = this.isAtBottom()
            this.messages.push(message)
            // Keep only last 200 messages
            if (this.messages.length > 200) {
              this.messages = this.messages.slice(-200)
            }
            this.$nextTick(() => {
              // Only scroll if user was at bottom
              if (wasAtBottom) {
                this.scrollToBottom()
              }
            })
          } catch (error) {
            console.error('Failed to parse WebSocket message:', error)
          }
        }

        this.websocket.onerror = (error) => {
          console.error('WebSocket error:', error)
        }

        this.websocket.onclose = () => {
          console.log('WebSocket disconnected for strategy', strategyId)
        }
      } catch (error) {
        console.error('Failed to connect WebSocket:', error)
      }
    },
    disconnectWebSocket() {
      if (this.websocket) {
        this.websocket.close()
        this.websocket = null
      }
    },
    formatTime(timestamp) {
      if (!timestamp) return ''
      const date = new Date(timestamp)
      return date.toLocaleTimeString('en-US', {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
      })
    },
    isAtBottom() {
      if (!this.messagesContainer) return true
      const threshold = 50 // pixels from bottom to consider "at bottom"
      const scrollTop = this.messagesContainer.scrollTop
      const scrollHeight = this.messagesContainer.scrollHeight
      const clientHeight = this.messagesContainer.clientHeight
      return scrollTop + clientHeight >= scrollHeight - threshold
    },
    scrollToBottom() {
      if (this.messagesContainer) {
        this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight
      }
    }
  }
}
</script>

<style scoped>
.messages-panel {
  flex: 1;
  min-height: 100px;
  padding: 10px;
  background-color: #ffffff;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.messages-panel h3 {
  margin: 0 0 10px 0;
  font-size: 14px;
  font-weight: 600;
  color: #333;
  flex-shrink: 0;
}

.messages-content {
  flex: 1;
  overflow-y: auto;
  font-size: 12px;
  font-family: 'Courier New', monospace;
}

.empty-state {
  padding: 20px;
  text-align: center;
  color: #999;
  font-size: 12px;
}

.message-item {
  display: flex;
  gap: 8px;
  padding: 4px 8px;
  border-bottom: 1px solid #f0f0f0;
  align-items: baseline;
}

.message-item:last-child {
  border-bottom: none;
}

.message-time {
  color: #666;
  font-size: 11px;
  min-width: 80px;
  flex-shrink: 0;
}

.message-level {
  font-weight: 600;
  font-size: 10px;
  min-width: 50px;
  flex-shrink: 0;
  text-transform: uppercase;
}

.message-text {
  color: #333;
  flex: 1;
}

.message-info .message-level {
  color: #2196f3;
}

.message-warning .message-level {
  color: #ff9800;
}

.message-error .message-level {
  color: #f44336;
}

.message-debug .message-level {
  color: #9e9e9e;
}

.message-info {
  background-color: #e3f2fd;
}

.message-warning {
  background-color: #fff3e0;
}

.message-error {
  background-color: #ffebee;
}

.message-debug {
  background-color: #f5f5f5;
}
</style>

