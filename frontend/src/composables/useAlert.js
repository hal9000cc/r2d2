import { ref, readonly } from 'vue'

// Global state for alerts (shared across all components)
const alerts = ref([])
let alertIdCounter = 0

/**
 * Composable for managing application-wide alerts/toasts
 * 
 * @returns {Object} Alert state and methods
 */
export function useAlert() {
  /**
   * Show an alert
   * @param {string} type - Alert type: 'success' | 'error' | 'warning' | 'info'
   * @param {string} message - Alert message
   * @param {number} duration - Duration in milliseconds (0 = no auto-dismiss)
   * @returns {number} Alert ID
   */
  function showAlert(type, message, duration = 5000) {
    const id = ++alertIdCounter
    const alert = {
      id,
      type,
      message,
      timestamp: new Date().toISOString()
    }
    
    alerts.value.push(alert)
    
    // Auto-dismiss after duration (if duration > 0)
    if (duration > 0) {
      setTimeout(() => {
        removeAlert(id)
      }, duration)
    }
    
    return id
  }
  
  /**
   * Remove an alert by ID
   * @param {number} id - Alert ID
   */
  function removeAlert(id) {
    const index = alerts.value.findIndex(alert => alert.id === id)
    if (index !== -1) {
      alerts.value.splice(index, 1)
    }
  }
  
  /**
   * Clear all alerts
   */
  function clearAllAlerts() {
    alerts.value = []
  }
  
  /**
   * Shortcut methods for common alert types
   */
  function success(message, duration = 3000) {
    return showAlert('success', message, duration)
  }
  
  function error(message, duration = 5000) {
    return showAlert('error', message, duration)
  }
  
  function warning(message, duration = 4000) {
    return showAlert('warning', message, duration)
  }
  
  function info(message, duration = 3000) {
    return showAlert('info', message, duration)
  }
  
  return {
    // State (readonly to prevent direct modification)
    alerts: readonly(alerts),
    
    // Methods
    showAlert,
    removeAlert,
    clearAllAlerts,
    
    // Shortcuts
    success,
    error,
    warning,
    info
  }
}

