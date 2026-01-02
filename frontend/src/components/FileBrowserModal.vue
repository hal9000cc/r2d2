<template>
  <div v-if="isOpen" class="modal-overlay" @click.self="handleClose">
    <div class="modal-content file-browser-modal" @click.stop>
      <div class="modal-header">
        <h3>Select Strategy File</h3>
        <button class="close-btn" @click="handleClose" title="Close">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="icon">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
      
      <div class="modal-body">
        <!-- Current path display -->
        <div class="path-display">
          <button
            v-if="parentPath"
            class="path-btn"
            @click="navigateToPath(parentPath)"
            title="Go to parent directory"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="icon">
              <path stroke-linecap="round" stroke-linejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
            </svg>
          </button>
          <span class="current-path">{{ currentPath || 'Root' }}</span>
        </div>

        <!-- Loading state -->
        <div v-if="isLoading" class="loading-state">
          <p>Loading...</p>
        </div>

        <!-- Error state -->
        <div v-if="error" class="error-message">
          {{ error }}
        </div>

        <!-- File list -->
        <div v-if="!isLoading && !error" class="file-list">
          <div
            v-for="item in items"
            :key="item.name"
            class="file-item"
            :class="{ 'is-directory': item.type === 'directory', 'is-file': item.type === 'file' }"
            @click="handleItemClick(item)"
          >
            <svg
              v-if="item.type === 'directory'"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              stroke-width="1.5"
              stroke="currentColor"
              class="item-icon"
            >
              <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 12.75V12A2.25 2.25 0 014.25 10h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.25A2.25 2.25 0 002 7.5v9A2.25 2.25 0 004.25 19h15A2.25 2.25 0 0021.75 16.5v-9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 00-1.06.44l-2.122 2.12z" />
            </svg>
            <svg
              v-else
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              stroke-width="1.5"
              stroke="currentColor"
              class="item-icon"
            >
              <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
            </svg>
            <span class="item-name">{{ item.name }}</span>
          </div>

          <div v-if="items.length === 0" class="empty-state">
            <p>No files found</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { strategiesApi } from '../services/strategiesApi'

export default {
  name: 'FileBrowserModal',
  props: {
    isOpen: {
      type: Boolean,
      required: true
    },
    initialPath: {
      type: String,
      default: ''
    }
  },
  emits: ['close', 'file-selected'],
  data() {
    return {
      currentPath: '',
      parentPath: null,
      items: [],
      isLoading: false,
      error: null
    }
  },
  watch: {
    isOpen(newValue) {
      if (newValue) {
        // Load root directory when modal opens
        this.loadFiles(null)
      }
    }
  },
  methods: {
    handleClose() {
      this.$emit('close')
    },
    async loadFiles(path = null) {
      this.isLoading = true
      this.error = null
      
      try {
        const response = await strategiesApi.listFiles(path, '*.py')
        // Normalize current_path: remove "." for root directory, remove leading/trailing slashes
        let currentPath = response.current_path || ''
        if (currentPath === '.' || currentPath === './') {
          currentPath = ''
        }
        currentPath = currentPath.replace(/^\.\/+|\/+$/g, '') // Remove leading "./" and trailing slashes
        this.currentPath = currentPath
        // parent_path can be null or a string - keep it as is
        this.parentPath = response.parent_path
        this.items = response.items
      } catch (error) {
        console.error('Failed to load files:', error)
        this.error = error.message || 'Failed to load files'
        this.items = []
      } finally {
        this.isLoading = false
      }
    },
    navigateToPath(path) {
      this.loadFiles(path)
    },
    handleItemClick(item) {
      if (item.type === 'directory') {
        // Navigate into directory
        const separator = this.currentPath && !this.currentPath.endsWith('/') ? '/' : ''
        const newPath = this.currentPath
          ? `${this.currentPath}${separator}${item.name}`
          : item.name
        this.loadFiles(newPath)
      } else {
        // Select file - return path with .py extension
        // Normalize path: remove any leading "./" or "." 
        let normalizedPath = this.currentPath || ''
        normalizedPath = normalizedPath.replace(/^\.\/+/, '').replace(/^\.$/, '')
        
        const separator = normalizedPath && !normalizedPath.endsWith('/') ? '/' : ''
        const filePath = normalizedPath
          ? `${normalizedPath}${separator}${item.name}`
          : item.name
        // filePath already has .py extension from item.name
        this.$emit('file-selected', filePath)
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
  z-index: calc(var(--z-modal) + 1);
}

.modal-content {
  background-color: var(--bg-primary);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-xl);
  max-width: 90vw;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
}

.file-browser-modal {
  width: 66.67vw;
  min-width: 500px;
  max-width: 1200px;
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
  padding-bottom: 0;
  overflow-y: auto;
  flex: 1;
}

.path-display {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-lg);
  padding: var(--spacing-xs) var(--spacing-md);
  background-color: var(--bg-secondary);
  border-radius: var(--radius-md);
}

.path-btn {
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
  transition: all var(--transition-base);
}

.path-btn:hover {
  background-color: var(--bg-hover);
}

.path-btn .icon {
  width: 18px;
  height: 18px;
  color: var(--text-secondary);
}

.path-btn:hover .icon {
  color: var(--text-primary);
}

.current-path {
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
  font-family: monospace;
  word-break: break-all;
}

.loading-state,
.empty-state {
  text-align: center;
  padding: var(--spacing-2xl);
  color: var(--text-tertiary);
}

.error-message {
  padding: var(--spacing-md);
  margin-bottom: var(--spacing-lg);
  background-color: var(--color-danger-light);
  border-left: var(--spacing-xs) solid var(--color-danger);
  border-radius: var(--radius-md);
  color: var(--color-danger);
  font-size: var(--font-size-sm);
}

.file-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(20rem, 1fr));
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  overflow: hidden;
  margin-bottom: var(--spacing-lg);
}

.file-item {
  display: flex;
  align-items: center;
  gap: var(--spacing-md);
  padding: var(--spacing-md);
  border-right: 1px solid var(--border-color);
  cursor: pointer;
  transition: all var(--transition-base);
  min-width: 0; /* Allows text truncation */
}

/* Remove right border for items that would be at the end of row */
/* Since we can't easily detect last column in dynamic grid, we'll keep all borders */
/* The outer border of .file-list will handle the edge */
.file-item:hover {
  background-color: var(--bg-hover);
}

.file-item.is-directory {
  font-weight: var(--font-weight-medium);
}

.file-item.is-file {
  font-weight: var(--font-weight-normal);
}

.item-icon {
  width: 20px;
  height: 20px;
  color: var(--text-tertiary);
  flex-shrink: 0;
}

.file-item.is-directory .item-icon {
  color: var(--color-info);
}

.file-item.is-file .item-icon {
  color: var(--text-secondary);
}

.item-name {
  font-size: var(--font-size-base);
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0; /* Allows text truncation */
}
</style>
