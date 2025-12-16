<template>
  <div class="backtesting-view">
    <!-- Teleport form to navbar -->
    <Teleport to="#navbar-content-slot">
      <BacktestingNavForm 
        ref="navForm" 
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
              <ChartPanel />
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
                @click="clearMessages"
                :disabled="backtestMessages.length === 0"
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
            <MessagesPanelSocket :task-id="currentTaskId" />
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
              ref="strategyParameters"
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

<script>
import ResizablePanel from '../components/ResizablePanel.vue'
import ChartPanel from '../components/ChartPanel.vue'
import MessagesPanelSocket from '../components/MessagesPanelSocket.vue'
import BacktestingNavForm from '../components/BacktestingNavForm.vue'
import StrategyParameters from '../components/StrategyParameters.vue'
import Tabs from '../components/Tabs.vue'
import CodeMirrorEditor from '../components/CodeMirrorEditor.vue'
import BacktestingTaskList from '../components/BacktestingTaskList.vue'
import { strategiesApi } from '../services/strategiesApi'
import { backtestingApi } from '../services/backtestingApi'

export default {
  name: 'BacktestingView',
  components: {
    ResizablePanel,
    ChartPanel,
    MessagesPanelSocket,
    BacktestingNavForm,
    StrategyParameters,
    Tabs,
    CodeMirrorEditor,
    BacktestingTaskList
  },
  data() {
    return {
      chartHeight: null,
      chartMaxHeight: null,
      rightPanelWidth: 250,
      rightPanelMaxWidth: null,
      parametersHeight: null,
      parametersMaxHeight: null,
      chartTabs: [
        { id: 'strategy', label: 'Strategy' },
        { id: 'chart', label: 'Chart' }
      ],
      tabs: [
        { id: 'messages', label: 'Messages' }
      ],
      activeTab: 'messages',
      strategyCode: '',
      activeChartTab: 'strategy',
      currentStrategyName: null,  // Strategy name for display
      currentStrategyFilePath: null,  // Relative path to strategy file (with .py extension, for loading/saving)
      isStrategyLoaded: false,
      strategyLoadError: null,
      previousStrategyName: null,
      saveTimeout: null,
      taskSaveTimeout: null,
      backtestMessages: [],
      strategyParametersDescription: null,
      currentTaskParameters: null,
      currentTaskId: null,
      currentTask: null,
      isTaskLoading: false, // Flag to prevent auto-save during task loading
      selectMode: false,
      selectedTasksCount: 0,
      isBacktestingRunning: false, // Flag to indicate if backtesting is in progress
      isSavingStrategy: false, // Flag to indicate if strategy is being saved
      hasUnsavedChanges: false, // Flag to track if strategy code has been modified since last save
      backtestProgress: 0,
      backtestProgressState: 'idle', // 'idle' | 'running' | 'completed' | 'error'
      backtestProgressErrorMessage: '',
      backtestProgressErrorType: null, // 'error' | 'cancel' | null
      backtestResultsSocket: null
    }
  },
  computed: {
    isMac() {
      // Use modern userAgentData API if available, otherwise fall back to userAgent parsing
      if (navigator.userAgentData?.platform) {
        return navigator.userAgentData.platform.toUpperCase().indexOf('MAC') >= 0
      }
      // Fallback: parse userAgent
      return /Mac|iPhone|iPad|iPod/.test(navigator.userAgent)
    },
    buttonDisabled() {
      // If backtesting is running, button should be enabled (for Stop)
      // If backtesting is not running, button is disabled if no strategy file is loaded
      return !this.isBacktestingRunning && !this.currentStrategyFilePath
    },
    errorDisplayMessage() {
      // For cancel packets, show message without prefix
      // For error packets, add "Backtesting error: " prefix
      if (this.backtestProgressErrorType === 'cancel') {
        return this.backtestProgressErrorMessage || 'Backtesting was cancelled'
      }
      return `Backtesting error: ${this.backtestProgressErrorMessage || 'Unknown error'}`
    }
  },
  mounted() {
    this.calculateSizes()
    window.addEventListener('resize', this.calculateSizes)
    // Save on page close
    window.addEventListener('beforeunload', this.handleBeforeUnload)
    // Add keyboard shortcut for saving
    document.addEventListener('keydown', this.handleKeyDown)
  },
  beforeUnmount() {
    window.removeEventListener('resize', this.calculateSizes)
    window.removeEventListener('beforeunload', this.handleBeforeUnload)
    document.removeEventListener('keydown', this.handleKeyDown)
    // Clear auto-save timers
    if (this.saveTimeout) {
      clearTimeout(this.saveTimeout)
    }
    if (this.taskSaveTimeout) {
      clearTimeout(this.taskSaveTimeout)
    }
    // Save all on component unmount
    this.saveAllSync()
    // Close backtest results WebSocket if open
    if (this.backtestResultsSocket) {
      this.backtestResultsSocket.close()
      this.backtestResultsSocket = null
    }
  },
  watch: {
    strategyCode(newValue, oldValue) {
      // Mark as having unsaved changes when code is modified
      // Only if task is fully loaded (not during loading) and code actually changed
      if (this.currentStrategyFilePath && this.isStrategyLoaded && !this.isTaskLoading && newValue !== oldValue) {
        this.hasUnsavedChanges = true
        
        // Auto-save strategy with debounce (5 seconds after last change)
        if (this.saveTimeout) {
          clearTimeout(this.saveTimeout)
        }
        this.saveTimeout = setTimeout(() => {
          this.saveCurrentStrategy()
        }, 5000)
      }
    },
    // Form data changes are handled via event from BacktestingNavForm
  },
  methods: {
    calculateSizes() {
      // Calculate available height (viewport height - navbar height 60px)
      const viewportHeight = window.innerHeight
      const navbarHeight = 60
      const availableHeight = viewportHeight - navbarHeight
      
      // Calculate max height for Chart (available height - min Tabs height)
      const tabsMinHeight = 200
      this.chartMaxHeight = availableHeight - tabsMinHeight
      
      // Calculate max width for right panel (50% of viewport width)
      this.rightPanelMaxWidth = Math.floor(window.innerWidth * 0.5)
      
      // Load saved sizes from localStorage or use defaults
      if (this.chartHeight === null) {
        const savedChartHeight = localStorage.getItem('backtesting-chart-panel-height')
        if (savedChartHeight) {
          const savedHeight = parseInt(savedChartHeight, 10)
          this.chartHeight = Math.min(savedHeight, this.chartMaxHeight)
        } else {
          // Default: 75% of available height for chart
          this.chartHeight = Math.floor(availableHeight * 0.75)
        }
      } else {
        if (this.chartHeight > this.chartMaxHeight) {
          this.chartHeight = this.chartMaxHeight
        }
      }
      
      // Load right panel width
      if (this.rightPanelWidth === 250) {
        const savedRightPanelWidth = localStorage.getItem('backtesting-right-panel-width')
        if (savedRightPanelWidth) {
          const savedWidth = parseInt(savedRightPanelWidth, 10)
          this.rightPanelWidth = Math.min(savedWidth, this.rightPanelMaxWidth)
        } else {
          // Default: 20% of viewport width
          this.rightPanelWidth = Math.floor(window.innerWidth * 0.2)
        }
      } else {
        if (this.rightPanelWidth > this.rightPanelMaxWidth) {
          this.rightPanelWidth = this.rightPanelMaxWidth
        }
      }
      
      // Calculate parameters panel height
      const resultsMinHeight = 150
      this.parametersMaxHeight = availableHeight - resultsMinHeight
      
      if (this.parametersHeight === null) {
        const savedParametersHeight = localStorage.getItem('backtesting-parameters-height')
        if (savedParametersHeight) {
          const savedHeight = parseInt(savedParametersHeight, 10)
          this.parametersHeight = Math.min(savedHeight, this.parametersMaxHeight)
        } else {
          // Default: 50% of available height for parameters
          this.parametersHeight = Math.floor(availableHeight * 0.5)
        }
      } else {
        if (this.parametersHeight > this.parametersMaxHeight) {
          this.parametersHeight = this.parametersMaxHeight
        }
      }
    },
    handleChartResize(size) {
      this.chartHeight = size
    },
    handleRightPanelResize(size) {
      this.rightPanelWidth = size
    },
    handleParametersResize(size) {
      this.parametersHeight = size
    },
    handleChartTabChange(tabId) {
      this.activeChartTab = tabId
    },
    async handleCloseStrategy() {
      // 1. Disable auto-save timers at the beginning
      if (this.saveTimeout) {
        clearTimeout(this.saveTimeout)
        this.saveTimeout = null
      }
      if (this.taskSaveTimeout) {
        clearTimeout(this.taskSaveTimeout)
        this.taskSaveTimeout = null
      }
      
      // 2. Set loading flag to prevent auto-save
      this.isTaskLoading = true
      
      // Save all before closing
      await this.saveAll()
      
      // Clear current strategy and return to task list
        this.currentStrategyName = null
        this.currentStrategyFilePath = null
        this.isStrategyLoaded = false
        this.strategyCode = ''
        this.hasUnsavedChanges = false
        this.strategyLoadError = null
        this.previousStrategyName = null
      this.strategyParametersDescription = null
      this.currentTaskParameters = null
      this.currentTaskId = null
      this.currentTask = null
      this.selectMode = false
      this.selectedTasksCount = 0
      
      // 6. Keep loading flag true (task is closed, no auto-save needed)
      // isTaskLoading will be set to false when new task is loaded
    },
    _openBacktestResultsSocket(taskId) {
      // Close previous socket if any
      if (this.backtestResultsSocket) {
        this.backtestResultsSocket.close()
        this.backtestResultsSocket = null
      }

      const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8202'
      const wsUrl = baseUrl.replace(/^http/i, 'ws') + `/api/v1/backtesting/tasks/${taskId}/results`

      try {
        const socket = new WebSocket(wsUrl)
        this.backtestResultsSocket = socket

        socket.onopen = () => {
          this.backtestProgressState = 'running'
          this.backtestProgress = 0
        }

        socket.onmessage = (event) => {
          try {
            const packet = JSON.parse(event.data)
            this._handleBacktestResultPacket(packet)
          } catch (e) {
            console.error('Failed to parse backtest results packet:', e)
          }
        }

        socket.onerror = (event) => {
          console.error('Backtest results WebSocket error:', event)
          this.backtestProgressState = 'error'
          this.backtestProgressErrorType = 'error'
          if (!this.backtestProgressErrorMessage) {
            this.backtestProgressErrorMessage = 'WebSocket error while receiving backtesting results'
          }
          this.isBacktestingRunning = false
        }

        socket.onclose = () => {
          this.backtestResultsSocket = null
          // If backtesting was running but socket closed unexpectedly, reset flag
          if (this.isBacktestingRunning && this.backtestProgressState === 'running') {
            this.isBacktestingRunning = false
            this.backtestProgressState = 'error'
            this.backtestProgressErrorType = 'error'
            this.backtestProgressErrorMessage = 'Connection closed unexpectedly'
          } else if (this.isBacktestingRunning && this.backtestProgressState === 'completed') {
            // If socket closes after completion, ensure flag is reset
            this.isBacktestingRunning = false
          }
        }
      } catch (e) {
        console.error('Failed to open backtest results WebSocket:', e)
        this.backtestProgressState = 'error'
        this.backtestProgressErrorType = 'error'
        this.backtestProgressErrorMessage = 'Failed to open WebSocket for backtesting results'
        this.isBacktestingRunning = false
      }
    },
    handleSelectionChanged(selectedIds) {
      this.selectedTasksCount = selectedIds.length
    },
    cancelSelection() {
      this.selectMode = false
      this.selectedTasksCount = 0
    },
    deleteSelectedTasks() {
      if (this.$refs.taskList) {
        this.$refs.taskList.deleteSelected()
      }
    },
    handleTabChange(tabId) {
      // Handle tab change
      this.activeTab = tabId
    },
    clearMessages() {
      this.backtestMessages = []
    },
    _resetBacktestProgress() {
      this.backtestProgress = 0
      this.backtestProgressState = 'idle'
      this.backtestProgressErrorMessage = ''
      this.backtestProgressErrorType = null
    },
    _handleBacktestResultPacket(packet) {
      const type = packet?.type
      if (!type) {
        this.backtestProgressState = 'error'
        this.backtestProgressErrorType = 'error'
        this.backtestProgressErrorMessage = 'Invalid results packet received'
        return
      }

      if (type === 'start') {
        this.backtestProgressState = 'running'
        this.backtestProgress = 0
        return
      }

      if (type === 'error') {
        this.backtestProgressState = 'error'
        this.backtestProgressErrorType = 'error'
        this.backtestProgressErrorMessage = packet.data?.message || 'Unknown backtesting error'
        this.isBacktestingRunning = false
        return
      }

      if (type === 'cancel') {
        this.backtestProgressState = 'error'
        this.backtestProgressErrorType = 'cancel'
        this.backtestProgressErrorMessage = packet.data?.message || 'Backtesting was cancelled'
        this.isBacktestingRunning = false
        return
      }

      if (type === 'data') {
        const progress = packet.data?.progress
        if (typeof progress === 'number') {
          this.backtestProgress = Math.min(100, Math.max(0, progress))
          this.backtestProgressState = 'running'
        }
        return
      }

      if (type === 'end') {
        this.backtestProgress = 100
        this.backtestProgressState = 'completed'
        this.isBacktestingRunning = false
        return
      }
    },
    async handleStrategyCreated(strategyName) {
      // Load strategy when new one is created
      await this.loadStrategyFile(strategyName)
    },
    async handleTaskSelected(task) {
      // 1. Disable auto-save timers at the beginning
      if (this.saveTimeout) {
        clearTimeout(this.saveTimeout)
        this.saveTimeout = null
      }
      if (this.taskSaveTimeout) {
        clearTimeout(this.taskSaveTimeout)
        this.taskSaveTimeout = null
      }
      
      // 2. Set loading flag to prevent auto-save during loading
      this.isTaskLoading = true
      
      // 3. Save previous task if switching to a different one
      if (this.currentTaskId && this.currentTaskId !== task.id) {
        await this.saveAll()
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
      this.currentTaskId = freshTask.id
      this.currentTask = freshTask

      // 6. Update form with task data
      if (this.$refs.navForm) {
        // Set source first, then symbol in nextTick to avoid SymbolInput watcher clearing symbol
        this.$refs.navForm.formData.source = freshTask.source || ''
        
        // Set symbol after source watcher has processed (SymbolInput clears symbol on source change)
        this.$nextTick(() => {
          this.$refs.navForm.formData.symbol = freshTask.symbol || ''
          this.$refs.navForm.formData.timeframe = freshTask.timeframe || ''
        })

        // Convert ISO dates to YYYY-MM-DD format for date inputs
        if (freshTask.dateStart) {
          const dateStart = new Date(freshTask.dateStart)
          this.$refs.navForm.formData.dateFrom = dateStart.toISOString().split('T')[0]
        }
        if (freshTask.dateEnd) {
          const dateEnd = new Date(freshTask.dateEnd)
          this.$refs.navForm.formData.dateTo = dateEnd.toISOString().split('T')[0]
        }
      }

      // 7. Load parameters from task
      this.currentTaskParameters = freshTask.parameters || null

      // 8. Load strategy if available
      if (freshTask.file_name) {
        // file_name is relative path (from STRATEGIES_DIR, with .py extension)
        this.currentStrategyFilePath = freshTask.file_name
        this.strategyLoadError = null
        await this.loadStrategyFile(this.currentStrategyFilePath)
      } else {
        this.currentStrategyName = null
        this.currentStrategyFilePath = null
        this.isStrategyLoaded = false
        this.strategyCode = ''
        this.hasUnsavedChanges = false
        this.strategyLoadError = null
        this.currentTaskParameters = null
      }
      
      // 9. Enable auto-save timers at the end (after all loading is complete)
      this.isTaskLoading = false
    },
    async loadStrategyFile(filePath) {
      try {
        // Try to load strategy file by path
        const strategy = await strategiesApi.loadStrategy(filePath)
        
        if (strategy && strategy.text) {
          this.strategyCode = strategy.text
          this.hasUnsavedChanges = false // Reset flag when loading strategy
          this.isStrategyLoaded = true
          this.strategyLoadError = null
          // Update both name (for display) and file_path (for operations)
          this.currentStrategyName = strategy.name
          this.currentStrategyFilePath = strategy.file_path
          this.previousStrategyName = filePath
          
          // Update parameters description if available
          if (strategy.parameters_description && Object.keys(strategy.parameters_description).length > 0) {
            this.strategyParametersDescription = strategy.parameters_description
          } else {
            this.strategyParametersDescription = null
          }
          
          // Show loading errors as warnings in messages panel
          if (strategy.loading_errors && strategy.loading_errors.length > 0) {
            strategy.loading_errors.forEach(error => {
              this.backtestMessages.push({
                timestamp: new Date().toISOString(),
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
        this.isStrategyLoaded = false
        this.strategyCode = ''
        this.hasUnsavedChanges = false
        this.strategyParametersDescription = null
        
        // Set error message for display
        if (error.response) {
          if (error.response.status === 404) {
            const detail = error.response.data?.detail || ''
            this.strategyLoadError = detail || `Strategy file "${filePath}" not found in strategies directory`
          } else if (error.response.status === 400) {
            const detail = error.response.data?.detail || ''
            this.strategyLoadError = detail || 'Invalid strategy name or path'
          } else {
            const detail = error.response.data?.detail || ''
            this.strategyLoadError = detail || `Server error: ${error.response.status}`
          }
        } else if (error.message) {
          this.strategyLoadError = error.message
        } else {
          this.strategyLoadError = 'Unknown error occurred while loading strategy'
        }
      }
    },
    async saveCurrentStrategy() {
      if (!this.currentStrategyName || !this.isStrategyLoaded) {
        return false
      }

      try {
        const response = await strategiesApi.saveStrategy(this.currentStrategyFilePath, this.strategyCode)
        
        // Remove old syntax error messages
        this.backtestMessages = this.backtestMessages.filter(
          msg => !msg.message.startsWith('Syntax error:')
        )
        
        // Add syntax errors if any
        if (response.syntax_errors && response.syntax_errors.length > 0) {
          response.syntax_errors.forEach(error => {
            this.backtestMessages.push({
              timestamp: new Date().toISOString(),
              level: 'error',
              message: `Syntax error: ${error}`
            })
          })
        }
        
        // Refresh parameters description after successful save
        // This ensures we have the latest parameter definitions from the saved strategy
        await this.refreshParametersDescription()
        
        // Mark as saved after successful save
        this.hasUnsavedChanges = false
        
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
        this.backtestMessages.push({
          timestamp: new Date().toISOString(),
          level: 'error',
          message: `Failed to save strategy: ${errorMessage}`
        })
        return false
      }
    },
    async saveCurrentTask() {
      if (!this.currentTaskId || !this.$refs.navForm) {
        return
      }

      try {
        // Get general parameters from form
        const formData = this.$refs.navForm.formData
        
        // Get custom parameters from StrategyParameters component
        let customParameters = {}
        if (this.$refs.strategyParameters) {
          // Get raw parameter values
          const rawValues = this.$refs.strategyParameters.parameterValues || {}
          // Convert values to proper types based on parameter descriptions
          const parametersDesc = this.strategyParametersDescription || {}
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
          customParameters = this.currentTaskParameters || {}
        }

        // Prepare task data
        // file_name is relative path (from STRATEGIES_DIR, with .py extension)
        const taskData = {
          file_name: this.currentStrategyFilePath || '',
          name: this.currentTask?.name || '',
          source: formData.source || '',
          symbol: formData.symbol || '',
          timeframe: formData.timeframe || '',
          dateStart: formData.dateFrom ? new Date(formData.dateFrom).toISOString() : '',
          dateEnd: formData.dateTo ? new Date(formData.dateTo).toISOString() : '',
          parameters: customParameters
        }

        const updatedTask = await backtestingApi.updateTask(this.currentTaskId, taskData)
        
        // Update currentTaskParameters from response to keep it in sync
        // Create a new object to ensure Vue reactivity
        if (updatedTask && updatedTask.parameters) {
          this.currentTaskParameters = { ...updatedTask.parameters }
        } else if (updatedTask && !updatedTask.parameters) {
          this.currentTaskParameters = {}
        }
      } catch (error) {
        console.error('Failed to save task:', error)
        // Add error message to panel
        this.backtestMessages.push({
          timestamp: new Date().toISOString(),
          level: 'error',
          message: `Failed to save task: ${error.response?.data?.detail || error.message}`
        })
      }
    },
    async saveAll() {
      // Save both strategy and task
      await Promise.all([
        this.saveCurrentStrategy(),
        this.saveCurrentTask()
      ])
    },
    async saveAllSync() {
      // Save all synchronously (for beforeunload/unmount)
      if (!this.currentStrategyFilePath || !this.isStrategyLoaded) {
        return
      }

      try {
        // Save strategy using sendBeacon or sync XHR
        const strategyData = JSON.stringify({
          file_path: this.currentStrategyFilePath,
          text: this.strategyCode
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
        if (this.currentTaskId && this.$refs.navForm) {
          const formData = this.$refs.navForm.formData
          let customParameters = {}
          if (this.$refs.strategyParameters) {
            customParameters = this.$refs.strategyParameters.parameterValues || {}
          } else {
            customParameters = this.currentTaskParameters || {}
          }

          // file_name is relative path (from STRATEGIES_DIR, with .py extension)
          const taskData = JSON.stringify({
            file_name: this.currentStrategyFilePath || '',
            name: this.currentTask?.name || '',
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
            xhr.open('PUT', `${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8202'}/api/v1/backtesting/tasks/${this.currentTaskId}`, false)
            xhr.setRequestHeader('Content-Type', 'application/json')
            xhr.send(taskData)
          } catch (error) {
            console.error('Failed to save task on page unload:', error)
          }
        }
      } catch (error) {
        console.error('Failed to save on unmount:', error)
      }
    },
    handleBeforeUnload(event) {
      // Save all before page close
      this.saveAllSync()
    },
    async handleStart(formData) {
      // Validate that we have a current task
      if (!this.currentTaskId) {
        this.backtestMessages.push({
          timestamp: new Date().toISOString(),
          level: 'error',
          message: 'No task selected. Please select or create a task first.'
        })
        return
      }

      // Validate that we have a strategy file
      if (!this.currentStrategyFilePath) {
        this.backtestMessages.push({
          timestamp: new Date().toISOString(),
          level: 'error',
          message: 'No strategy file selected. Please select a strategy first.'
        })
        return
      }

      // Validate form data
      if (!formData.source || !formData.symbol || !formData.timeframe || !formData.dateFrom || !formData.dateTo) {
        this.backtestMessages.push({
          timestamp: new Date().toISOString(),
          level: 'error',
          message: 'Please fill in all required fields: Source, Symbol, Timeframe, Date From, Date To'
        })
        return
      }

      // Save current task before starting backtest
      try {
        await this.saveAll()
      } catch (error) {
        console.error('Failed to save before starting backtest:', error)
        this.backtestMessages.push({
          timestamp: new Date().toISOString(),
          level: 'error',
          message: `Failed to save task before starting backtest: ${error.message}`
        })
        return
      }

      // Set running flag
      this.isBacktestingRunning = true
      this._resetBacktestProgress()

      // Add info message
      this.backtestMessages.push({
        timestamp: new Date().toISOString(),
        level: 'info',
        message: `Starting backtesting for task ${this.currentTaskId}...`
      })

      try {
        // Call API to start backtesting
        await backtestingApi.startBacktest(this.currentTaskId)

        // Open WebSocket to receive backtest results and progress
        this._openBacktestResultsSocket(this.currentTaskId)

        // Add success message
        this.backtestMessages.push({
          timestamp: new Date().toISOString(),
          level: 'success',
          message: `Backtesting started successfully for task ${this.currentTaskId}`
        })
      } catch (error) {
        console.error('Failed to start backtesting:', error)
        const errorMessage = error.response?.data?.detail || error.message || 'Unknown error'
        this.backtestMessages.push({
          timestamp: new Date().toISOString(),
          level: 'error',
          message: `Failed to start backtesting: ${errorMessage}`
        })
      } finally {
        // isBacktestingRunning will be reset when results stream finishes or on error
      }
    },
    async handleStop() {
      // Validate that we have a current task
      if (!this.currentTaskId) {
        this.backtestMessages.push({
          timestamp: new Date().toISOString(),
          level: 'error',
          message: 'No task selected. Cannot stop backtesting.'
        })
        return
      }

      try {
        // Call API to stop backtesting
        // All UI changes will happen via WebSocket packets (error packet)
        await backtestingApi.stopBacktest(this.currentTaskId)
      } catch (error) {
        console.error('Failed to stop backtesting:', error)
        const errorMessage = error.response?.data?.detail || error.message || 'Unknown error'
        this.backtestMessages.push({
          timestamp: new Date().toISOString(),
          level: 'error',
          message: `Failed to stop backtesting: ${errorMessage}`
        })
      }
    },
    async handleUpdateParameters() {
      // Update parameters description from strategy
      if (!this.currentStrategyName || !this.isStrategyLoaded) {
        return
      }
      
      try {
        // Save strategy first to ensure we get the latest parameters
        await strategiesApi.saveStrategy(this.currentStrategyFilePath, this.strategyCode)
        
        // Mark as saved after successful save
        this.hasUnsavedChanges = false
        
        // Now load strategy to get updated parameters
        await this.refreshParametersDescription()
      } catch (error) {
        console.error('Failed to update parameters:', error)
        // Add error message to panel
        this.backtestMessages.push({
          timestamp: new Date().toISOString(),
          level: 'error',
          message: `Failed to update parameters: ${error.message}`
        })
      }
    },
    async refreshParametersDescription() {
      // Refresh parameters description from strategy file
      if (!this.currentStrategyFilePath) {
        return
      }

      try {
        const strategy = await strategiesApi.loadStrategy(this.currentStrategyFilePath)
        
        // Remove old loading error messages first
        this.backtestMessages = this.backtestMessages.filter(
          msg => !msg.message.startsWith('Failed to load parameters:')
        )
        
        // Only update if parameters were successfully loaded (no errors)
        if (strategy.loading_errors && strategy.loading_errors.length > 0) {
          // Don't update parameters if there are errors
          this.strategyParametersDescription = null
          // Add loading errors
          strategy.loading_errors.forEach(error => {
            this.backtestMessages.push({
              timestamp: new Date().toISOString(),
              level: 'error',
              message: `Failed to load parameters: ${error}`
            })
          })
        } else if (strategy.parameters_description && Object.keys(strategy.parameters_description).length > 0) {
          // Update parameters only if no errors
          this.strategyParametersDescription = strategy.parameters_description
        } else {
          this.strategyParametersDescription = null
        }
      } catch (error) {
        console.error('Failed to refresh parameters description:', error)
        this.backtestMessages.push({
          timestamp: new Date().toISOString(),
          level: 'error',
          message: `Failed to refresh parameters: ${error.message}`
        })
      }
    },
    handleFormDataChanged() {
      // Triggered when general parameters change in BacktestingNavForm
      // Auto-save task with debounce (5 seconds)
      // Only if task is fully loaded (not during loading)
      if (this.currentTaskId && !this.isTaskLoading) {
        if (this.taskSaveTimeout) {
          clearTimeout(this.taskSaveTimeout)
        }
        this.taskSaveTimeout = setTimeout(() => {
          this.saveCurrentTask()
        }, 5000)
      }
    },
    handleParametersChanged() {
      // Triggered when custom parameters change in StrategyParameters component
      // Auto-save task with debounce (5 seconds)
      // Only if task is fully loaded (not during loading)
      if (this.currentTaskId && !this.isTaskLoading) {
        if (this.taskSaveTimeout) {
          clearTimeout(this.taskSaveTimeout)
        }
        this.taskSaveTimeout = setTimeout(() => {
          this.saveCurrentTask()
        }, 5000)
      }
    },
    handleKeyDown(event) {
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
        if (this.currentStrategyFilePath && this.isStrategyLoaded && this.activeChartTab === 'strategy' && this.hasUnsavedChanges) {
          // If we're in CodeMirror, it should handle it, but prevent default anyway
          // If we're not in an input field, handle it
          if (isInCodeMirror || !isInputElement) {
            event.preventDefault()
            this.handleSaveStrategy()
          }
        }
      }
    },
    async handleSaveStrategy() {
      if (!this.currentStrategyFilePath || !this.isStrategyLoaded || this.isSavingStrategy || !this.hasUnsavedChanges) {
        return
      }
      
      // Clear auto-save timeout since we're saving manually
      if (this.saveTimeout) {
        clearTimeout(this.saveTimeout)
        this.saveTimeout = null
      }
      
      this.isSavingStrategy = true
      try {
        const success = await this.saveCurrentStrategy()
        // Show success message only if save was successful
        if (success) {
          this.backtestMessages.push({
            timestamp: new Date().toISOString(),
            level: 'success',
            message: 'Strategy saved successfully'
          })
        }
      } catch (error) {
        // Error is already handled in saveCurrentStrategy
        console.error('Failed to save strategy:', error)
      } finally {
        this.isSavingStrategy = false
      }
    },
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
  transition: width 0.2s ease-out;
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
