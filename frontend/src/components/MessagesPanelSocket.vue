<template>
  <MessagesPanel :messages="allMessages" />
</template>

<script>
import MessagesPanel from './MessagesPanel.vue'

export default {
  name: 'MessagesPanelSocket',
  components: {
    MessagesPanel
  },
  emits: ['backtesting-error', 'messages-count-changed'],
  props: {
    taskId: {
      type: Number,
      default: null
    },
    localMessages: {
      type: Array,
      default: () => []
    }
  },
  data() {
    return {
      messages: [],
      messagesSocket: null
    }
  },
  computed: {
    allMessages() {
      // Combine local messages with WebSocket messages and sort by timestamp
      const combined = [...this.localMessages, ...this.messages]
      return combined.sort((a, b) => {
        const timeA = new Date(a.timestamp).getTime()
        const timeB = new Date(b.timestamp).getTime()
        return timeA - timeB
      })
    },
    messagesCount() {
      // Return total count of messages (local + WebSocket)
      return this.localMessages.length + this.messages.length
    },
    wsMessagesCount() {
      // Return count of WebSocket messages only
      return this.messages.length
    }
  },
  watch: {
    taskId(newTaskId, oldTaskId) {
      // Reconnect when taskId changes
      if (newTaskId !== oldTaskId) {
        this.disconnect()
        // Clear messages when task changes
        this.clearMessages()
        if (newTaskId) {
          this.connect(newTaskId)
        }
      }
    },
    wsMessagesCount(newCount) {
      // Emit event when WebSocket message count changes so parent can reactively update
      this.$emit('messages-count-changed', newCount)
    }
  },
  mounted() {
    if (this.taskId) {
      this.connect(this.taskId)
    }
    // Emit initial WebSocket messages count
    this.$emit('messages-count-changed', this.wsMessagesCount)
  },
  beforeUnmount() {
    this.disconnect()
  },
  methods: {
    connect(taskId) {
      // Close previous socket if any
      if (this.messagesSocket) {
        this.disconnect()
      }

      const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8202'
      const wsUrl = baseUrl.replace(/^http/i, 'ws') + `/api/v1/backtesting/tasks/${taskId}/messages`

      try {
        const socket = new WebSocket(wsUrl)
        this.messagesSocket = socket

        socket.onopen = () => {
          console.log(`Messages WebSocket connected for task ${taskId}`)
        }

        socket.onmessage = (event) => {
          try {
            const message = JSON.parse(event.data)
            // Ensure message has required fields
            if (message.timestamp && message.level && message.message) {
              this.messages.push({
                timestamp: message.timestamp,
                level: message.level,
                message: message.message,
                category: message.category || null
              })
              
              // Handle backtesting error messages (category="backtesting" and level="error")
              // These errors occur before the results stream starts
              if (message.category === 'backtesting' && message.level === 'error') {
                // Emit event to parent component to handle backtesting error
                this.$emit('backtesting-error', {
                  message: message.message,
                  timestamp: message.timestamp
                })
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
          this.messagesSocket = null
          console.log(`Messages WebSocket disconnected for task ${taskId}`)
        }
      } catch (e) {
        console.error('Failed to open messages WebSocket:', e)
      }
    },
    disconnect() {
      if (this.messagesSocket) {
        this.messagesSocket.close()
        this.messagesSocket = null
      }
    },
    clearMessages() {
      // Clear WebSocket messages
      this.messages = []
      // Emit event after clearing (watch will also trigger, but this ensures it)
      this.$nextTick(() => {
        this.$emit('messages-count-changed', this.wsMessagesCount)
      })
    },
    getMessagesCount() {
      // Return total count of messages (local + WebSocket)
      return this.localMessages.length + this.messages.length
    }
  }
}
</script>
