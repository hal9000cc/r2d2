<template>
  <Teleport to="body">
    <Transition name="modal">
      <div 
        v-if="isOpen" 
        class="modal-overlay"
        @click.self="handleClose"
      >
        <div class="modal-content error-modal">
          <div class="modal-header">
            <h3>{{ title }}</h3>
            <button class="close-btn" @click="handleClose">
              <XMarkIcon class="icon" />
            </button>
          </div>
          
          <div class="modal-body">
            <p class="error-message">{{ message }}</p>
          </div>
          
          <div class="modal-footer">
            <button class="btn btn-primary" @click="handleClose">OK</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script>
import { XMarkIcon } from '@heroicons/vue/24/outline'

export default {
  name: 'ErrorModal',
  components: {
    XMarkIcon
  },
  props: {
    isOpen: {
      type: Boolean,
      default: false
    },
    message: {
      type: String,
      default: 'An error occurred'
    },
    title: {
      type: String,
      default: 'Failed to create strategy'
    }
  },
  emits: ['close'],
  watch: {
    isOpen(newValue) {
      if (newValue) {
        // Close on ESC key
        document.addEventListener('keydown', this.handleKeyDown)
      } else {
        document.removeEventListener('keydown', this.handleKeyDown)
      }
    }
  },
  beforeUnmount() {
    document.removeEventListener('keydown', this.handleKeyDown)
  },
  methods: {
    handleClose() {
      this.$emit('close')
    },
    handleKeyDown(event) {
      if (event.key === 'Escape') {
        this.handleClose()
      }
    }
  }
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: var(--z-modal);
}

.modal-content {
  background-color: var(--bg-primary);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-xl);
  max-width: 500px;
  width: 90%;
  max-height: 90vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.error-modal {
  max-width: 400px;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--spacing-lg);
}

.modal-header h3 {
  margin: 0;
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
}

.close-btn {
  background: none;
  border: none;
  cursor: pointer;
  padding: var(--spacing-xs);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-tertiary);
  transition: color var(--transition-base);
}

.close-btn:hover {
  color: var(--text-primary);
}

.icon {
  width: 20px;
  height: 20px;
}

.modal-body {
  padding: var(--spacing-lg);
  flex: 1;
  overflow-y: auto;
}

.error-message {
  margin: 0;
  color: var(--text-primary);
  font-size: var(--font-size-base);
  line-height: 1.5;
}

.modal-footer {
  padding: var(--spacing-lg);
  display: flex;
  justify-content: flex-end;
  gap: var(--spacing-md);
}

.btn {
  padding: var(--spacing-sm) var(--spacing-xl);
  border: none;
  border-radius: var(--radius-md);
  font-weight: var(--font-weight-medium);
  font-size: var(--font-size-sm);
  cursor: pointer;
  transition: background-color var(--transition-base);
}

.btn-primary {
  background-color: var(--color-primary);
  color: var(--text-inverse);
}

.btn-primary:hover {
  background-color: var(--color-primary-hover);
}

.btn-primary:active {
  background-color: var(--color-primary-active);
}

/* Modal transition */
.modal-enter-active,
.modal-leave-active {
  transition: opacity var(--transition-base);
}

.modal-enter-active .modal-content,
.modal-leave-active .modal-content {
  transition: transform var(--transition-base), opacity var(--transition-base);
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-from .modal-content,
.modal-leave-to .modal-content {
  transform: scale(0.95);
  opacity: 0;
}
</style>

