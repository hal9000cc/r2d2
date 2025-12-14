<template>
  <div class="backtesting-view">
    <!-- Teleport form to navbar -->
    <Teleport to="#navbar-content-slot">
      <BacktestingNavForm 
        ref="navForm" 
        :disabled="!currentStrategyName"
        @start="handleStart"
        @form-data-changed="handleFormDataChanged"
      />
    </Teleport>
    
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
              <div v-if="activeChartTab === 'strategy' && !currentStrategyName" class="header-actions">
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
                v-if="activeChartTab === 'strategy' && !currentStrategyName"
                ref="taskList"
                :select-mode="selectMode"
                @strategy-created="handleStrategyCreated"
                @task-selected="handleTaskSelected"
                @selection-changed="handleSelectionChanged"
              />
              <CodeMirrorEditor
                v-if="activeChartTab === 'strategy' && currentStrategyName && isStrategyLoaded"
                v-model="strategyCode"
                language="python"
              />
              <div v-if="activeChartTab === 'strategy' && currentStrategyName && !isStrategyLoaded" class="strategy-error">
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
          <template #messages>
            <MessagesPanel :messages="backtestMessages" />
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
          <BacktestResults />
        </div>
      </ResizablePanel>
    </div>
  </div>
</template>

<script>
import ResizablePanel from '../components/ResizablePanel.vue'
import ChartPanel from '../components/ChartPanel.vue'
import MessagesPanel from '../components/MessagesPanel.vue'
import BacktestingNavForm from '../components/BacktestingNavForm.vue'
import StrategyParameters from '../components/StrategyParameters.vue'
import BacktestResults from '../components/BacktestResults.vue'
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
    MessagesPanel,
    BacktestingNavForm,
    StrategyParameters,
    BacktestResults,
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
      strategyCode: '',
      activeChartTab: 'strategy',
      currentStrategyName: null,
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
      selectedTasksCount: 0
    }
  },
  mounted() {
    this.calculateSizes()
    window.addEventListener('resize', this.calculateSizes)
    // Save on page close
    window.addEventListener('beforeunload', this.handleBeforeUnload)
  },
  beforeUnmount() {
    window.removeEventListener('resize', this.calculateSizes)
    window.removeEventListener('beforeunload', this.handleBeforeUnload)
    // Clear auto-save timers
    if (this.saveTimeout) {
      clearTimeout(this.saveTimeout)
    }
    if (this.taskSaveTimeout) {
      clearTimeout(this.taskSaveTimeout)
    }
    // Save all on component unmount
    this.saveAllSync()
  },
  watch: {
    strategyCode(newValue) {
      // Auto-save strategy with debounce (5 seconds after last change)
      // Only if task is fully loaded (not during loading)
      if (this.currentStrategyName && this.isStrategyLoaded && !this.isTaskLoading) {
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
      this.isStrategyLoaded = false
      this.strategyCode = ''
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
      // Handle tab change if needed
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
      if (freshTask.strategy_id) {
        this.currentStrategyName = freshTask.strategy_id
        this.strategyLoadError = null
        await this.loadStrategyFile(freshTask.strategy_id)
      } else {
        this.currentStrategyName = null
        this.isStrategyLoaded = false
        this.strategyCode = ''
        this.strategyLoadError = null
        this.currentTaskParameters = null
      }
      
      // 9. Enable auto-save timers at the end (after all loading is complete)
      this.isTaskLoading = false
    },
    async loadStrategyFile(strategyName) {
      try {
        // Try to load strategy file
        const strategy = await strategiesApi.loadStrategy(strategyName)
        
        if (strategy && strategy.text) {
          this.strategyCode = strategy.text
          this.isStrategyLoaded = true
          this.strategyLoadError = null
          this.previousStrategyName = strategyName
          
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
        this.strategyParametersDescription = null
        
        // Set error message for display
        if (error.response) {
          if (error.response.status === 404) {
            const detail = error.response.data?.detail || ''
            this.strategyLoadError = detail || `Strategy file "${strategyName}.py" not found in strategies directory`
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
        return
      }

      try {
        const response = await strategiesApi.saveStrategy(this.currentStrategyName, this.strategyCode)
        
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
      } catch (error) {
        console.error('Failed to save strategy:', error)
        // Add error message to panel
        this.backtestMessages.push({
          timestamp: new Date().toISOString(),
          level: 'error',
          message: `Failed to save strategy: ${error.message}`
        })
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
        const taskData = {
          strategy_id: this.currentStrategyName || '',
          name: this.currentTask?.name || '',
          source: formData.source || '',
          symbol: formData.symbol || '',
          timeframe: this.currentTask?.timeframe || '',
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
      if (!this.currentStrategyName || !this.isStrategyLoaded) {
        return
      }

      try {
        // Save strategy using sendBeacon or sync XHR
        const strategyData = JSON.stringify({
          name: this.currentStrategyName,
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

          const taskData = JSON.stringify({
            strategy_id: this.currentStrategyName || '',
            name: this.currentTask?.name || '',
            source: formData.source || '',
            symbol: formData.symbol || '',
            timeframe: this.currentTask?.timeframe || '',
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
    handleStart(formData) {
      console.log('Start backtesting with:', formData)
      // TODO: Implement backtesting start logic
    },
    async handleUpdateParameters() {
      // Update parameters description from strategy
      if (!this.currentStrategyName || !this.isStrategyLoaded) {
        return
      }
      
      try {
        // Save strategy first to ensure we get the latest parameters
        await strategiesApi.saveStrategy(this.currentStrategyName, this.strategyCode)
        
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
      if (!this.currentStrategyName) {
        return
      }

      try {
        const strategy = await strategiesApi.loadStrategy(this.currentStrategyName)
        
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
  }
}
</script>

<style scoped>
.backtesting-view {
  width: 100%;
  height: 100%;
  overflow: hidden;
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
