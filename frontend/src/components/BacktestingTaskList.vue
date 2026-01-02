<template>
  <div class="backtesting-task-list">
    <div v-if="isLoading" class="loading-state">
      Loading tasks...
    </div>
    <div v-else class="tasks-grid">
      <div
        v-for="task in tasks"
        :key="task.id"
        class="task-card"
        :class="{ 
          'selected': selectMode && selectedTasks.includes(task.id),
          'select-mode': selectMode,
          'deleting': deletingTasks.includes(task.id)
        }"
        @click="handleCardClick(task)"
      >
        <!-- Checkbox for select mode -->
        <div v-if="selectMode" class="task-checkbox" @click.stop="toggleTaskSelection(task.id)">
          <input type="checkbox" :checked="selectedTasks.includes(task.id)" />
        </div>

        <!-- Menu button -->
        <div v-if="!selectMode" class="task-menu" @click.stop="toggleMenu(task.id)">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.75a.75.75 0 110-1.5.75.75 0 010 1.5zM12 12.75a.75.75 0 110-1.5.75.75 0 010 1.5zM12 18.75a.75.75 0 110-1.5.75.75 0 010 1.5z" />
          </svg>
          
          <!-- Dropdown menu -->
          <div v-if="openMenuId === task.id" class="dropdown-menu">
            <button class="menu-item" @click="handleTaskClick(task)">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="icon">
                <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
              </svg>
              Open
            </button>
            <button class="menu-item danger" @click="confirmDeleteTask(task)">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="icon">
                <path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
              </svg>
              Delete
            </button>
          </div>
        </div>

        <div class="task-name" :title="task.name">
          {{ task.name }}
        </div>
        <div class="task-details">
          <span class="task-symbol">{{ task.symbol }}</span>
          <span class="task-timeframe">{{ task.timeframe?.toString ? task.timeframe.toString() : task.timeframe }}</span>
        </div>
      </div>
      
      <!-- New task card -->
      <div class="task-card new-task-card" @click="showNewTaskModal = true">
        <div class="new-task-icon">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
        </div>
        <div class="new-task-text">New</div>
      </div>
    </div>
    
    <NewTaskModal
      :is-open="showNewTaskModal"
      @close="showNewTaskModal = false"
      @strategy-created="handleStrategyCreated"
      @task-created="handleTaskCreated"
    />

    <!-- Delete confirmation modal -->
    <div v-if="showDeleteConfirm" class="modal-overlay" @click.self="showDeleteConfirm = false">
      <div class="modal-content">
        <div class="modal-header">
          <h3>Confirm Deletion</h3>
        </div>
        <div class="modal-body">
          <p v-if="taskToDelete">
            Are you sure you want to delete task <strong>{{ taskToDelete.name }}</strong>?
          </p>
          <p v-else-if="selectedTasks.length > 0">
            Are you sure you want to delete <strong>{{ selectedTasks.length }}</strong> task{{ selectedTasks.length > 1 ? 's' : '' }}?
          </p>
          <p class="warning-text">This action cannot be undone.</p>
        </div>
        <div class="modal-actions">
          <button class="btn btn-cancel" @click="showDeleteConfirm = false">
            Cancel
          </button>
          <button class="btn btn-danger" @click="executeDelete" :disabled="isDeleting">
            {{ isDeleting ? 'Deleting...' : 'Delete' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { backtestingApi } from '../services/backtestingApi'
import NewTaskModal from './NewTaskModal.vue'

export default {
  name: 'BacktestingTaskList',
  components: {
    NewTaskModal
  },
  props: {
    selectMode: {
      type: Boolean,
      default: false
    }
  },
  emits: ['strategy-created', 'task-selected', 'selection-changed'],
  data() {
    return {
      tasks: [],
      isLoading: false,
      showNewTaskModal: false,
      selectedTasks: [],
      openMenuId: null,
      showDeleteConfirm: false,
      taskToDelete: null,
      isDeleting: false,
      deletingTasks: []
    }
  },
  watch: {
    selectMode(newValue) {
      if (!newValue) {
        // Clear selection when exiting select mode
        this.selectedTasks = []
        this.$emit('selection-changed', [])
      }
    }
  },
  mounted() {
    this.loadTasks()
    // Close menu when clicking outside
    document.addEventListener('click', this.closeMenu)
  },
  beforeUnmount() {
    document.removeEventListener('click', this.closeMenu)
  },
  methods: {
    async loadTasks() {
      this.isLoading = true
      try {
        this.tasks = await backtestingApi.getTasks()
      } catch (error) {
        console.error('Failed to load backtesting tasks:', error)
      } finally {
        this.isLoading = false
      }
    },
    handleCardClick(task) {
      if (this.selectMode) {
        this.toggleTaskSelection(task.id)
      } else {
        this.handleTaskClick(task)
      }
    },
    handleTaskClick(task) {
      this.$emit('task-selected', task)
    },
    toggleMenu(taskId) {
      this.openMenuId = this.openMenuId === taskId ? null : taskId
    },
    closeMenu() {
      this.openMenuId = null
    },
    toggleTaskSelection(taskId) {
      const index = this.selectedTasks.indexOf(taskId)
      if (index > -1) {
        this.selectedTasks.splice(index, 1)
      } else {
        this.selectedTasks.push(taskId)
      }
      this.$emit('selection-changed', this.selectedTasks)
    },
    cancelSelection() {
      this.selectedTasks = []
      this.$emit('selection-changed', [])
    },
    confirmDeleteTask(task) {
      this.taskToDelete = task
      this.showDeleteConfirm = true
      this.closeMenu()
    },
    confirmDeleteSelected() {
      if (this.selectedTasks.length > 0) {
        this.taskToDelete = null
        this.showDeleteConfirm = true
      }
    },
    // Public method to trigger delete from parent
    deleteSelected() {
      this.confirmDeleteSelected()
    },
    async executeDelete() {
      this.isDeleting = true
      
      try {
        if (this.taskToDelete) {
          // Delete single task
          this.deletingTasks.push(this.taskToDelete.id)
          await this.deleteTaskWithAnimation(this.taskToDelete.id)
        } else {
          // Delete multiple tasks
          this.deletingTasks = [...this.selectedTasks]
          for (const taskId of this.selectedTasks) {
            await this.deleteTaskWithAnimation(taskId)
          }
          this.cancelSelection()
        }
      } catch (error) {
        console.error('Failed to delete task(s):', error)
      } finally {
        this.isDeleting = false
        this.showDeleteConfirm = false
        this.taskToDelete = null
        this.deletingTasks = []
      }
    },
    async deleteTaskWithAnimation(taskId) {
      // Wait for animation
      await new Promise(resolve => setTimeout(resolve, 300))
      
      // Delete from server
      await backtestingApi.deleteTask(taskId)
      
      // Remove from local list
      this.tasks = this.tasks.filter(t => t.id !== taskId)
    },
    handleStrategyCreated(strategyName) {
      this.$emit('strategy-created', strategyName)
    },
    handleTaskCreated(task) {
      this.loadTasks()
      this.$emit('task-selected', task)
    }
  }
}
</script>

<style scoped>
.backtesting-task-list {
  width: 100%;
  height: 100%;
  background-color: var(--bg-primary);
  padding: var(--spacing-lg);
  overflow-y: auto;
}

.tasks-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
  gap: var(--spacing-md);
  padding: var(--spacing-xs);
}

.task-card {
  position: relative;
  padding: var(--spacing-md);
  background-color: var(--bg-secondary);
  border: 1px solid var(--border-color-light);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-base);
  min-height: 5rem;
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
}

.task-card.deleting {
  animation: deleteCard 0.3s ease-out forwards;
}

@keyframes deleteCard {
  0% {
    opacity: 1;
    transform: scale(1);
  }
  100% {
    opacity: 0;
    transform: scale(0.8);
  }
}

.task-card:hover:not(.select-mode) {
  background-color: var(--bg-hover);
  border-color: var(--color-primary);
  box-shadow: var(--shadow-md);
  transform: translateY(-0.0625rem);
}

.task-card.selected {
  border-color: var(--color-primary);
  background-color: var(--color-primary-lighter);
}

.task-checkbox {
  position: absolute;
  top: var(--spacing-sm);
  left: var(--spacing-sm);
  z-index: 1;
}

.task-checkbox input[type="checkbox"] {
  width: var(--spacing-lg);
  height: var(--spacing-lg);
  cursor: pointer;
}

.task-menu {
  position: absolute;
  top: var(--spacing-sm);
  right: var(--spacing-sm);
  width: var(--spacing-2xl);
  height: var(--spacing-2xl);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--spacing-xs);
  border-radius: var(--radius-sm);
  color: var(--text-tertiary);
  opacity: 0;
  transition: all var(--transition-base);
  cursor: pointer;
}

.task-card:hover .task-menu {
  opacity: 1;
}

.task-menu:hover {
  background-color: var(--bg-tertiary);
  color: var(--text-primary);
}

.task-menu svg {
  width: var(--spacing-lg);
  height: var(--spacing-lg);
}

.dropdown-menu {
  position: absolute;
  top: 100%;
  right: 0;
  margin-top: var(--spacing-xs);
  min-width: 9rem;
  background-color: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
  z-index: 10;
  overflow: hidden;
}

.menu-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  padding: var(--spacing-sm) var(--spacing-md);
  font-size: var(--font-size-sm);
  color: var(--text-primary);
  background: none;
  border: none;
  cursor: pointer;
  transition: background-color var(--transition-base);
  text-align: left;
}

.menu-item:hover {
  background-color: var(--bg-hover);
}

.menu-item.danger {
  color: var(--color-danger);
}

.menu-item.danger:hover {
  background-color: rgba(239, 68, 68, 0.1);
}

.menu-item .icon {
  width: var(--spacing-lg);
  height: var(--spacing-lg);
}

.task-name {
  font-weight: var(--font-weight-semibold);
  font-size: var(--font-size-sm);
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 20ch;
}

.task-details {
  display: flex;
  gap: var(--spacing-sm);
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
}

.task-symbol {
  font-weight: var(--font-weight-medium);
}

.task-timeframe {
  opacity: 0.8;
}

.loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  color: var(--text-tertiary);
  font-size: var(--font-size-sm);
}

.new-task-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--spacing-sm);
  border: 2px dashed var(--border-color-dark);
  background-color: transparent;
}

.new-task-card:hover {
  border-color: var(--color-primary);
  background-color: var(--color-primary-lighter);
}

.new-task-icon {
  width: var(--spacing-2xl);
  height: var(--spacing-2xl);
  color: var(--text-tertiary);
}

.new-task-card:hover .new-task-icon {
  color: var(--color-primary);
}

.new-task-icon svg {
  width: 100%;
  height: 100%;
}

.new-task-text {
  font-weight: var(--font-weight-medium);
  font-size: var(--font-size-sm);
  color: var(--text-tertiary);
}

.new-task-card:hover .new-task-text {
  color: var(--color-primary);
}

/* Modal styles */
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
  max-width: 32rem;
  display: flex;
  flex-direction: column;
}

.modal-header {
  padding: var(--spacing-lg);
  border-bottom: 1px solid var(--border-color);
}

.modal-header h3 {
  margin: 0;
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
}

.modal-body {
  padding: var(--spacing-lg);
}

.modal-body p {
  margin: 0 0 var(--spacing-md) 0;
  color: var(--text-secondary);
}

.warning-text {
  font-size: var(--font-size-sm);
  color: var(--text-tertiary);
  font-style: italic;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--spacing-md);
  padding: var(--spacing-lg);
  border-top: 1px solid var(--border-color);
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

.btn-danger {
  color: white;
  background-color: var(--color-danger);
}

.btn-danger:hover:not(:disabled) {
  background-color: var(--color-danger-hover);
}

.btn-danger:disabled {
  color: var(--color-white);
  background-color: var(--color-gray-400);
  opacity: 0.7;
}
</style>
