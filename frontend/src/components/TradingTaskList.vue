<template>
  <div class="trading-task-list">
    <div class="list-header">
      <h3>Tasks</h3>
      <button class="refresh-btn" @click="loadTasks" :disabled="isLoading" title="Refresh task list">
        <ArrowPathIcon class="icon" :class="{ 'spin': isLoading }" />
      </button>
    </div>

    <div v-if="isLoading && tasks.length === 0" class="loading-state">
      Loading tasks...
    </div>

    <div v-else-if="tasks.length === 0" class="empty-state">
      <p>No trading tasks</p>
    </div>

    <div v-else class="task-tree">
      <!-- Ungrouped tasks (single in their group or group_id=0) -->
      <div
        v-for="task in ungroupedTasks"
        :key="task.id"
        class="task-item"
        :class="{ 'selected': selectedTaskId === task.id }"
        @click="selectTask(task)"
      >
        <span class="status-icon" :class="statusClass(task)">
          <PlayIcon v-if="task.isRunning" class="icon" />
          <StopIcon v-else class="icon" />
        </span>
        <div class="task-info">
          <span class="task-name" :title="task.name">{{ task.name }}</span>
          <span class="task-details">{{ task.symbol }} · {{ formatTimeframe(task.timeframe) }}</span>
        </div>
        <button
          v-if="!task.isRunning"
          class="delete-btn"
          @click.stop="confirmDelete(task)"
          title="Delete task"
        >
          <TrashIcon class="icon" />
        </button>
      </div>

      <!-- Grouped tasks -->
      <div
        v-for="group in groupList"
        :key="'group-' + group.groupId"
        class="task-group"
      >
        <div
          class="group-header"
          @click="toggleGroup(group.groupId)"
        >
          <ChevronRightIcon class="icon chevron" :class="{ 'expanded': expandedGroups.has(group.groupId) }" />
          <span class="group-name" :title="group.name">{{ group.name }}</span>
          <span class="group-count">{{ group.tasks.length }}</span>
        </div>
        <div v-if="expandedGroups.has(group.groupId)" class="group-tasks">
          <div
            v-for="task in group.tasks"
            :key="task.id"
            class="task-item grouped"
            :class="{ 'selected': selectedTaskId === task.id }"
            @click="selectTask(task)"
          >
            <span class="status-icon" :class="statusClass(task)">
              <PlayIcon v-if="task.isRunning" class="icon" />
              <StopIcon v-else class="icon" />
            </span>
            <div class="task-info">
              <span class="task-name" :title="task.name">{{ task.name }}</span>
              <span class="task-details">{{ task.symbol }} · {{ formatTimeframe(task.timeframe) }}</span>
            </div>
            <button
              v-if="!task.isRunning"
              class="delete-btn"
              @click.stop="confirmDelete(task)"
              title="Delete task"
            >
              <TrashIcon class="icon" />
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Delete confirmation dialog -->
    <div v-if="taskToDelete" class="confirm-overlay" @click.self="taskToDelete = null">
      <div class="confirm-dialog">
        <p>Delete task <strong>{{ taskToDelete.name }}</strong>?</p>
        <p class="confirm-details">{{ taskToDelete.symbol }} · {{ formatTimeframe(taskToDelete.timeframe) }}</p>
        <div class="confirm-actions">
          <button class="btn btn-cancel" @click="taskToDelete = null">Cancel</button>
          <button class="btn btn-danger" @click="executeDelete" :disabled="isDeleting">
            {{ isDeleting ? 'Deleting...' : 'Delete' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { PlayIcon, StopIcon, ArrowPathIcon, ChevronRightIcon, TrashIcon } from '@heroicons/vue/24/outline'
import { tradingApi } from '../services/tradingApi'

const props = defineProps({
  selectedTaskId: {
    type: Number,
    default: null
  }
})

const emit = defineEmits(['task-selected', 'task-deleted'])

const tasks = ref([])
const groups = ref({})
const isLoading = ref(false)
const isDeleting = ref(false)
const expandedGroups = ref(new Set())
const taskToDelete = ref(null)

// Tasks that are alone in their group (count <= 1) — shown flat
const ungroupedTasks = computed(() => {
  return tasks.value.filter(t => {
    const gid = t.group_id
    if (!gid || gid === 0) return true
    // If this group_id has metadata in groups → it has >1 task → grouped
    return !(String(gid) in groups.value)
  })
})

// Groups with >1 task
const groupList = computed(() => {
  const result = []
  for (const [gid, meta] of Object.entries(groups.value)) {
    const groupTasks = tasks.value.filter(t => t.group_id === Number(gid))
    if (groupTasks.length > 0) {
      result.push({
        groupId: Number(gid),
        name: meta.name,
        tasks: groupTasks
      })
    }
  }
  return result
})

function statusClass(task) {
  if (task.isRunning) return 'status-running'
  return 'status-stopped'
}

function formatTimeframe(tf) {
  if (!tf) return ''
  if (typeof tf === 'object' && tf.name) return tf.name
  return String(tf)
}

function toggleGroup(groupId) {
  const s = new Set(expandedGroups.value)
  if (s.has(groupId)) {
    s.delete(groupId)
  } else {
    s.add(groupId)
  }
  expandedGroups.value = s
}

function selectTask(task) {
  emit('task-selected', task)
}

function confirmDelete(task) {
  taskToDelete.value = task
}

async function executeDelete() {
  if (!taskToDelete.value) return
  const task = taskToDelete.value
  isDeleting.value = true
  try {
    await tradingApi.deleteTask(task.id)
    taskToDelete.value = null
    emit('task-deleted', task.id)
    await loadTasks()
  } catch (error) {
    console.error('Failed to delete trading task:', error)
  } finally {
    isDeleting.value = false
  }
}

async function loadTasks() {
  isLoading.value = true
  try {
    const data = await tradingApi.getTasks()
    tasks.value = data.tasks || []
    groups.value = data.groups || {}
  } catch (error) {
    console.error('Failed to load trading tasks:', error)
  } finally {
    isLoading.value = false
  }
}

function getTaskById(id) {
  return tasks.value.find(t => t.id === id) || null
}

defineExpose({ loadTasks, getTaskById })

loadTasks()
</script>

<style scoped>
.trading-task-list {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--spacing-sm) var(--spacing-sm) var(--spacing-xs);
  flex-shrink: 0;
}

.list-header h3 {
  margin: 0;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
}

.refresh-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: none;
  border-radius: var(--radius-sm);
  background: none;
  color: var(--text-tertiary);
  cursor: pointer;
  transition: all var(--transition-base);
}

.refresh-btn:hover:not(:disabled) {
  color: var(--text-primary);
  background-color: var(--bg-hover);
}

.refresh-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.refresh-btn .icon {
  width: 14px;
  height: 14px;
}

.refresh-btn .icon.spin {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.loading-state,
.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  color: var(--text-muted);
  font-size: var(--font-size-xs);
}

.task-tree {
  flex: 1;
  overflow-y: auto;
  padding: 0 var(--spacing-xs) var(--spacing-xs);
}

/* Task item */
.task-item {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  padding: var(--spacing-xs) var(--spacing-sm);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background-color var(--transition-base);
  user-select: none;
}

.task-item.grouped {
  padding-left: calc(var(--spacing-sm) + 18px);
}

.task-item:hover {
  background-color: var(--bg-hover);
}

.task-item.selected {
  background-color: var(--color-primary-lighter);
}

/* Status icon */
.status-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 16px;
  height: 16px;
}

.status-icon .icon {
  width: 12px;
  height: 12px;
}

.status-icon.status-running {
  color: var(--color-success);
}

.status-icon.status-stopped {
  color: var(--text-muted);
}

/* Task info */
.task-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.task-name {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-details {
  font-size: 10px;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Group */
.task-group {
  margin-top: var(--spacing-xs);
}

.group-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  padding: var(--spacing-xs) var(--spacing-sm);
  border-radius: var(--radius-sm);
  cursor: pointer;
  user-select: none;
  transition: background-color var(--transition-base);
}

.group-header:hover {
  background-color: var(--bg-hover);
}

.group-header .chevron {
  width: 14px;
  height: 14px;
  color: var(--text-tertiary);
  transition: transform var(--transition-base);
  flex-shrink: 0;
}

.group-header .chevron.expanded {
  transform: rotate(90deg);
}

.group-name {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.group-count {
  flex-shrink: 0;
  font-size: 10px;
  color: var(--text-muted);
  background-color: var(--bg-tertiary);
  padding: 1px 6px;
  border-radius: 8px;
  margin-left: auto;
}

.group-tasks {
  margin-top: 1px;
}

/* Delete button */
.delete-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  padding: 0;
  margin-left: auto;
  flex-shrink: 0;
  border: none;
  border-radius: var(--radius-sm);
  background: none;
  color: var(--text-muted);
  cursor: pointer;
  opacity: 0;
  transition: all var(--transition-base);
}

.task-item:hover .delete-btn {
  opacity: 1;
}

.delete-btn:hover {
  color: var(--color-danger);
  background-color: var(--color-danger-light);
}

.delete-btn .icon {
  width: 12px;
  height: 12px;
}

/* Confirm dialog */
.confirm-overlay {
  position: fixed;
  inset: 0;
  background-color: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.confirm-dialog {
  background-color: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
  padding: var(--spacing-lg);
  min-width: 280px;
  max-width: 400px;
}

.confirm-dialog p {
  margin: 0 0 var(--spacing-xs);
  font-size: var(--font-size-sm);
  color: var(--text-primary);
}

.confirm-details {
  color: var(--text-muted) !important;
  font-size: var(--font-size-xs) !important;
  margin-bottom: var(--spacing-md) !important;
}

.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--spacing-sm);
}

.btn {
  padding: var(--spacing-xs) var(--spacing-md);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  transition: all var(--transition-base);
}

.btn-cancel {
  background-color: var(--bg-secondary);
  color: var(--text-primary);
}

.btn-cancel:hover {
  background-color: var(--bg-hover);
}

.btn-danger {
  background-color: var(--color-danger);
  color: white;
  border-color: var(--color-danger);
}

.btn-danger:hover:not(:disabled) {
  background-color: var(--color-danger-hover);
}

.btn-danger:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>

