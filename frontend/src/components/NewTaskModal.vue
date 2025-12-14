<template>
  <div v-if="isOpen" class="modal-overlay" @click.self="handleClose">
    <div class="modal-content" @click.stop>
      <div class="modal-header">
        <h3>Create New Task</h3>
        <button class="close-btn" @click="handleClose" title="Close">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="icon">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
      <div class="modal-body">
        <form @submit.prevent="handleCreate">
          <div class="form-group">
            <label for="strategy-name" class="form-label">Strategy Name</label>
            <input
              id="strategy-name"
              ref="nameInput"
              v-model="strategyName"
              type="text"
              class="form-input"
              placeholder="Enter strategy name..."
              required
            />
          </div>
          
          <div class="form-group">
            <label for="strategy-file" class="form-label">Strategy File</label>
            <div class="file-input-wrapper">
              <input
                id="strategy-file"
                v-model="strategyFile"
                type="text"
                class="form-input"
                placeholder="path/strategy_name"
                required
              />
              <span class="file-extension">.py</span>
              <button
                type="button"
                class="file-open-btn"
                @click="openFileBrowser"
                title="Browse files"
              >
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="icon">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.75a.75.75 0 110-1.5.75.75 0 010 1.5zM12 12.75a.75.75 0 110-1.5.75.75 0 010 1.5zM12 18.75a.75.75 0 110-1.5.75.75 0 010 1.5z" />
                </svg>
              </button>
            </div>
          </div>
          
          <div v-if="error" class="error-message">
            {{ error }}
          </div>
          
          <div class="modal-actions">
            <button type="button" class="btn btn-cancel" @click="handleClose">
              Cancel
            </button>
            <button type="submit" class="btn btn-primary" :disabled="!strategyName.trim() || isCreating">
              {{ isCreating ? 'Creating...' : 'Create' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <FileBrowserModal
      :is-open="showFileBrowser"
      :initial-path="strategyFile"
      @close="showFileBrowser = false"
      @file-selected="handleFileSelected"
    />
  </div>
</template>

<script>
import { strategiesApi } from '../services/strategiesApi'
import { backtestingApi } from '../services/backtestingApi'
import FileBrowserModal from './FileBrowserModal.vue'

export default {
  name: 'NewTaskModal',
  components: {
    FileBrowserModal
  },
  props: {
    isOpen: {
      type: Boolean,
      required: true
    }
  },
  emits: ['close', 'created', 'task-created'],
  data() {
    return {
      strategyName: '',
      strategyFile: '',
      defaultFolder: 'path/',
      isSynced: true,
      isCreating: false,
      error: null,
      showFileBrowser: false
    }
  },
  watch: {
    async isOpen(newValue) {
      if (newValue) {
        // Reset form when modal opens
        this.strategyName = ''
        this.isSynced = true
        this.error = null
        this.isCreating = false
        
        // Load strategies directory path from backend
        try {
          this.defaultFolder = await strategiesApi.getStrategiesDirectory()
          this.strategyFile = this.defaultFolder
        } catch (error) {
          console.error('Failed to load strategies directory:', error)
          // Fallback to default if request fails
          this.defaultFolder = 'path/'
          this.strategyFile = this.defaultFolder
        }
        
        // Focus input field after DOM update
        this.$nextTick(() => {
          if (this.$refs.nameInput) {
            this.$refs.nameInput.focus()
          }
        })
      }
    },
    strategyName(newValue) {
      // Sync file path if synced mode is active
      if (this.isSynced) {
        this.strategyFile = this.defaultFolder + newValue
      }
    },
    strategyFile(newValue) {
      // Check if file path matches expected pattern
      const expectedPath = this.defaultFolder + this.strategyName
      this.isSynced = (newValue === expectedPath)
    }
  },
  methods: {
    handleClose() {
      if (!this.isCreating) {
        this.$emit('close')
      }
    },
    openFileBrowser() {
      this.showFileBrowser = true
    },
    handleFileSelected(filePath) {
      // filePath already comes without .py extension from FileBrowserModal
      this.strategyFile = filePath
      
      // Extract filename from path and fill strategy name if empty
      if (!this.strategyName.trim()) {
        const lastSeparator = Math.max(
          filePath.lastIndexOf('/'),
          filePath.lastIndexOf('\\')
        )
        let fileName = lastSeparator >= 0 
          ? filePath.substring(lastSeparator + 1)
          : filePath
        // Remove .py extension if present (shouldn't be, but just in case)
        if (fileName.endsWith('.py')) {
          fileName = fileName.slice(0, -3)
        }
        this.strategyName = fileName
      }
      
      // Update sync state - if path matches expected pattern, enable sync
      const expectedPath = this.defaultFolder + this.strategyName
      this.isSynced = (this.strategyFile === expectedPath)
    },
    async handleCreate() {
      if (!this.strategyName.trim() || this.isCreating) {
        return
      }
      
      this.isCreating = true
      this.error = null
      
      try {
        const strategyName = this.strategyName.trim()
        const strategyFile = this.strategyFile.trim()
        
        // Extract file path from strategyFile (remove .py if present)
        let filePath = strategyFile.trim()
        if (filePath.endsWith('.py')) {
          filePath = filePath.slice(0, -3)
        }
        // Normalize path separators to forward slashes
        filePath = filePath.replace(/\\/g, '/')
        
        // If path doesn't start with defaultFolder, prepend it to make it absolute
        if (!filePath.startsWith(this.defaultFolder)) {
          // Remove leading slashes from filePath
          const cleanPath = filePath.replace(/^\/+/, '')
          // Ensure defaultFolder ends with /
          const baseFolder = this.defaultFolder.endsWith('/') ? this.defaultFolder : this.defaultFolder + '/'
          filePath = baseFolder + cleanPath
        }
        
        // Remove trailing slashes
        filePath = filePath.replace(/\/+$/, '')
        
        // Extract relative path from absolute path for strategy identifier
        let relativePath = filePath
        if (relativePath.startsWith(this.defaultFolder)) {
          relativePath = relativePath.substring(this.defaultFolder.length)
          relativePath = relativePath.replace(/^\/+/, '')
        }
        
        // Determine strategy identifier:
        // - If path was manually edited (not synced) and is different from strategyName, use the relative path
        // - Otherwise use strategyName
        let strategyIdentifier = (!this.isSynced && relativePath && relativePath !== strategyName) ? relativePath : strategyName
        
        // 1. Check if strategy file exists, create only if it doesn't
        let strategyExists = false
        let existingStrategy = null
        try {
          existingStrategy = await strategiesApi.loadStrategy(strategyIdentifier)
          strategyExists = true
          // Use the strategy name from loaded strategy (which contains the correct relative path)
          if (existingStrategy && existingStrategy.name) {
            strategyIdentifier = existingStrategy.name
          }
        } catch (loadError) {
          // Check if it's a 404 (not found) error
          const isNotFound = loadError.message && (
            loadError.message.includes('404') || 
            loadError.message.includes('not found') ||
            loadError.message.includes('Not Found')
          )
          if (!isNotFound) {
            // Other error, rethrow
            throw loadError
          }
          // Strategy doesn't exist, will create it below
        }
        
        // Create strategy only if it doesn't exist
        // Use absolute filePath if path was manually edited (not synced) and is different from strategyName
        if (!strategyExists) {
          const pathToUse = (!this.isSynced && filePath && relativePath !== strategyName && filePath.length > 0) ? filePath : null
          const createdStrategy = await strategiesApi.createStrategy(strategyName, pathToUse)
          // Use the strategy name from API response (which contains the correct relative path)
          if (createdStrategy && createdStrategy.name) {
            strategyIdentifier = createdStrategy.name
          }
        }
        
        // 2. Create backtesting task with this strategy
        // Use strategyIdentifier (relative path from STRATEGIES_DIR) as strategy_id
        const taskData = {
          strategy_id: strategyIdentifier,
          name: strategyName
        }
        const createdTask = await backtestingApi.createTask(taskData)
        
        // Emit events
        // Use strategyIdentifier for loading the strategy
        this.$emit('strategy-created', strategyIdentifier)
        this.$emit('task-created', createdTask)
        
        // Close modal
        this.$emit('close')
      } catch (error) {
        console.error('Failed to create strategy and task:', error)
        
        // Handle errors from both fetch (strategiesApi) and axios (backtestingApi)
        let errorMessage = 'Failed to create strategy. Please try again.'
        
        if (error.response) {
          // Axios error with response (from backtestingApi)
          const status = error.response.status
          const data = error.response.data || {}
          const detail = data.detail || data.message
          
          if (status === 409) {
            // Conflict - task already exists
            errorMessage = detail || `A task with strategy "${strategyName}" already exists. Please use a different strategy name.`
          } else {
            errorMessage = detail || error.message || `HTTP error! status: ${status}`
          }
        } else if (error.message) {
          // Fetch error (from strategiesApi) or regular error
          // Fetch errors from strategiesApi contain the detail in error.message
          if (error.message.includes('409') || error.message.includes('already exists')) {
            errorMessage = `A task with strategy "${strategyName}" already exists. Please use a different strategy name.`
          } else {
            // Use the error message directly (it should contain the detail from backend)
            errorMessage = error.message
          }
        }
        
        this.error = errorMessage
      } finally {
        this.isCreating = false
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
  width: 90%;
  max-width: 600px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--spacing-lg);
  border-bottom: 1px solid var(--border-color);
}

.modal-header h3 {
  margin: 0;
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
}

.close-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border: none;
  border-radius: var(--radius-md);
  background-color: transparent;
  cursor: pointer;
  transition: background-color var(--transition-base);
}

.close-btn:hover {
  background-color: var(--bg-hover);
}

.close-btn .icon {
  width: 20px;
  height: 20px;
  color: var(--text-tertiary);
}

.close-btn:hover .icon {
  color: var(--text-primary);
}

.modal-body {
  padding: var(--spacing-lg);
  overflow-y: auto;
}

.form-group {
  margin-bottom: var(--spacing-lg);
}

.form-label {
  display: block;
  margin-bottom: var(--spacing-sm);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--text-secondary);
}

.form-input {
  width: 100%;
  padding: var(--spacing-md);
  font-size: var(--font-size-base);
  color: var(--text-primary);
  background-color: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  transition: all var(--transition-base);
}

.form-input:focus {
  outline: none;
  border-color: var(--color-primary);
  background-color: var(--bg-primary);
}

.form-input::placeholder {
  color: var(--text-tertiary);
}

.file-input-wrapper {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
}

.file-input-wrapper .form-input {
  flex: 1;
}

.file-extension {
  font-size: var(--font-size-base);
  color: var(--text-secondary);
  font-weight: var(--font-weight-medium);
  white-space: nowrap;
}

.file-open-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  color: var(--text-secondary);
  background-color: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-base);
}

.file-open-btn:hover {
  background-color: var(--bg-tertiary);
  border-color: var(--color-primary);
  color: var(--text-primary);
}

.file-open-btn .icon {
  width: 18px;
  height: 18px;
}

.error-message {
  padding: var(--spacing-md);
  margin-bottom: var(--spacing-lg);
  background-color: rgba(239, 68, 68, 0.1);
  border-left: 3px solid var(--color-danger);
  border-radius: var(--radius-md);
  color: var(--color-danger);
  font-size: var(--font-size-sm);
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--spacing-md);
  margin-top: var(--spacing-lg);
}

.btn {
  padding: var(--spacing-md) var(--spacing-xl);
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-medium);
  border: none;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-base);
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-cancel {
  color: var(--text-secondary);
  background-color: var(--bg-secondary);
}

.btn-cancel:hover:not(:disabled) {
  background-color: var(--bg-tertiary);
  color: var(--text-primary);
}

.btn-primary {
  color: white;
  background-color: var(--color-primary);
}

.btn-primary:hover:not(:disabled) {
  background-color: var(--color-primary-hover);
}

.placeholder-text {
  text-align: center;
  color: var(--text-tertiary);
  font-size: var(--font-size-sm);
  margin: var(--spacing-2xl) 0;
}
</style>
