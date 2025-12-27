<template>
  <Teleport to="body">
    <div class="alert-container">
      <TransitionGroup name="alert">
        <div
          v-for="alert in alerts"
          :key="alert.id"
          class="alert-item"
          :class="`alert-${alert.type}`"
          @click="handleRemove(alert.id)"
        >
          <div class="alert-icon">
            <svg v-if="alert.type === 'success'" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <svg v-else-if="alert.type === 'error'" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9.75 9.75l4.5 4.5m0-4.5l-4.5 4.5M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <svg v-else-if="alert.type === 'warning'" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
            </svg>
            <svg v-else-if="alert.type === 'info'" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z" />
            </svg>
          </div>
          <div class="alert-content">
            <p class="alert-message">{{ alert.message }}</p>
          </div>
          <button class="alert-close" @click.stop="handleRemove(alert.id)" title="Close">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<script setup>
import { useAlert } from '../composables/useAlert'

const { alerts, removeAlert } = useAlert()

function handleRemove(id) {
  removeAlert(id)
}
</script>

<style scoped>
.alert-container {
  position: fixed;
  top: 70px; /* Below navbar (60px) + spacing */
  right: 20px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 10px;
  pointer-events: none;
}

.alert-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  min-width: 320px;
  max-width: 480px;
  padding: 16px;
  background: var(--bg-primary);
  border-radius: var(--radius-md);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15), 0 0 0 1px rgba(0, 0, 0, 0.05);
  cursor: pointer;
  pointer-events: auto;
  transition: all 0.2s ease;
  border-left: 4px solid currentColor;
}

.alert-item:hover {
  transform: translateX(-4px);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.2), 0 0 0 1px rgba(0, 0, 0, 0.05);
}

.alert-icon {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
}

.alert-icon svg {
  width: 100%;
  height: 100%;
}

.alert-content {
  flex: 1;
  min-width: 0;
}

.alert-message {
  margin: 0;
  font-size: var(--font-size-sm);
  line-height: 1.5;
  color: var(--text-primary);
  word-wrap: break-word;
}

.alert-close {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  padding: 0;
  background: none;
  border: none;
  cursor: pointer;
  color: var(--text-tertiary);
  transition: color 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: center;
}

.alert-close:hover {
  color: var(--text-primary);
}

.alert-close svg {
  width: 100%;
  height: 100%;
}

/* Alert type styles */
.alert-success {
  color: var(--color-success);
  background: var(--color-success-light);
  border-left-color: var(--color-success);
}

.alert-error {
  color: var(--color-danger);
  background: var(--color-danger-light);
  border-left-color: var(--color-danger);
}

.alert-warning {
  color: var(--color-warning);
  background: var(--color-warning-light);
  border-left-color: var(--color-warning);
}

.alert-info {
  color: var(--color-info);
  background: var(--color-info-light);
  border-left-color: var(--color-info);
}

/* Transitions */
.alert-enter-active,
.alert-leave-active {
  transition: all 0.3s ease;
}

.alert-enter-from {
  opacity: 0;
  transform: translateX(100%);
}

.alert-leave-to {
  opacity: 0;
  transform: translateX(100%) scale(0.95);
}

.alert-move {
  transition: transform 0.3s ease;
}

/* Responsive */
@media (max-width: 640px) {
  .alert-container {
    left: 10px;
    right: 10px;
    top: 65px;
  }
  
  .alert-item {
    min-width: auto;
    max-width: none;
  }
}
</style>

