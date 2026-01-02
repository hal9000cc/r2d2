<template>
  <div class="messages-panel">
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
export default {
  name: 'MessagesPanel',
  props: {
    messages: {
      type: Array,
      default: () => []
    }
  },
  data() {
    return {
      messagesContainer: null
    }
  },
  watch: {
    messages: {
      handler() {
        this.$nextTick(() => {
          this.scrollToBottom()
        })
      },
      deep: true
    }
  },
  mounted() {
    this.messagesContainer = this.$refs.messagesContainer
  },
  methods: {
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
        const wasAtBottom = this.isAtBottom()
        if (wasAtBottom) {
          this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight
        }
      }
    }
  }
}
</script>

<style scoped>
.messages-panel {
  flex: 1;
  min-height: 100px;
  padding: var(--spacing-sm);
  background-color: var(--bg-primary);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.messages-content {
  flex: 1;
  overflow-y: auto;
  font-size: var(--font-size-xs);
  font-family: 'Courier New', monospace;
}

.empty-state {
  padding: var(--spacing-xl);
  text-align: center;
  color: var(--text-muted);
  font-size: var(--font-size-xs);
}

.message-item {
  display: flex;
  gap: var(--spacing-sm);
  padding: var(--spacing-xs) var(--spacing-sm);
  border-bottom: 1px solid var(--bg-tertiary);
  align-items: baseline;
}

.message-item:last-child {
  border-bottom: none;
}

.message-time {
  color: var(--text-tertiary);
  font-size: 11px;
  min-width: 80px;
  flex-shrink: 0;
}

.message-level {
  font-weight: var(--font-weight-semibold);
  font-size: 10px;
  min-width: 50px;
  flex-shrink: 0;
  text-transform: uppercase;
}

.message-text {
  color: var(--text-primary);
  flex: 1;
}

.message-info .message-level {
  color: var(--color-info);
}

.message-warning .message-level {
  color: var(--color-warning);
}

.message-error .message-level {
  color: var(--color-danger);
}

.message-debug .message-level {
  color: var(--text-muted);
}

.message-info {
  background-color: var(--color-info-light);
}

.message-warning {
  background-color: var(--color-warning-light);
}

.message-error {
  background-color: var(--color-danger-light);
}

.message-debug {
  background-color: var(--bg-tertiary);
}
</style>

