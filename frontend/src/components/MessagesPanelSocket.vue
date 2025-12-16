<template>
  <MessagesPanel :messages="messages" />
</template>

<script>
import MessagesPanel from './MessagesPanel.vue'

export default {
  name: 'MessagesPanelSocket',
  components: {
    MessagesPanel
  },
  props: {
    taskId: {
      type: Number,
      default: null
    }
  },
  data() {
    return {
      messages: [],
      messagesSocket: null
    }
  },
  watch: {
    taskId(newTaskId, oldTaskId) {
      // Reconnect when taskId changes
      if (newTaskId !== oldTaskId) {
        this.disconnect()
        if (newTaskId) {
          this.connect(newTaskId)
        }
      }
    }
  },
  mounted() {
    if (this.taskId) {
      this.connect(this.taskId)
    }
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
                message: message.message
              })
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
    }
  }
}
</script>
