<template>
  <div class="backtesting-view">
    <!-- Teleport form to navbar -->
    <Teleport to="#navbar-content-slot">
      <BacktestingNavForm 
        ref="navFormRef" 
        :disabled="buttonDisabled"
        :is-running="isBacktestingRunning"
        @start="handleStart"
        @stop="handleStop"
        @form-data-changed="handleFormDataChanged"
      />
    </Teleport>

    <!-- Backtest progress bar -->
    <div v-if="backtestProgressState !== 'idle'" class="backtest-progress" :class="{ 'error-state': backtestProgressState === 'error' }">
      <div class="progress-text">
        <span v-if="backtestProgressState === 'running'">
          Backtesting: {{ backtestProgress.toFixed(1) }}%
        </span>
        <span v-else-if="backtestProgressState === 'completed'">
          Backtesting completed
        </span>
        <span v-else-if="backtestProgressState === 'error'" class="error-message">
          {{ errorDisplayMessage }}
        </span>
      </div>
      <div class="progress-bar">
        <div
          class="progress-bar-fill"
          :style="{ width: backtestProgress + '%' }"
        ></div>
      </div>
    </div>

    <div class="backtesting-layout">
      <!-- Left side: Chart and Tabs -->
      <div class="left-panel">
        <ResizablePanel
          v-if="chartHeight !== null"
          direction="vertical"
          :min-size="150"
          :max-size="chartMaxHeight"
          :default-size="chartHeight"
          storage-key="backtesting-chart-panel-height"
          @resize="handleChartResize"
        >
          <Tabs
            :tabs="chartTabs"
            default-tab="strategy"
            :strategy-name="currentStrategyName || ''"
            @tab-change="handleChartTabChange"
            @close-strategy="handleCloseStrategy"
          >
            <template #header-actions>
              <div v-if="activeChartTab === 'strategy' && currentStrategyFilePath && isStrategyLoaded" class="header-actions">
                <button 
                  class="header-btn save-btn" 
                  @click="handleSaveStrategy"
                  :disabled="isSavingStrategy || !hasUnsavedChanges"
                  :title="isMac ? 'Save (⌘S)' : 'Save (Ctrl+S)'"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="icon">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                  </svg>
                  {{ isSavingStrategy ? 'Saving...' : 'Save' }}
                </button>
              </div>
              <div v-if="activeChartTab === 'strategy' && !currentStrategyFilePath" class="header-actions">
                <button 
                  v-if="!selectMode" 
                  class="header-btn" 
                  @click="selectMode = true"
                  title="Select multiple tasks"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="icon">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  Select
                </button>
                
                <template v-if="selectMode">
                  <button class="header-btn" @click="cancelSelection">
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="icon">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                    Cancel
                  </button>
                  <button 
                    class="header-btn danger" 
                    :disabled="selectedTasksCount === 0"
                    @click="deleteSelectedTasks"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="icon">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                    </svg>
                    Delete ({{ selectedTasksCount }})
                  </button>
                </template>
              </div>
            </template>
            
            <template #strategy>
              <BacktestingTaskList
                v-if="activeChartTab === 'strategy' && !currentStrategyFilePath"
                ref="taskList"
                :select-mode="selectMode"
                @strategy-created="handleStrategyCreated"
                @task-selected="handleTaskSelected"
                @selection-changed="handleSelectionChanged"
              />
              <CodeMirrorEditor
                v-if="activeChartTab === 'strategy' && currentStrategyFilePath && isStrategyLoaded"
                v-model="strategyCode"
                language="python"
                :on-save="handleSaveStrategy"
              />
              <div v-if="activeChartTab === 'strategy' && currentStrategyFilePath && !isStrategyLoaded" class="strategy-error">
                <div class="error-icon">⚠️</div>
                <h3>Failed to load strategy</h3>
                <p class="strategy-name">Strategy ID: {{ currentStrategyName }}</p>
                <p v-if="strategyLoadError" class="error-message">{{ strategyLoadError }}</p>
                <p v-else class="error-message">Strategy file not found or cannot be loaded</p>
              </div>
            </template>
            <template #chart>
              <ChartPanel 
                :source="currentTask?.source || null"
                :symbol="currentTask?.symbol || null"
                :timeframe="currentTask?.timeframe || null"
                :backtesting-progress="backtestingProgressData"
                :clear-chart="clearChartFlag" 
                @chart-cleared="clearChartFlag = false"
                @quotes-load-error="handleQuotesLoadError"
                @chart-message="handleChartMessage"
              />
            </template>
          </Tabs>
        </ResizablePanel>
        <Tabs
          :tabs="tabs"
          default-tab="messages"
          @tab-change="handleTabChange"
        >
          <template #header-actions>
            <div v-if="activeTab === 'messages'" class="header-actions">
              <button 
                class="header-btn clear-btn" 
                @click="clearAllMessages"
                :disabled="!hasMessages"
                title="Clear messages"
              >
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="icon">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
                Clear
              </button>
            </div>
          </template>
          <template #messages>
            <MessagesPanel :messages="allMessages" />
          </template>
        </Tabs>
      </div>
      
      <!-- Right side: Parameters and Results -->
      <ResizablePanel
        direction="horizontal"
        handle-side="left"
        :min-size="200"
        :max-size="rightPanelMaxWidth"
        :default-size="rightPanelWidth"
        storage-key="backtesting-right-panel-width"
        @resize="handleRightPanelResize"
      >
        <div class="right-panel">
          <ResizablePanel
            v-if="parametersHeight !== null"
            direction="vertical"
            :min-size="150"
            :max-size="parametersMaxHeight"
            :default-size="parametersHeight"
            storage-key="backtesting-parameters-height"
            @resize="handleParametersResize"
          >
            <StrategyParameters 
              ref="strategyParametersRef"
              :parameters-description="strategyParametersDescription"
              :strategy-name="currentStrategyName"
              :initial-parameters="currentTaskParameters"
              @update-parameters="handleUpdateParameters"
              @parameters-changed="handleParametersChanged"
            />
          </ResizablePanel>
        </div>
      </ResizablePanel>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import ResizablePanel from '../components/ResizablePanel.vue'
import ChartPanel from '../components/ChartPanel.vue'
import MessagesPanel from '../components/MessagesPanel.vue'
import BacktestingNavForm from '../components/BacktestingNavForm.vue'
import StrategyParameters from '../components/StrategyParameters.vue'
import Tabs from '../components/Tabs.vue'
import CodeMirrorEditor from '../components/CodeMirrorEditor.vue'
import BacktestingTaskList from '../components/BacktestingTaskList.vue'
import { strategiesApi } from '../services/strategiesApi'
import { backtestingApi } from '../services/backtestingApi'
import { useBacktesting } from '../composables/useBacktesting'
// Layout state
const chartHeight = ref(null)
const chartMaxHeight = ref(null)
const rightPanelWidth = ref(250)
const rightPanelMaxWidth = ref(null)
const parametersHeight = ref(null)
const parametersMaxHeight = ref(null)

// Tabs
const chartTabs = [
  { id: 'strategy', label: 'Strategy' },
  { id: 'chart', label: 'Chart' }
]
const tabs = [
  { id: 'messages', label: 'Messages' }
]
const activeTab = ref('messages')
const activeChartTab = ref('strategy')

// Strategy state
const strategyCode = ref('')
const currentStrategyName = ref(null)  // Strategy name for display
const currentStrategyFilePath = ref(null)  // Relative path to strategy file (with .py extension, for loading/saving)
const isStrategyLoaded = ref(false)
const strategyLoadError = ref(null)
const previousStrategyName = ref(null)
const strategyParametersDescription = ref(null)
const hasUnsavedChanges = ref(false)

// Task state
const currentTaskId = ref(null)
const currentTask = ref(null)
const currentTaskParameters = ref(null)
const isTaskLoading = ref(false) // Flag to prevent auto-save during task loading

// Selection state
const selectMode = ref(false)
const selectedTasksCount = ref(0)

// Saving state
const isSavingStrategy = ref(false)
const saveTimeout = ref(null)
const taskSaveTimeout = ref(null)

// Chart state
const chartData = ref([]) // Array of {time, open, high, low, close} for chart (deprecated, kept for compatibility)
const clearChartFlag = ref(false) // Flag to trigger chart clearing

// Computed: backtesting progress data for chart
const backtestingProgressData = computed(() => {
  if (backtestProgressDateStart.value && backtestProgressCurrentTime.value) {
    return {
      date_start: backtestProgressDateStart.value,
      current_time: backtestProgressCurrentTime.value
    }
  }
  return null
})

// Component refs
const navFormRef = ref(null)
const taskListRef = ref(null)
const strategyParametersRef = ref(null)

// Use backtesting composable
const {
  allMessages,
  messagesCount,
  isBacktestingRunning,
  backtestProgress,
  backtestProgressState,
  backtestProgressErrorMessage,
  backtestProgressErrorType,
  backtestProgressDateStart,
  backtestProgressCurrentTime,
  clearMessages,
  clearAllMessages,
  addLocalMessage,
  setBacktestingStarted,
  resetBacktestingState
} = useBacktesting(currentTaskId)
// Computed properties
const isMac = computed(() => {
  // Use modern userAgentData API if available, otherwise fall back to userAgent parsing
  if (navigator.userAgentData?.platform) {
    return navigator.userAgentData.platform.toUpperCase().indexOf('MAC') >= 0
  }
  // Fallback: parse userAgent
  return /Mac|iPhone|iPad|iPod/.test(navigator.userAgent)
})

const buttonDisabled = computed(() => {
  // If backtesting is running, button should be enabled (for Stop)
  // If backtesting is not running, button is disabled if no strategy file is loaded
  return !isBacktestingRunning.value && !currentStrategyFilePath.value
})

const errorDisplayMessage = computed(() => {
  // Show simple "Error" message in progress bar
  // Full error message is available in messages panel
  return 'Error'
})

const hasMessages = computed(() => {
  // Check if there are any messages (local or from WebSocket)
  return messagesCount.value > 0
})
// Watch strategy code changes for auto-save
watch(strategyCode, (newValue, oldValue) => {
  // Mark as having unsaved changes when code is modified
  // Only if task is fully loaded (not during loading) and code actually changed
  if (currentStrategyFilePath.value && isStrategyLoaded.value && !isTaskLoading.value && newValue !== oldValue) {
    hasUnsavedChanges.value = true
    
    // Auto-save strategy with debounce (5 seconds after last change)
    if (saveTimeout.value) {
      clearTimeout(saveTimeout.value)
    }
    saveTimeout.value = setTimeout(() => {
      saveCurrentStrategy()
    }, 5000)
  }
})

// Lifecycle hooks
onMounted(() => {
  calculateSizes()
  window.addEventListener('resize', calculateSizes)
  // Save on page close
  window.addEventListener('beforeunload', handleBeforeUnload)
  // Add keyboard shortcut for saving
  document.addEventListener('keydown', handleKeyDown)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', calculateSizes)
  window.removeEventListener('beforeunload', handleBeforeUnload)
  document.removeEventListener('keydown', handleKeyDown)
  // Clear auto-save timers
  if (saveTimeout.value) {
    clearTimeout(saveTimeout.value)
  }
  if (taskSaveTimeout.value) {
    clearTimeout(taskSaveTimeout.value)
  }
  // Save all on component unmount
  saveAllSync()
})
// Methods
function calculateSizes() {
  // Calculate available height (viewport height - navbar height 60px)
  const viewportHeight = window.innerHeight
  const navbarHeight = 60
  const availableHeight = viewportHeight - navbarHeight
  
  // Calculate max height for Chart (available height - min Tabs height)
  const tabsMinHeight = 200
  chartMaxHeight.value = availableHeight - tabsMinHeight
  
  // Calculate max width for right panel (50% of viewport width)
  rightPanelMaxWidth.value = Math.floor(window.innerWidth * 0.5)
  
  // Load saved sizes from localStorage or use defaults
  if (chartHeight.value === null) {
    const savedChartHeight = localStorage.getItem('backtesting-chart-panel-height')
    if (savedChartHeight) {
      const savedHeight = parseInt(savedChartHeight, 10)
      chartHeight.value = Math.min(savedHeight, chartMaxHeight.value)
    } else {
      // Default: 75% of available height for chart
      chartHeight.value = Math.floor(availableHeight * 0.75)
    }
  } else {
    if (chartHeight.value > chartMaxHeight.value) {
      chartHeight.value = chartMaxHeight.value
    }
  }
  
  // Load right panel width
  if (rightPanelWidth.value === 250) {
    const savedRightPanelWidth = localStorage.getItem('backtesting-right-panel-width')
    if (savedRightPanelWidth) {
      const savedWidth = parseInt(savedRightPanelWidth, 10)
      rightPanelWidth.value = Math.min(savedWidth, rightPanelMaxWidth.value)
    } else {
      // Default: 20% of viewport width
      rightPanelWidth.value = Math.floor(window.innerWidth * 0.2)
    }
  } else {
    if (rightPanelWidth.value > rightPanelMaxWidth.value) {
      rightPanelWidth.value = rightPanelMaxWidth.value
    }
  }
  
  // Calculate parameters panel height
  const resultsMinHeight = 150
  parametersMaxHeight.value = availableHeight - resultsMinHeight
  
  if (parametersHeight.value === null) {
    const savedParametersHeight = localStorage.getItem('backtesting-parameters-height')
    if (savedParametersHeight) {
      const savedHeight = parseInt(savedParametersHeight, 10)
      parametersHeight.value = Math.min(savedHeight, parametersMaxHeight.value)
    } else {
      // Default: 50% of available height for parameters
      parametersHeight.value = Math.floor(availableHeight * 0.5)
    }
  } else {
    if (parametersHeight.value > parametersMaxHeight.value) {
      parametersHeight.value = parametersMaxHeight.value
    }
  }
}

function handleChartResize(size) {
  chartHeight.value = size
}

function handleRightPanelResize(size) {
  rightPanelWidth.value = size
}

function handleParametersResize(size) {
  parametersHeight.value = size
}

function handleChartTabChange(tabId) {
  activeChartTab.value = tabId
}
async function handleCloseStrategy() {
  // 1. Disable auto-save timers at the beginning
  if (saveTimeout.value) {
    clearTimeout(saveTimeout.value)
    saveTimeout.value = null
  }
  if (taskSaveTimeout.value) {
    clearTimeout(taskSaveTimeout.value)
    taskSaveTimeout.value = null
  }
  
  // 2. Set loading flag to prevent auto-save
  isTaskLoading.value = true
  
  // Save all before closing
  await saveAll()
  
  // Clear current strategy and return to task list
  currentStrategyName.value = null
  currentStrategyFilePath.value = null
  isStrategyLoaded.value = false
  strategyCode.value = ''
  hasUnsavedChanges.value = false
  strategyLoadError.value = null
  previousStrategyName.value = null
  strategyParametersDescription.value = null
  currentTaskParameters.value = null
  currentTaskId.value = null
  currentTask.value = null
  selectMode.value = false
  selectedTasksCount.value = 0
  
  // Clear messages when closing strategy
  clearAllMessages()
  
  // 6. Keep loading flag true (task is closed, no auto-save needed)
  // isTaskLoading will be set to false when new task is loaded
}

function handleSelectionChanged(selectedIds) {
  selectedTasksCount.value = selectedIds.length
}

function cancelSelection() {
  selectMode.value = false
  selectedTasksCount.value = 0
}

function deleteSelectedTasks() {
  if (taskListRef.value) {
    taskListRef.value.deleteSelected()
  }
}

function handleTabChange(tabId) {
  // Handle tab change
  activeTab.value = tabId
}

// clearMessages is imported from composable
// Use clearAllMessages if you need to clear both local and WebSocket messages
async function handleStrategyCreated(strategyName) {
  // Load strategy when new one is created
  await loadStrategyFile(strategyName)
}

async function handleTaskSelected(task) {
  // 1. Disable auto-save timers at the beginning
  if (saveTimeout.value) {
    clearTimeout(saveTimeout.value)
    saveTimeout.value = null
  }
  if (taskSaveTimeout.value) {
    clearTimeout(taskSaveTimeout.value)
    taskSaveTimeout.value = null
  }
  
  // 2. Set loading flag to prevent auto-save during loading
  isTaskLoading.value = true
  
  // 3. Save previous task if switching to a different one
  if (currentTaskId.value && currentTaskId.value !== task.id) {
    await saveAll()
    // Clear messages when switching to a different task
    clearAllMessages()
  }

  // 4. Load fresh task data from API to ensure we have the latest version
  let freshTask = task
  try {
    freshTask = await backtestingApi.getTask(task.id)
  } catch (error) {
    console.error('Failed to load fresh task data:', error)
    // Fallback to task from list if API call fails
  }

  // 5. Store current task info
  currentTaskId.value = freshTask.id
  currentTask.value = freshTask

  // 6. Update form with task data
  if (navFormRef.value) {
    // Set source first, then symbol in nextTick to avoid SymbolInput watcher clearing symbol
    navFormRef.value.formData.source = freshTask.source || ''
    
    // Set symbol after source watcher has processed (SymbolInput clears symbol on source change)
    nextTick(() => {
      navFormRef.value.formData.symbol = freshTask.symbol || ''
      navFormRef.value.formData.timeframe = freshTask.timeframe || ''
    })

    // Convert ISO dates to YYYY-MM-DD format for date inputs
    if (freshTask.dateStart) {
      const dateStart = new Date(freshTask.dateStart)
      navFormRef.value.formData.dateFrom = dateStart.toISOString().split('T')[0]
    }
    if (freshTask.dateEnd) {
      const dateEnd = new Date(freshTask.dateEnd)
      navFormRef.value.formData.dateTo = dateEnd.toISOString().split('T')[0]
    }
  }

  // 7. Load parameters from task
  currentTaskParameters.value = freshTask.parameters || null

  // 8. Load strategy if available
  if (freshTask.file_name) {
    // file_name is relative path (from STRATEGIES_DIR, with .py extension)
    currentStrategyFilePath.value = freshTask.file_name
    strategyLoadError.value = null
    await loadStrategyFile(currentStrategyFilePath.value)
  } else {
    currentStrategyName.value = null
    currentStrategyFilePath.value = null
    isStrategyLoaded.value = false
    strategyCode.value = ''
    hasUnsavedChanges.value = false
    strategyLoadError.value = null
    currentTaskParameters.value = null
  }
  
  // 9. Enable auto-save timers at the end (after all loading is complete)
  isTaskLoading.value = false
}
async function loadStrategyFile(filePath) {
  try {
    // Try to load strategy file by path
    const strategy = await strategiesApi.loadStrategy(filePath)
    
    if (strategy && strategy.text) {
      strategyCode.value = strategy.text
      hasUnsavedChanges.value = false // Reset flag when loading strategy
      isStrategyLoaded.value = true
      strategyLoadError.value = null
      // Update both name (for display) and file_path (for operations)
      currentStrategyName.value = strategy.name
      currentStrategyFilePath.value = strategy.file_path
      previousStrategyName.value = filePath
      
      // Update parameters description if available
      if (strategy.parameters_description && Object.keys(strategy.parameters_description).length > 0) {
        strategyParametersDescription.value = strategy.parameters_description
      } else {
        strategyParametersDescription.value = null
      }
      
      // Show loading errors as warnings in messages panel
      if (strategy.loading_errors && strategy.loading_errors.length > 0) {
        strategy.loading_errors.forEach(error => {
          addLocalMessage({
            level: 'warning',
            message: `Strategy loading warning: ${error}`
          })
        })
      }
    } else {
      throw new Error('Strategy file is empty or invalid')
    }
  } catch (error) {
    console.error('Failed to load strategy file:', error)
    isStrategyLoaded.value = false
    strategyCode.value = ''
    hasUnsavedChanges.value = false
    strategyParametersDescription.value = null
    
    // Set error message for display
    if (error.response) {
      if (error.response.status === 404) {
        const detail = error.response.data?.detail || ''
        strategyLoadError.value = detail || `Strategy file "${filePath}" not found in strategies directory`
      } else if (error.response.status === 400) {
        const detail = error.response.data?.detail || ''
        strategyLoadError.value = detail || 'Invalid strategy name or path'
      } else {
        const detail = error.response.data?.detail || ''
        strategyLoadError.value = detail || `Server error: ${error.response.status}`
      }
    } else if (error.message) {
      strategyLoadError.value = error.message
    } else {
      strategyLoadError.value = 'Unknown error occurred while loading strategy'
    }
  }
}
async function saveCurrentStrategy() {
  if (!currentStrategyName.value || !isStrategyLoaded.value) {
    return false
  }

  try {
    const response = await strategiesApi.saveStrategy(currentStrategyFilePath.value, strategyCode.value)
    
    // Add syntax errors if any
    if (response.syntax_errors && response.syntax_errors.length > 0) {
      response.syntax_errors.forEach(error => {
        addLocalMessage({
          level: 'error',
          message: `Syntax error: ${error}`
        })
      })
    }
    
    // Refresh parameters description after successful save
    // This ensures we have the latest parameter definitions from the saved strategy
    await refreshParametersDescription()
    
    // Mark as saved after successful save
    hasUnsavedChanges.value = false
    
    return true
  } catch (error) {
    console.error('Failed to save strategy:', error)
    // Extract error message properly
    let errorMessage = 'Unknown error'
    if (error.response?.data?.detail) {
      errorMessage = error.response.data.detail
    } else if (error.message) {
      errorMessage = error.message
    } else if (typeof error === 'string') {
      errorMessage = error
    }
    
    // Add error message to panel
    addLocalMessage({
      level: 'error',
      message: `Failed to save strategy: ${errorMessage}`
    })
    return false
  }
}
async function saveCurrentTask() {
  if (!currentTaskId.value || !navFormRef.value) {
    return
  }

  try {
    // Get general parameters from form
    const formData = navFormRef.value.formData
    
    // Get custom parameters from StrategyParameters component
    let customParameters = {}
    if (strategyParametersRef.value) {
      // Get raw parameter values
      const rawValues = strategyParametersRef.value.parameterValues || {}
      // Convert values to proper types based on parameter descriptions
      const parametersDesc = strategyParametersDescription.value || {}
      customParameters = {}
      for (const paramName in rawValues) {
        const value = rawValues[paramName]
        if (parametersDesc[paramName]) {
          const paramDesc = parametersDesc[paramName]
          const typeLower = paramDesc.type?.toLowerCase() || 'string'
          // Convert to proper type
          if (typeLower === 'int' || typeLower === 'integer') {
            const parsed = parseInt(value, 10)
            customParameters[paramName] = isNaN(parsed) ? value : parsed
          } else if (typeLower === 'float' || typeLower === 'double') {
            const parsed = parseFloat(value)
            customParameters[paramName] = isNaN(parsed) ? value : parsed
          } else if (typeLower === 'bool' || typeLower === 'boolean') {
            customParameters[paramName] = Boolean(value)
          } else {
            customParameters[paramName] = String(value)
          }
        } else {
          // If no description, keep as is
          customParameters[paramName] = value
        }
      }
    } else {
      // Fallback: use currentTaskParameters if component ref not available
      customParameters = currentTaskParameters.value || {}
    }

    // Prepare task data
    // file_name is relative path (from STRATEGIES_DIR, with .py extension)
    const taskData = {
      file_name: currentStrategyFilePath.value || '',
      name: currentTask.value?.name || '',
      source: formData.source || '',
      symbol: formData.symbol || '',
      timeframe: formData.timeframe || '',
      dateStart: formData.dateFrom ? new Date(formData.dateFrom).toISOString() : '',
      dateEnd: formData.dateTo ? new Date(formData.dateTo).toISOString() : '',
      parameters: customParameters
    }

    const updatedTask = await backtestingApi.updateTask(currentTaskId.value, taskData)
    
    // Update currentTaskParameters from response to keep it in sync
    // Create a new object to ensure Vue reactivity
    if (updatedTask && updatedTask.parameters) {
      currentTaskParameters.value = { ...updatedTask.parameters }
    } else if (updatedTask && !updatedTask.parameters) {
      currentTaskParameters.value = {}
    }
  } catch (error) {
    console.error('Failed to save task:', error)
    // Add error message to panel
    addLocalMessage({
      level: 'error',
      message: `Failed to save task: ${error.response?.data?.detail || error.message}`
    })
  }
}

async function saveAll() {
  // Save both strategy and task
  await Promise.all([
    saveCurrentStrategy(),
    saveCurrentTask()
  ])
}
async function saveAllSync() {
  // Save all synchronously (for beforeunload/unmount)
  if (!currentStrategyFilePath.value || !isStrategyLoaded.value) {
    return
  }

  try {
    // Save strategy using sendBeacon or sync XHR
    const strategyData = JSON.stringify({
      file_path: currentStrategyFilePath.value,
      text: strategyCode.value
    })
    
    if (navigator.sendBeacon) {
      const blob = new Blob([strategyData], { type: 'application/json' })
      const url = `${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8202'}/api/v1/strategies/save`
      navigator.sendBeacon(url, blob)
    } else {
      try {
        const xhr = new XMLHttpRequest()
        xhr.open('POST', `${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8202'}/api/v1/strategies/save`, false)
        xhr.setRequestHeader('Content-Type', 'application/json')
        xhr.send(strategyData)
      } catch (error) {
        console.error('Failed to save strategy on page unload:', error)
      }
    }

    // Save task if available
    if (currentTaskId.value && navFormRef.value) {
      const formData = navFormRef.value.formData
      let customParameters = {}
      if (strategyParametersRef.value) {
        customParameters = strategyParametersRef.value.parameterValues || {}
      } else {
        customParameters = currentTaskParameters.value || {}
      }

      // file_name is relative path (from STRATEGIES_DIR, with .py extension)
      const taskData = JSON.stringify({
        file_name: currentStrategyFilePath.value || '',
        name: currentTask.value?.name || '',
        source: formData.source || '',
        symbol: formData.symbol || '',
        timeframe: formData.timeframe || '',
        dateStart: formData.dateFrom ? new Date(formData.dateFrom).toISOString() : '',
        dateEnd: formData.dateTo ? new Date(formData.dateTo).toISOString() : '',
        parameters: customParameters
      })

      // sendBeacon doesn't support PUT, use sync XHR
      try {
        const xhr = new XMLHttpRequest()
        xhr.open('PUT', `${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8202'}/api/v1/backtesting/tasks/${currentTaskId.value}`, false)
        xhr.setRequestHeader('Content-Type', 'application/json')
        xhr.send(taskData)
      } catch (error) {
        console.error('Failed to save task on page unload:', error)
      }
    }
  } catch (error) {
    console.error('Failed to save on unmount:', error)
  }
}

function handleBeforeUnload(event) {
  // Save all before page close
  saveAllSync()
}
async function handleStart(formData) {
  // Validate that we have a current task
  if (!currentTaskId.value) {
    addLocalMessage({
      level: 'error',
      message: 'No task selected. Please select or create a task first.'
    })
    return
  }

  // Validate that we have a strategy file
  if (!currentStrategyFilePath.value) {
    addLocalMessage({
      level: 'error',
      message: 'No strategy file selected. Please select a strategy first.'
    })
    return
  }

  // Validate form data
  if (!formData.source || !formData.symbol || !formData.timeframe || !formData.dateFrom || !formData.dateTo) {
    addLocalMessage({
      level: 'error',
      message: 'Please fill in all required fields: Source, Symbol, Timeframe, Date From, Date To'
    })
    return
  }

  // Save current task before starting backtest
  try {
    await saveAll()
  } catch (error) {
    console.error('Failed to save before starting backtest:', error)
    addLocalMessage({
      level: 'error',
      message: `Failed to save task before starting backtest: ${error.message}`
    })
    return
  }

  // Set backtesting state immediately for instant UI feedback
  setBacktestingStarted()
  
  try {
    // Call API to start backtesting
    await backtestingApi.startBacktest(currentTaskId.value)
    // State will also be updated by composable when backtesting_started event is received via WebSocket
    // But we set it immediately above for instant UI feedback
  } catch (error) {
    console.error('Failed to start backtesting:', error)
    // Reset state on error
    resetBacktestingState()
    const errorMessage = error.response?.data?.detail || error.message || 'Unknown error'
    addLocalMessage({
      level: 'error',
      message: `Failed to start backtesting: ${errorMessage}`
    })
  }
}

async function handleStop() {
  // Validate that we have a current task
  if (!currentTaskId.value) {
    addLocalMessage({
      level: 'error',
      message: 'No task selected. Cannot stop backtesting.'
    })
    return
  }

  try {
    // Call API to stop backtesting
    // All UI changes will happen via WebSocket packets (error packet)
    await backtestingApi.stopBacktest(currentTaskId.value)
  } catch (error) {
    console.error('Failed to stop backtesting:', error)
    const errorMessage = error.response?.data?.detail || error.message || 'Unknown error'
    addLocalMessage({
      level: 'error',
      message: `Failed to stop backtesting: ${errorMessage}`
    })
  }
}
async function handleUpdateParameters() {
  // Update parameters description from strategy
  if (!currentStrategyName.value || !isStrategyLoaded.value) {
    return
  }
  
  try {
    // Save strategy first to ensure we get the latest parameters
    await strategiesApi.saveStrategy(currentStrategyFilePath.value, strategyCode.value)
    
    // Mark as saved after successful save
    hasUnsavedChanges.value = false
    
    // Now load strategy to get updated parameters
    await refreshParametersDescription()
  } catch (error) {
    console.error('Failed to update parameters:', error)
    // Add error message to panel
    addLocalMessage({
      level: 'error',
      message: `Failed to update parameters: ${error.message}`
    })
  }
}

async function refreshParametersDescription() {
  // Refresh parameters description from strategy file
  if (!currentStrategyFilePath.value) {
    return
  }

  try {
    const strategy = await strategiesApi.loadStrategy(currentStrategyFilePath.value)
    
    // Only update if parameters were successfully loaded (no errors)
    if (strategy.loading_errors && strategy.loading_errors.length > 0) {
      // Don't update parameters if there are errors
      strategyParametersDescription.value = null
      // Add loading errors
      strategy.loading_errors.forEach(error => {
        addLocalMessage({
          level: 'error',
          message: `Failed to load parameters: ${error}`
        })
      })
    } else if (strategy.parameters_description && Object.keys(strategy.parameters_description).length > 0) {
      // Update parameters only if no errors
      strategyParametersDescription.value = strategy.parameters_description
    } else {
      strategyParametersDescription.value = null
    }
  } catch (error) {
    console.error('Failed to refresh parameters description:', error)
    addLocalMessage({
      level: 'error',
      message: `Failed to refresh parameters: ${error.message}`
    })
  }
}

function handleFormDataChanged() {
  // Triggered when general parameters change in BacktestingNavForm
  // Auto-save task with debounce (5 seconds)
  // Only if task is fully loaded (not during loading)
  if (currentTaskId.value && !isTaskLoading.value) {
    if (taskSaveTimeout.value) {
      clearTimeout(taskSaveTimeout.value)
    }
    taskSaveTimeout.value = setTimeout(() => {
      saveCurrentTask()
    }, 5000)
  }
}

function handleParametersChanged() {
  // Triggered when custom parameters change in StrategyParameters component
  // Auto-save task with debounce (5 seconds)
  // Only if task is fully loaded (not during loading)
  if (currentTaskId.value && !isTaskLoading.value) {
    if (taskSaveTimeout.value) {
      clearTimeout(taskSaveTimeout.value)
    }
    taskSaveTimeout.value = setTimeout(() => {
      saveCurrentTask()
    }, 5000)
  }
}

function handleQuotesLoadError(error) {
  // Handle error from chart when loading quotes
  const errorMessage = error.response?.data?.detail || error.message || 'Failed to load quotes data'
  addLocalMessage({
    level: 'error',
    message: `Chart data loading error: ${errorMessage}`
  })
}

function handleChartMessage(message) {
  addLocalMessage({
    level: message.level || 'info',
    message: message.message
  })
}

function handleKeyDown(event) {
  // Handle Ctrl+S (or Cmd+S on Mac) to save strategy
  // This is a fallback for cases when CodeMirror doesn't handle it
  // Only if we're not in an input/textarea/select element
  const target = event.target
  const isInputElement = target.tagName === 'INPUT' || 
                         target.tagName === 'TEXTAREA' || 
                         target.tagName === 'SELECT' ||
                         target.isContentEditable
  
  // Check if we're in CodeMirror editor (CodeMirror 6 uses .cm-editor class)
  const isInCodeMirror = target.closest('.cm-editor') || target.closest('.cm-content')
  
  if ((event.ctrlKey || event.metaKey) && event.key === 's') {
    // Only save if strategy is loaded, we're on strategy tab, and there are unsaved changes
    if (currentStrategyFilePath.value && isStrategyLoaded.value && activeChartTab.value === 'strategy' && hasUnsavedChanges.value) {
      // If we're in CodeMirror, it should handle it, but prevent default anyway
      // If we're not in an input field, handle it
      if (isInCodeMirror || !isInputElement) {
        event.preventDefault()
        handleSaveStrategy()
      }
    }
  }
}

async function handleSaveStrategy() {
  if (!currentStrategyFilePath.value || !isStrategyLoaded.value || isSavingStrategy.value || !hasUnsavedChanges.value) {
    return
  }
  
  // Clear auto-save timeout since we're saving manually
  if (saveTimeout.value) {
    clearTimeout(saveTimeout.value)
    saveTimeout.value = null
  }
  
  isSavingStrategy.value = true
  try {
    const success = await saveCurrentStrategy()
    // Show success message only if save was successful
    if (success) {
      addLocalMessage({
        level: 'info',
        message: 'Strategy saved successfully'
      })
    }
  } catch (error) {
    // Error is already handled in saveCurrentStrategy
    console.error('Failed to save strategy:', error)
  } finally {
    isSavingStrategy.value = false
  }
}
</script>

<style scoped>
.backtesting-view {
  width: 100%;
  height: 100%;
  overflow: hidden;
}

.backtest-progress {
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-md);
  padding: var(--spacing-xs) var(--spacing-md);
  border-bottom: 1px solid var(--border-color);
  background-color: var(--bg-secondary);
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
}

.backtest-progress.error-state {
  background-color: rgba(239, 68, 68, 0.1);
  border-bottom-color: var(--color-danger, #ef4444);
  border-bottom-width: 2px;
}

.backtest-progress .progress-text {
  flex: 0 0 auto;
  white-space: nowrap;
}

.backtest-progress .progress-text .error-message {
  color: var(--color-danger, #ef4444);
  font-weight: var(--font-weight-semibold, 600);
  animation: error-pulse 2s ease-in-out infinite;
}

@keyframes error-pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.7;
  }
}

.backtest-progress .progress-bar {
  flex: 1 1 auto;
  height: 8px;
  border-radius: 9999px;
  /* Use explicit colors so the bar is clearly visible */
  background-color: #e5e7eb; /* light gray */
  border: 1px solid #d1d5db;
  overflow: hidden;
}

.backtest-progress .progress-bar-fill {
  height: 100%;
  width: 0;
  border-radius: inherit;
  /* Simple solid color for better visibility */
  background-color: #3b82f6; /* blue-500 */
}

.backtesting-layout {
  display: flex;
  flex-direction: row;
  width: 100%;
  height: 100%;
  overflow: hidden;
}

.left-panel {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  height: 100%;
}

.right-panel {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  overflow: hidden;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  margin-left: auto;
  margin-right: var(--spacing-sm);
}

.header-btn {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  padding: var(--spacing-xs) var(--spacing-sm);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--text-secondary);
  background-color: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all var(--transition-base);
}

.header-btn:hover:not(:disabled) {
  background-color: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--color-primary);
}

.header-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.header-btn.danger {
  color: var(--color-danger);
  border-color: var(--border-color);
}

.header-btn.danger:disabled {
  opacity: 0.5;
}

.header-btn.danger:hover:not(:disabled) {
  background-color: var(--color-danger-light);
  border-color: var(--color-danger);
}

.header-btn .icon {
  width: var(--font-size-sm);
  height: var(--font-size-sm);
}

.save-btn {
  margin-right: var(--spacing-sm);
}

.strategy-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding: var(--spacing-xl);
  background-color: var(--bg-primary);
  color: var(--text-primary);
  text-align: center;
}

.strategy-error .error-icon {
  font-size: 3rem; /* 48px */
  margin-bottom: var(--spacing-lg);
}

.strategy-error h3 {
  margin: 0 0 var(--spacing-md) 0;
  font-size: var(--font-size-lg);
  color: var(--color-danger);
}

.strategy-error .strategy-name {
  margin: var(--spacing-sm) 0;
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  color: var(--text-secondary);
}

.strategy-error .error-message {
  margin: var(--spacing-md) 0 0 0;
  padding: var(--spacing-md);
  font-size: var(--font-size-sm);
  color: var(--text-tertiary);
  background-color: var(--bg-secondary);
  border-radius: var(--border-radius);
  border-left: var(--spacing-xs) solid var(--color-danger);
  max-width: 37.5rem; /* 600px */
}

</style>
