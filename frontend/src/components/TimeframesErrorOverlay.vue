<template>
  <div v-if="show" class="timeframes-error-overlay">
    <div class="error-content">
      <div class="error-icon">⚠️</div>
      <h2>Failed to Load Application Data</h2>
      <p class="error-message">{{ message }}</p>
      <p class="error-description">
        The application cannot start without loading timeframes configuration.
        Please check your internet connection and try again.
      </p>
      <button @click="onRetry" class="retry-button" :disabled="isRetrying">
        {{ isRetrying ? 'Retrying...' : 'Retry' }}
      </button>
    </div>
  </div>
</template>

<script>
export default {
  name: 'TimeframesErrorOverlay',
  props: {
    show: {
      type: Boolean,
      required: true
    },
    message: {
      type: String,
      default: 'Failed to load timeframes'
    },
    isRetrying: {
      type: Boolean,
      default: false
    }
  },
  emits: ['retry'],
  methods: {
    onRetry() {
      this.$emit('retry')
    }
  }
}
</script>

<style scoped>
.timeframes-error-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.85);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10000;
  backdrop-filter: blur(4px);
}

.error-content {
  background: #1e1e1e;
  border: 2px solid #dc3545;
  border-radius: 12px;
  padding: 40px;
  max-width: 500px;
  text-align: center;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
}

.error-icon {
  font-size: 64px;
  margin-bottom: 20px;
}

.error-content h2 {
  color: #dc3545;
  margin: 0 0 16px 0;
  font-size: 24px;
  font-weight: 600;
}

.error-message {
  color: #ff6b6b;
  margin: 0 0 12px 0;
  font-size: 16px;
  font-weight: 500;
}

.error-description {
  color: #aaa;
  margin: 0 0 24px 0;
  font-size: 14px;
  line-height: 1.6;
}

.retry-button {
  background: #dc3545;
  color: white;
  border: none;
  padding: 12px 32px;
  font-size: 16px;
  font-weight: 600;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.retry-button:hover:not(:disabled) {
  background: #c82333;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(220, 53, 69, 0.4);
}

.retry-button:active:not(:disabled) {
  transform: translateY(0);
}

.retry-button:disabled {
  background: #6c757d;
  cursor: not-allowed;
  opacity: 0.7;
}
</style>

