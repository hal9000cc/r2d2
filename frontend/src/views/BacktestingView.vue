<template>
  <div class="backtesting-view">
    <!-- Teleport form to navbar -->
    <Teleport to="#navbar-content-slot">
      <BacktestingNavForm 
        ref="navFormRef" 
        :disabled="buttonDisabled"
        :is-running="isBacktestingRunning"
        :add-message="addLocalMessage"
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
              <!-- Chart controls -->
              <div v-if="activeChartTab === 'chart'" class="header-actions chart-controls">
                <!-- Go to start button -->
                <button
                  class="chart-control-btn"
                  @click="handleGoToStart"
                  title="Go to start (Home)"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="icon-small">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
                    <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 19.5L.75 12l7.5-7.5" />
                  </svg>
                </button>
                <!-- Date/time input and Go button -->
                <div class="chart-date-input-wrapper">
                  <div class="chart-date-fields">
                    <input
                      type="number"
                      v-model.number="chartDateFields.year"
                      class="chart-date-field chart-date-field-year"
                      placeholder="YYYY"
                      min="1000"
                      max="9999"
                      @keyup.enter="handleGoToDate"
                      title="Year (optional)"
                    />
                    <span class="chart-date-separator">-</span>
                    <input
                      type="number"
                      v-model.number="chartDateFields.month"
                      class="chart-date-field"
                      placeholder="MM"
                      min="1"
                      max="12"
                      @keyup.enter="handleGoToDate"
                      title="Month (optional)"
                    />
                    <span class="chart-date-separator">-</span>
                    <input
                      type="number"
                      v-model.number="chartDateFields.day"
                      class="chart-date-field"
                      placeholder="DD"
                      min="1"
                      max="31"
                      @keyup.enter="handleGoToDate"
                      title="Day (optional)"
                    />
                    <span class="chart-date-separator"> </span>
                    <input
                      type="number"
                      v-model.number="chartDateFields.hours"
                      class="chart-date-field"
                      placeholder="HH"
                      min="0"
                      max="23"
                      @keyup.enter="handleGoToDate"
                      title="Hours (optional)"
                    />
                    <span class="chart-date-separator">:</span>
                    <input
                      type="number"
                      v-model.number="chartDateFields.minutes"
                      class="chart-date-field"
                      placeholder="mm"
                      min="0"
                      max="59"
                      @keyup.enter="handleGoToDate"
                      title="Minutes (optional)"
                    />
                  </div>
                  <button
                    class="chart-control-btn"
                    @click="handleGoToDate"
                    title="Go to date"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="icon-small">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
                    </svg>
                  </button>
                </div>
                <!-- Go to end button -->
                <button
                  class="chart-control-btn"
                  @click="handleGoToEnd"
                  title="Go to end (End)"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="icon-small">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                    <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 4.5l7.5 7.5-7.5 7.5" />
                  </svg>
                </button>
                <!-- Toggle log scale button -->
                <button
                  class="chart-control-btn"
                  @click="handleToggleLogScale"
                  :class="{ active: isLogScale }"
                  title="Toggle logarithmic scale"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="icon-small">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
                  </svg>
                </button>
                <!-- Auto scale button -->
                <button
                  class="chart-control-btn"
                  @click="handleAutoScale"
                  title="Auto scale"
                >
                  <span class="chart-control-letter">A</span>
                </button>
                <!-- Settings button with dropdown -->
                <div class="chart-settings-wrapper" ref="chartSettingsRef">
                  <button
                    class="chart-control-btn"
                    @click="toggleChartSettings"
                    title="Chart settings"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="icon-small">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z" />
                      <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    </svg>
                  </button>
                  <!-- Dropdown menu -->
                  <div v-if="isChartSettingsOpen" class="chart-settings-dropdown">
                    <label class="settings-option">
                      <input 
                        type="checkbox" 
                        v-model="showTradeMarkers"
                        @change="saveChartSettings"
                      />
                      <span>Show trades</span>
                    </label>
                    <label class="settings-option">
                      <input 
                        type="checkbox" 
                        v-model="showDealLines"
                        @change="saveChartSettings"
                      />
                      <span>Show deals</span>
                    </label>
                    <label class="settings-option">
                      <input 
                        type="checkbox" 
                        v-model="showIndicators"
                        @change="saveChartSettings"
                      />
                      <span>Show indicators</span>
                    </label>
                  </div>
                </div>
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
                ref="chartPanelRef"
                :source="currentTask?.source || null"
                :symbol="currentTask?.symbol || null"
                :timeframe="currentTask?.timeframe || null"
                :backtesting-progress="backtestingProgressData"
                :clear-chart="clearChartFlag"
                :task-id="currentTaskId"
                :show-trade-markers="showTradeMarkers"
                :show-deal-lines="showDealLines"
                :show-indicators="showIndicators"
                @chart-cleared="handleChartCleared"
                @quotes-load-error="handleQuotesLoadError"
                @chart-message="handleChartMessage"
                @log-scale-changed="isLogScale = $event"
                @chart-error="handleChartError"
              />
            </template>
          </Tabs>
        </ResizablePanel>
        <Tabs
          :tabs="tabsWithBadge"
          default-tab="deals"
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
            <div v-if="activeTab === 'orders'" class="header-actions">
              <label class="checkbox-label">
                <input 
                  type="checkbox" 
                  v-model="hideCanceledOrders"
                  class="checkbox-input"
                />
                <span>Hide inactive/untraded orders</span>
              </label>
            </div>
          </template>
          <template #messages>
            <MessagesPanel :messages="allMessages" />
          </template>
          <template #trades>
            <DataTable 
              ref="tradesTableRef"
              :columns="tradesColumns"
              :data="allTrades"
              row-key="trade_id"
              :row-class="getTradesRowClass"
              empty-message="No trades yet"
              :enabled="activeTab === 'trades'"
              :on-row-selected="handleTradeSelected"
            />
          </template>
          <template #deals>
            <DataTable 
              ref="dealsTableRef"
              :columns="dealsColumns"
              :data="dealsArray"
              row-key="deal_id"
              :row-class="getDealsRowClass"
              empty-message="No deals yet"
              :enabled="activeTab === 'deals'"
              :on-row-selected="handleDealSelected"
            />
          </template>
          <template #orders>
            <DataTable 
              ref="ordersTableRef"
              :columns="ordersColumns"
              :data="filteredOrders"
              row-key="order_id"
              :row-class="getOrdersRowClass"
              empty-message="No orders yet"
              :enabled="activeTab === 'orders'"
              :on-row-selected="handleOrderSelected"
            />
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
          <div class="stats-panel">
            <BacktestingStats :stats="stats" />
          </div>
        </div>
      </ResizablePanel>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick, provide, inject } from 'vue'
import ResizablePanel from '../components/ResizablePanel.vue'
import ChartPanel from '../components/ChartPanel.vue'
import MessagesPanel from '../components/MessagesPanel.vue'
import DataTable from '../components/DataTable.vue'
import BacktestingNavForm from '../components/BacktestingNavForm.vue'
import StrategyParameters from '../components/StrategyParameters.vue'
import BacktestingStats from '../components/BacktestingStats.vue'
import Tabs from '../components/Tabs.vue'
import CodeMirrorEditor from '../components/CodeMirrorEditor.vue'
import BacktestingTaskList from '../components/BacktestingTaskList.vue'
import { strategiesApi } from '../services/strategiesApi'
import { backtestingApi } from '../services/backtestingApi'
import { useBacktesting } from '../composables/useBacktesting'
import { useBacktestingResults } from '../composables/useBacktestingResults'
import { useAlert } from '../composables/useAlert'

// Inject timeframes composable
const timeframesComposable = inject('timeframes')

// Layout state
const chartHeight = ref(null)
const chartMaxHeight = ref(null)
const rightPanelWidth = ref(250)
const rightPanelMaxWidth = ref(null)
const parametersHeight = ref(null)
const parametersMaxHeight = ref(null)
const resultsHeight = ref(null)
const resultsMaxHeight = ref(null)

// Tabs
const chartTabs = computed(() => {
  const tabs = [{ id: 'strategy', label: 'Strategy' }]
  // Only show Chart tab if strategy is selected
  if (currentStrategyFilePath.value) {
    tabs.push({ id: 'chart', label: 'Chart' })
  }
  return tabs
})
const tabs = [
  { id: 'deals', label: 'Deals' },
  { id: 'trades', label: 'Trades' },
  { id: 'orders', label: 'Orders' },
  { id: 'messages', label: 'Messages' }
]
const activeTab = ref('deals')

// Unread important messages counter
const unreadImportantMessagesCount = ref(0)
const lastProcessedMessageIndex = ref(-1) // Track last processed message index
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
const clearChartFlag = ref(false) // Flag to trigger chart clearing

// Computed: backtesting progress data for chart
const backtestingProgressData = computed(() => {
  if (backtestProgressDateStart.value && backtestProgressCurrentTime.value) {
    const data = {
      date_start: backtestProgressDateStart.value,
      current_time: backtestProgressCurrentTime.value
    }
    // Add date_end if available (from backtesting_completed)
    if (backtestProgressDateEnd.value) {
      data.date_end = backtestProgressDateEnd.value
    }
    return data
  }
  return null
})

// Component refs
const navFormRef = ref(null)
const taskListRef = ref(null)
const strategyParametersRef = ref(null)
const chartPanelRef = ref(null)
const tradesTableRef = ref(null)
const dealsTableRef = ref(null)

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
  backtestProgressDateEnd,
  backtestProgressResultId,
  clearMessages,
  clearAllMessages,
  addLocalMessage,
  setBacktestingStarted,
  resetBacktestingState,
  ensureConnection
} = useBacktesting(currentTaskId)

// Use backtesting results composable
const backtestingResults = useBacktestingResults()
const {
  resultId,
  resultsRelevanceTime,
  trades,
  deals,
  tradesCount,
  dealsCount,
  allTrades,
  stats,
  clearResults,
  setResultId,
  setRelevanceTime,
  addTrades,
  updateDeals,
  updateOrders,
  updateStats,
  getAllDeals,
  getAllTrades,
  getAllOrders
} = backtestingResults

// Provide backtesting results to child components
provide('backtestingResults', backtestingResults)

// Use alert system
const { showAlert } = useAlert()

// Table columns definitions
const tradesColumns = [
  { key: 'trade_id', label: 'Trade ID', width: '80px' },
  { key: 'deal_id', label: 'Deal ID', width: '80px' },
  { key: 'order_id', label: 'Order ID', width: '80px' },
  { 
    key: 'time', 
    label: 'Time',
    format: (value) => {
      if (!value) return '—'
      const date = new Date(value)
      return date.toISOString().replace('T', ' ').substring(0, 19)
    }
  },
  { 
    key: 'side', 
    label: 'Side',
    width: '60px',
    format: (value) => value ? value.toUpperCase() : '—'
  },
  { 
    key: 'price', 
    label: 'Price',
    class: 'align-right',
    format: (value) => value ? parseFloat(value).toFixed(8) : '—'
  },
  { 
    key: 'quantity', 
    label: 'Quantity',
    class: 'align-right',
    format: (value) => value ? parseFloat(value).toFixed(8) : '—'
  },
  { 
    key: 'fee', 
    label: 'Fee',
    class: 'align-right',
    format: (value) => value ? parseFloat(value).toFixed(8) : '—'
  },
  { 
    key: 'sum', 
    label: 'Sum',
    class: 'align-right',
    format: (value) => value ? parseFloat(value).toFixed(8) : '—'
  }
]

const dealsColumns = [
  { key: 'deal_id', label: 'Deal ID', width: '80px' },
  { 
    key: 'type', 
    label: 'Type', 
    width: '100px',
    format: (value) => value ? value.toUpperCase() : '—'
  },
  { 
    key: 'avg_buy_price', 
    label: 'Avg Buy Price',
    class: 'align-right',
    format: (value) => value ? parseFloat(value).toFixed(8) : '—'
  },
  { 
    key: 'avg_sell_price', 
    label: 'Avg Sell Price',
    class: 'align-right',
    format: (value) => value ? parseFloat(value).toFixed(8) : '—'
  },
  { 
    key: 'quantity', 
    label: 'Quantity',
    class: 'align-right',
    format: (value) => value ? parseFloat(value).toFixed(8) : '—'
  },
  { 
    key: 'profit_net', 
    label: 'Profit gross',
    class: 'align-right',
    format: (value, row) => {
      const profit = row.profit ? parseFloat(row.profit) : 0
      const fee = row.fee ? parseFloat(row.fee) : 0
      const profitNet = profit + fee
      return profitNet.toFixed(8)
    }
  },
  { 
    key: 'fee', 
    label: 'Fee',
    class: 'align-right',
    format: (value) => value ? parseFloat(value).toFixed(8) : '—'
  },
  { 
    key: 'profit', 
    label: 'Profit',
    class: 'align-right',
    format: (value) => value ? parseFloat(value).toFixed(8) : '—'
  },
  { 
    key: 'is_closed', 
    label: 'Status',
    width: '80px',
    class: (row) => row.is_closed ? 'status-closed' : 'status-open',
    format: (value) => value ? 'Closed' : 'Open'
  }
]

const ordersColumns = [
  { key: 'order_id', label: 'Order ID', width: '80px' },
  { key: 'deal_id', label: 'Deal ID', width: '80px' },
  { 
    key: 'order_type', 
    label: 'Type',
    width: '80px',
    format: (value) => value ? value.toUpperCase() : '—'
  },
  { 
    key: 'create_time', 
    label: 'Create Time',
    format: (value) => {
      if (!value) return '—'
      const date = new Date(value)
      return date.toISOString().replace('T', ' ').substring(0, 19)
    }
  },
  { 
    key: 'modify_time', 
    label: 'Modify Time',
    format: (value) => {
      if (!value) return '—'
      const date = new Date(value)
      return date.toISOString().replace('T', ' ').substring(0, 19)
    }
  },
  { 
    key: 'side', 
    label: 'Side',
    width: '60px',
    format: (value) => value ? value.toUpperCase() : '—'
  },
  { 
    key: 'price', 
    label: 'Price',
    class: 'align-right',
    format: (value) => value ? parseFloat(value).toFixed(8) : '—'
  },
  { 
    key: 'trigger_price', 
    label: 'Trigger Price',
    class: 'align-right',
    format: (value) => value ? parseFloat(value).toFixed(8) : '—'
  },
  { 
    key: 'volume', 
    label: 'Volume',
    class: 'align-right',
    format: (value) => value ? parseFloat(value).toFixed(8) : '—'
  },
  { 
    key: 'filled_volume', 
    label: 'Filled Volume',
    class: 'align-right',
    format: (value) => value ? parseFloat(value).toFixed(8) : '—'
  },
  { 
    key: 'status', 
    label: 'Status',
    width: '100px',
    format: (value) => {
      const statusMap = {
        0: 'New',
        1: 'Active',
        2: 'Executed',
        3: 'Canceled',
        4: 'Error'
      }
      return statusMap[value] || 'Unknown'
    }
  }
]

// Computed: deals as array for table
const dealsArray = computed(() => getAllDeals())

// Computed: orders as array for table
const allOrders = computed(() => getAllOrders())

// State for hiding canceled orders
const hideCanceledOrders = ref(false)

// Computed: filtered orders (hide inactive/untraded if checkbox is checked)
const filteredOrders = computed(() => {
  if (!hideCanceledOrders.value) {
    return allOrders.value
  }
  // Show only orders with status ACTIVE (1) or with filled_volume != 0
  return allOrders.value.filter(order => {
    const filledVolume = parseFloat(order.filled_volume) || 0
    return order.status === 1 || filledVolume !== 0
  })
})

// Row class functions for table row coloring
function getTradesRowClass(row) {
  if (row.side === 'buy') {
    return 'row-buy'
  } else if (row.side === 'sell') {
    return 'row-sell'
  }
  return ''
}

function getDealsRowClass(row) {
  // Color by profit: profitable (green) vs unprofitable (red)
  if (row.profit !== null && row.profit !== undefined) {
    const profit = parseFloat(row.profit)
    if (profit > 0) {
      return 'row-buy'  // Green for profitable
    } else if (profit < 0) {
      return 'row-sell'  // Red for unprofitable
    }
  }
  return ''
}

function getOrdersRowClass(row) {
  // Check for cancelled/error orders (status CANCELED or ERROR with filled_volume = 0)
  const filledVolume = parseFloat(row.filled_volume) || 0
  if ((row.status === 3 || row.status === 4) && filledVolume === 0) {
    return 'row-inactive'
  }
  
  // Color by side for active or partially executed orders
  if (row.side === 'buy') {
    return 'row-buy'
  } else if (row.side === 'sell') {
    return 'row-sell'
  }
  return ''
}

function handleOrderSelected(order) {
  // Optional: handle order selection
  // Similar to handleTradeSelected or handleDealSelected
}

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

// Computed: tabs with unread badge for Messages tab
const tabsWithBadge = computed(() => {
  return tabs.map(tab => {
    if (tab.id === 'messages' && unreadImportantMessagesCount.value > 0) {
      return {
        ...tab,
        badge: unreadImportantMessagesCount.value
      }
    }
    return tab
  })
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

// Watch activeTab to reset unread counter when Messages tab is opened
watch(activeTab, (newTab) => {
  if (newTab === 'messages') {
    // Reset counter and update last processed index when Messages tab is opened
    unreadImportantMessagesCount.value = 0
    lastProcessedMessageIndex.value = allMessages.value.length - 1
  }
})

// Watch allMessages to count new important messages when Messages tab is closed
watch(allMessages, (newMessages, oldMessages) => {
  // Handle case when messages are cleared (array becomes shorter)
  if (newMessages.length < oldMessages.length) {
    // Reset counter and index when messages are cleared
    unreadImportantMessagesCount.value = 0
    lastProcessedMessageIndex.value = -1
  }
  
  // Only count if Messages tab is not active
  if (activeTab.value !== 'messages') {
    // Process only new messages (after lastProcessedMessageIndex)
    const startIndex = lastProcessedMessageIndex.value + 1
    for (let i = startIndex; i < newMessages.length; i++) {
      const message = newMessages[i]
      // Check if message is important (error, critical, or warning level)
      if (message.level === 'error' || message.level === 'critical' || message.level === 'warning') {
        unreadImportantMessagesCount.value++
      }
    }
    // Update last processed index
    lastProcessedMessageIndex.value = newMessages.length - 1
  } else {
    // If Messages tab is active, just update last processed index without counting
    lastProcessedMessageIndex.value = newMessages.length - 1
  }
}, { deep: true })

/**
 * Load backtesting results from API
 * @param {string|null} fromTime - Start time for loading (ISO string or null for all)
 * @returns {Promise<boolean>} True if loaded successfully, false otherwise
 */
async function loadBacktestingResults(fromTime = null) {
  if (!currentTaskId.value || !resultId.value) {
    return false
  }
  
  try {
    ensureConnection()
    const response = await backtestingApi.getBacktestingResults(
      currentTaskId.value,
      resultId.value,
      fromTime || resultsRelevanceTime.value
    )
    
    if (response.success && response.data) {
      // Add trades (avoid duplicates)
      let addedTrades = []
      if (response.data.trades && response.data.trades.length > 0) {
        addedTrades = addTrades(response.data.trades)
      }
      
      // Update deals (add or update)
      if (response.data.deals && response.data.deals.length > 0) {
        updateDeals(response.data.deals)
      }
      
      // Update orders (add or update)
      if (response.data.orders && response.data.orders.length > 0) {
        updateOrders(response.data.orders)
      }
      
      // Update statistics
      if (response.data.stats) {
        updateStats(response.data.stats)
      }
      
      // Update relevance time with current_time from progress
      // We only update if we have current_time to ensure we track what we've actually loaded
      if (backtestProgressCurrentTime.value) {
        setRelevanceTime(backtestProgressCurrentTime.value)
      }
      
      // Update indicator series after loading results
      chartPanelRef.value?.updateIndicatorSeries()
      
      return true
    } else if (!response.success) {
      console.error('Failed to load backtesting results:', response.error_message)
      addLocalMessage({
        level: 'error',
        message: `Failed to load backtesting results: ${response.error_message || 'Unknown error'}`
      })
      return false
    }
    return false
  } catch (error) {
    console.error('Error loading backtesting results:', error)
    addLocalMessage({
      level: 'error',
      message: `Error loading backtesting results: ${error.message || 'Unknown error'}`
    })
    return false
  }
}

/**
 * Validate that backtesting results are complete
 * Checks completed flag and counts match
 */
function validateResultsCompleteness() {
  // Check if stats are loaded
  if (!stats.value) {
    addLocalMessage({
      level: 'error',
      message: 'Backtesting results are incomplete: statistics not loaded'
    })
    return false
  }
  
  // Check completed flag
  if (stats.value.completed !== true) {
    addLocalMessage({
      level: 'error',
      message: 'Backtesting results are incomplete: final results not saved to Redis'
    })
    return false
  }
  
  // Check trades count
  if (tradesCount.value !== stats.value.total_trades) {
    addLocalMessage({
      level: 'error',
      message: `Backtesting results are incomplete: trades count mismatch (loaded: ${tradesCount.value}, expected: ${stats.value.total_trades})`
    })
    return false
  }
  
  // Check deals count
  if (dealsCount.value !== stats.value.total_deals) {
    addLocalMessage({
      level: 'error',
      message: `Backtesting results are incomplete: deals count mismatch (loaded: ${dealsCount.value}, expected: ${stats.value.total_deals})`
    })
    return false
  }
  
  return true
}

// Watch for backtesting progress to load results
watch([backtestProgressCurrentTime, backtestProgressResultId], async ([newCurrentTime, newResultId], [oldCurrentTime, oldResultId]) => {
  // Only load results if:
  // 1. We have a current time (progress event received)
  // 2. We have a result_id
  // 3. Current time changed (new progress event)
  // 4. result_id matches our local result_id (not from another backtesting run)
  if (!newCurrentTime || !newResultId || !resultId.value) {
    return
  }
  
  // Check if result_id from event matches our local result_id
  if (newResultId !== resultId.value) {
    // Ignore events from other backtesting runs
    return
  }
  
  // Check if current time changed
  if (newCurrentTime === oldCurrentTime) {
    return
  }
  
  // Load results from last relevance time to current time
  await loadBacktestingResults()
})

// Watch for backtesting completion to load and validate final results
watch(backtestProgressState, async (newState) => {
  // Only process when backtesting is completed
  if (newState !== 'completed') {
    return
  }
  
  // Check result_id matches
  if (!backtestProgressResultId.value || !resultId.value || backtestProgressResultId.value !== resultId.value) {
    return
  }
  
  // Check if we already have results loaded
  const hasResults = stats.value !== null
  
  if (hasResults) {
    // Check if results are complete
    const isComplete = stats.value.completed === true && 
                       tradesCount.value === stats.value.total_trades &&
                       dealsCount.value === stats.value.total_deals
    
    if (isComplete) {
      // Results are already complete, just validate
      validateResultsCompleteness()
      return
    }
    // Results exist but are incomplete - need to load missing data
      }
      
  // Load results (either we don't have them or they're incomplete)
  const loaded = await loadBacktestingResults()
  
  if (loaded) {
    // Validate completeness after loading
    validateResultsCompleteness()
    // Update indicator series after loading final results
    chartPanelRef.value?.updateIndicatorSeries()
  } else {
    // Loading failed, but try to validate what we have (if any)
    if (stats.value) {
      validateResultsCompleteness()
    }
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
  // Add centralized keyboard navigation handler
  window.addEventListener('keydown', handleGlobalKeyboard)
  // Load chart settings from localStorage
  loadChartSettings()
  // Add click outside listener for settings dropdown
  document.addEventListener('click', handleClickOutsideSettings)
  
  // Initialize last processed message index
  lastProcessedMessageIndex.value = allMessages.value.length - 1
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', calculateSizes)
  window.removeEventListener('beforeunload', handleBeforeUnload)
  document.removeEventListener('keydown', handleKeyDown)
  window.removeEventListener('keydown', handleGlobalKeyboard)
  document.removeEventListener('click', handleClickOutsideSettings)
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
  
  // Calculate parameters and results panel heights
  const resultsMinHeight = 150
  const parametersMinHeight = 150
  
  // Maximum height for parameters is available height minus minimum results height
  parametersMaxHeight.value = availableHeight - resultsMinHeight
  
  // Maximum height for results is available height minus minimum parameters height
  resultsMaxHeight.value = availableHeight - parametersMinHeight
  
  // Initialize parameters height
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
  
  // Initialize results height
  if (resultsHeight.value === null) {
    const savedResultsHeight = localStorage.getItem('backtesting-results-height')
    if (savedResultsHeight) {
      const savedHeight = parseInt(savedResultsHeight, 10)
      resultsHeight.value = Math.min(savedHeight, resultsMaxHeight.value)
    } else {
      // Default: remaining height for results
      resultsHeight.value = availableHeight - parametersHeight.value
    }
  } else {
    if (resultsHeight.value > resultsMaxHeight.value) {
      resultsHeight.value = resultsMaxHeight.value
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
  localStorage.setItem('backtesting-parameters-height', size.toString())
  // Update results height to fill remaining space
  const availableHeight = rightPanelMaxWidth.value ? 
    Math.floor((window.innerHeight - 60) * 0.95) : 
    Math.floor((window.innerHeight - 60) * 0.95)
  const newResultsHeight = availableHeight - size
  if (newResultsHeight >= 150) { // min size for results
    resultsHeight.value = newResultsHeight
  }
}

function handleResultsResize(size) {
  resultsHeight.value = size
  localStorage.setItem('backtesting-results-height', size.toString())
}

function handleChartTabChange(tabId) {
  // If chart tab is selected but strategy is closed, switch back to strategy
  if (tabId === 'chart' && !currentStrategyFilePath.value) {
    activeChartTab.value = 'strategy'
    return
  }
  activeChartTab.value = tabId
  
  // When switching to chart tab, update indicator series if results are available
  if (tabId === 'chart') {
    nextTick(() => {
      chartPanelRef.value?.updateIndicatorSeries()
    })
  }
}

// Chart controls state
const chartDateInput = ref('') // Keep for backward compatibility, but use chartDateFields instead
const chartDateFields = ref({
  year: null,
  month: null,
  day: null,
  hours: null,
  minutes: null
})
const isLogScale = ref(false)
const isChartSettingsOpen = ref(false)
const chartSettingsRef = ref(null)
const showTradeMarkers = ref(true)
const showDealLines = ref(true)
const showIndicators = ref(true)

/**
 * Parse partial datetime input into object with optional fields
 * Supports formats: "YYYY-MM-DD HH:mm", "YYYY-MM-DDTHH:mm", "2024-01-15", "14:30", "15", etc.
 * @param {string} input - datetime input string
 * @returns {Object|null} Object with optional fields: { year?, month?, day?, hours?, minutes? } or null if invalid
 */
function parsePartialDateTime(input) {
  if (!input || typeof input !== 'string') {
    return null
  }
  
  const trimmed = input.trim()
  if (!trimmed) {
    return null
  }
  
  const result = {}
  // Split by 'T' or space (support both "2024-01-15T14:30" and "2024-01-15 14:30")
  const parts = trimmed.split(/[T\s]/)
  const hasDatePart = parts[0] && parts[0].trim() !== ''
  const hasTimePart = parts.length > 1 && parts[1] && parts[1].trim() !== ''
  
  // Parse date part (YYYY-MM-DD or YYYY-MM or YYYY or single number)
  if (hasDatePart) {
    const datePart = parts[0].trim()
    const dateParts = datePart.split('-').filter(p => p !== '')
    
    if (dateParts.length === 1) {
      // Single number: interpret as day (1-31), month (1-12), or year (1000-9999)
      const num = parseInt(dateParts[0], 10)
      if (!isNaN(num) && num > 0 && num <= 9999) {
        if (num >= 1000 && num <= 9999) {
          // Valid year range
          result.year = num
        } else if (num >= 1 && num <= 31) {
          // Interpret as day (most common case for partial date input)
          result.day = num
        } else if (num >= 1 && num <= 12) {
          // Could be month
          result.month = num
        }
      }
    } else if (dateParts.length > 1) {
      // Multiple parts with separators (YYYY-MM-DD or YYYY-MM or MM-DD)
      const first = parseInt(dateParts[0], 10)
      if (!isNaN(first) && first > 0 && first <= 9999) {
        if (first >= 1000 && first <= 9999) {
          // Valid year range
          result.year = first
        } else if (first >= 1 && first <= 12) {
          result.month = first
        }
      }
      
      if (dateParts.length > 1) {
        const second = parseInt(dateParts[1], 10)
        if (!isNaN(second)) {
          if (result.year !== undefined) {
            // YYYY-MM format
            if (second >= 1 && second <= 12) {
              result.month = second
            }
          } else if (result.month !== undefined) {
            // MM-DD format
            if (second >= 1 && second <= 31) {
              result.day = second
            }
          }
        }
      }
      
      if (dateParts.length > 2) {
        const third = parseInt(dateParts[2], 10)
        if (!isNaN(third) && third >= 1 && third <= 31) {
          result.day = third
        }
      }
    }
  }
  
  // Parse time part (HH:mm or HH or single number)
  if (hasTimePart) {
    const timePart = parts[1].trim()
    const timeParts = timePart.split(':').filter(p => p !== '')
    
    if (timeParts.length === 1) {
      // Single number: interpret as hours
      const num = parseInt(timeParts[0], 10)
      if (!isNaN(num) && num >= 0 && num <= 23) {
        result.hours = num
      }
    } else if (timeParts.length > 0) {
      // Multiple parts with colon (HH:mm)
      const hours = parseInt(timeParts[0], 10)
      if (!isNaN(hours) && hours >= 0 && hours <= 23) {
        result.hours = hours
      }
      if (timeParts.length > 1) {
        const minutes = parseInt(timeParts[1], 10)
        if (!isNaN(minutes) && minutes >= 0 && minutes <= 59) {
          result.minutes = minutes
        }
      }
    }
  }
  
  // Check if at least one field is present before special case
  let hasAnyField = 'year' in result || 'month' in result || 'day' in result || 'hours' in result || 'minutes' in result
  
  // Special case: if input is just a number without separators and no date/time parts were parsed
  // This handles cases where user types just "15" or similar
  if (!hasAnyField && !trimmed.includes('-') && !trimmed.includes(':') && !trimmed.includes('T') && !trimmed.includes(' ')) {
    const num = parseInt(trimmed, 10)
    if (!isNaN(num) && num > 0 && num <= 9999) {
      // Try to interpret as day (most common case for date input)
      if (num >= 1 && num <= 31) {
        result.day = num
      } else if (num >= 0 && num <= 23) {
        // Could be hour
        result.hours = num
      } else if (num >= 1000 && num <= 9999) {
        // Valid year range
        result.year = num
      }
    }
  }
  
  // Final check if at least one field is present
  const hasAnyFieldFinal = 'year' in result || 'month' in result || 'day' in result || 'hours' in result || 'minutes' in result
  return hasAnyFieldFinal ? result : null
}

/**
 * Merge partial datetime object with current time from chart
 * @param {Object} partial - Partial datetime object with optional fields
 * @param {number} currentTimestamp - Unix timestamp in seconds
 * @returns {Object} Complete datetime object with all fields
 */
function mergeWithCurrentTime(partial, currentTimestamp) {
  // Convert timestamp to Date object in UTC
  const currentDate = new Date(currentTimestamp * 1000)
  const currentUTC = {
    year: currentDate.getUTCFullYear(),
    month: currentDate.getUTCMonth() + 1, // getUTCMonth returns 0-11
    day: currentDate.getUTCDate(),
    hours: currentDate.getUTCHours(),
    minutes: currentDate.getUTCMinutes()
  }
  
  // Merge: use partial values if present, otherwise use current values
  return {
    year: partial.year !== undefined ? partial.year : currentUTC.year,
    month: partial.month !== undefined ? partial.month : currentUTC.month,
    day: partial.day !== undefined ? partial.day : currentUTC.day,
    hours: partial.hours !== undefined ? partial.hours : currentUTC.hours,
    minutes: partial.minutes !== undefined ? partial.minutes : currentUTC.minutes
  }
}

/**
 * Convert datetime object to Unix timestamp (seconds) in UTC
 * @param {Object} dateTime - Object with { year, month, day, hours, minutes }
 * @returns {number} Unix timestamp in seconds
 */
function dateTimeToTimestamp(dateTime) {
  // Use Date.UTC to create timestamp in UTC
  return Math.floor(Date.UTC(
    dateTime.year,
    dateTime.month - 1, // Date.UTC expects month 0-11
    dateTime.day,
    dateTime.hours,
    dateTime.minutes
  ) / 1000)
}

// Chart control handlers
function handleGoToDate() {
  if (!chartPanelRef.value) {
    showAlert('error', 'Chart is not available')
    return
  }
  
  // Build parsed object from individual fields
  const parsed = {}
  if (chartDateFields.value.year !== null && chartDateFields.value.year !== undefined && chartDateFields.value.year !== '') {
    parsed.year = Number(chartDateFields.value.year)
  }
  if (chartDateFields.value.month !== null && chartDateFields.value.month !== undefined && chartDateFields.value.month !== '') {
    parsed.month = Number(chartDateFields.value.month)
  }
  if (chartDateFields.value.day !== null && chartDateFields.value.day !== undefined && chartDateFields.value.day !== '') {
    parsed.day = Number(chartDateFields.value.day)
  }
  if (chartDateFields.value.hours !== null && chartDateFields.value.hours !== undefined && chartDateFields.value.hours !== '') {
    parsed.hours = Number(chartDateFields.value.hours)
  }
  if (chartDateFields.value.minutes !== null && chartDateFields.value.minutes !== undefined && chartDateFields.value.minutes !== '') {
    parsed.minutes = Number(chartDateFields.value.minutes)
  }
  
  // Check if at least one field is filled
  const hasAnyField = 'year' in parsed || 'month' in parsed || 'day' in parsed || 'hours' in parsed || 'minutes' in parsed
  if (!hasAnyField) {
    showAlert('error', 'Please enter at least one value (year, month, day, hour, or minute)')
    return
  }
  
  // Validate values are within reasonable ranges
  if (parsed.year !== undefined && (parsed.year < 1000 || parsed.year > 9999)) {
    showAlert('error', 'Year must be between 1000 and 9999')
    return
  }
  
  if (parsed.month !== undefined && (parsed.month < 1 || parsed.month > 12)) {
    showAlert('error', 'Month must be between 1 and 12')
    return
  }
  
  if (parsed.day !== undefined && (parsed.day < 1 || parsed.day > 31)) {
    showAlert('error', 'Day must be between 1 and 31')
    return
  }
  
  if (parsed.hours !== undefined && (parsed.hours < 0 || parsed.hours > 23)) {
    showAlert('error', 'Hours must be between 0 and 23')
    return
  }
  
  if (parsed.minutes !== undefined && (parsed.minutes < 0 || parsed.minutes > 59)) {
    showAlert('error', 'Minutes must be between 0 and 59')
    return
  }
  
  // Get current time from chart
  const currentTime = chartPanelRef.value.getChartCurrentTime()
  if (!currentTime) {
    showAlert('error', 'Chart is not loaded. Please wait for the chart to load or start backtesting first.')
    return
  }
  
  // Merge partial input with current time
  const finalDateTime = mergeWithCurrentTime(parsed, currentTime)
  
  // Convert to timestamp and navigate
  const timestamp = dateTimeToTimestamp(finalDateTime)
  chartPanelRef.value.goToTime(timestamp, true)
  
  // Write back the used values to fields for feedback
  chartDateFields.value = {
    year: finalDateTime.year,
    month: finalDateTime.month,
    day: finalDateTime.day,
    hours: finalDateTime.hours,
    minutes: finalDateTime.minutes
  }
}

function handleGoToStart() {
  if (chartPanelRef.value) {
    chartPanelRef.value.goToStart()
  }
}

function handleGoToEnd() {
  if (chartPanelRef.value) {
    chartPanelRef.value.goToEnd()
  }
}

function handleToggleLogScale() {
  if (chartPanelRef.value) {
    chartPanelRef.value.toggleLogScale()
    // isLogScale will be updated via @log-scale-changed event
  }
}

function handleAutoScale() {
  if (chartPanelRef.value) {
    chartPanelRef.value.autoScale()
  }
}

function toggleChartSettings() {
  isChartSettingsOpen.value = !isChartSettingsOpen.value
}

function saveChartSettings() {
  localStorage.setItem('chart-show-trade-markers', showTradeMarkers.value.toString())
  localStorage.setItem('chart-show-deal-lines', showDealLines.value.toString())
  localStorage.setItem('chart-show-indicators', showIndicators.value.toString())
}

function loadChartSettings() {
  const savedShowTrades = localStorage.getItem('chart-show-trade-markers')
  const savedShowDeals = localStorage.getItem('chart-show-deal-lines')
  const savedShowIndicators = localStorage.getItem('chart-show-indicators')
  
  if (savedShowTrades !== null) {
    showTradeMarkers.value = savedShowTrades === 'true'
  }
  if (savedShowDeals !== null) {
    showDealLines.value = savedShowDeals === 'true'
  }
  if (savedShowIndicators !== null) {
    showIndicators.value = savedShowIndicators === 'true'
  }
}

function handleClickOutsideSettings(event) {
  if (chartSettingsRef.value && !chartSettingsRef.value.contains(event.target)) {
    isChartSettingsOpen.value = false
  }
}

// ============================================================================
// KEYBOARD NAVIGATION HANDLER
// ============================================================================
/**
 * Global keyboard navigation handler - single point of control for all shortcuts
 * 
 * Keyboard layout:
 * 
 * CHART NAVIGATION (Shift + keys, active when activeChartTab === 'chart'):
 *   Shift+Home     - Go to chart start
 *   Shift+End      - Go to chart end  
 *   Shift+PageUp   - Scroll chart forward (to newer data)
 *   Shift+PageDown - Scroll chart backward (to older data)
 * 
 * TABLE NAVIGATION (no modifiers, active when activeTab === 'trades' or 'deals'):
 *   ArrowUp        - Select previous row
 *   ArrowDown      - Select next row
 *   PageUp         - Scroll table up one page
 *   PageDown       - Scroll table down one page
 *   Home           - Go to first row
 *   End            - Go to last row
 *   Escape         - Deselect current row
 */
function handleGlobalKeyboard(event) {
  // Filter: Ignore if typing in input fields
  if (event.target.tagName === 'INPUT' || 
      event.target.tagName === 'TEXTAREA' || 
      event.target.isContentEditable) {
    return
  }
  
  // Determine active context with priorities
  const context = determineActiveContext()
  
  // Route commands based on context and modifiers
  if (event.shiftKey) {
    // Shift + keys -> Chart navigation
    if (context.chart) {
      routeChartCommand(event)
    }
  } else {
    // No modifiers -> Table navigation has priority
    if (context.table) {
      routeTableCommand(event)
    }
  }
}

/**
 * Determine which context is currently active
 * @returns {Object} { chart: boolean, table: boolean, tableRef: ref }
 */
function determineActiveContext() {
  const context = {
    chart: false,
    table: false,
    tableRef: null
  }
  
  // Check if table is active (priority)
  if (activeTab.value === 'trades' && tradesTableRef.value) {
    context.table = true
    context.tableRef = tradesTableRef.value
  } else if (activeTab.value === 'deals' && dealsTableRef.value) {
    context.table = true
    context.tableRef = dealsTableRef.value
  }
  
  // Check if chart is active
  if (activeChartTab.value === 'chart') {
    context.chart = true
  }
  
  return context
}

/**
 * Route chart navigation commands
 * @param {KeyboardEvent} event 
 */
function routeChartCommand(event) {
  // Only handle Shift+key combinations
  if (!event.shiftKey) return
  
  // Ignore other modifiers
  if (event.ctrlKey || event.metaKey || event.altKey) return
  
  let handled = false
  
  switch (event.key) {
    case 'Home':
      handleGoToStart()
      handled = true
      break
    case 'End':
      handleGoToEnd()
      handled = true
      break
    case 'PageUp':
      // Scroll forward (to newer data)
      if (chartPanelRef.value) {
        chartPanelRef.value.pageDown()
      }
      handled = true
      break
    case 'PageDown':
      // Scroll backward (to older data)
      if (chartPanelRef.value) {
        chartPanelRef.value.pageUp()
      }
      handled = true
      break
  }
  
  if (handled) {
    event.preventDefault()
    event.stopImmediatePropagation()
  }
}

/**
 * Route table navigation commands
 * @param {KeyboardEvent} event
 */
function routeTableCommand(event) {
  const context = determineActiveContext()
  
  if (!context.table || !context.tableRef) return
  
  // Ignore modifiers for table navigation
  if (event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) return
  
  let handled = false
  
  switch (event.key) {
    case 'ArrowUp':
      context.tableRef.navigateUp()
      handled = true
      break
    case 'ArrowDown':
      context.tableRef.navigateDown()
      handled = true
      break
    case 'PageUp':
      context.tableRef.navigatePageUp()
      handled = true
      break
    case 'PageDown':
      context.tableRef.navigatePageDown()
      handled = true
      break
    case 'Home':
      context.tableRef.navigateHome()
      handled = true
      break
    case 'End':
      context.tableRef.navigateEnd()
      handled = true
      break
    case 'Escape':
      context.tableRef.deselect()
      handled = true
      break
  }
  
  if (handled) {
    event.preventDefault()
    event.stopImmediatePropagation()
  }
}

// ============================================================================

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
  
  // Reset chart tab to strategy (show task list)
  activeChartTab.value = 'strategy'
  
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

function handleTradeSelected(tradeId) {
  // Callback when a trade row is selected
  if (chartPanelRef.value) {
    chartPanelRef.value.goToTrade(tradeId, true)
  }
}

function handleDealSelected(dealId) {
  // Callback when a deal row is selected
  if (chartPanelRef.value) {
    chartPanelRef.value.goToDeal(dealId, true)
  }
}

function handleChartError(errorMessage) {
  // Handle chart errors (e.g., trade/deal not found)
  if (errorMessage) {
    showAlert('error', errorMessage)
  }
}

function handleChartCleared() {
  clearChartFlag.value = false
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
    ensureConnection()
    freshTask = await backtestingApi.getTask(task.id)
  } catch (error) {
    console.error('Failed to load fresh task data:', error)
    // Fallback to task from list if API call fails
  }

  // 5. Store current task info
  currentTaskId.value = freshTask.id
  // Convert timeframe string to Timeframe object
  const timeframeStr = freshTask.timeframe || ''
  const timeframeObj = timeframesComposable?.getTimeframe(timeframeStr) || null
  currentTask.value = {
    ...freshTask,
    timeframe: timeframeObj
  }
  
  // Clear chart when switching to a different task (new task may have different parameters)
  clearChartFlag.value = false
  await nextTick()
  clearChartFlag.value = true

  // 6. Update form with task data
  if (navFormRef.value) {
    // Set source first, then symbol in nextTick to avoid SymbolInput watcher clearing symbol
    navFormRef.value.formData.source = freshTask.source || ''
    
    // Set symbol after source watcher has processed (SymbolInput clears symbol on source change)
    nextTick(() => {
      navFormRef.value.formData.symbol = freshTask.symbol || ''
      // Convert string timeframe from API to Timeframe object
      const timeframeStr = freshTask.timeframe || ''
      navFormRef.value.formData.timeframe = timeframesComposable?.getTimeframe(timeframeStr) || null
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
    
    // Load fee, price step and slippage parameters
    navFormRef.value.formData.feeTaker = freshTask.fee_taker !== undefined ? freshTask.fee_taker : 0.0
    navFormRef.value.formData.feeMaker = freshTask.fee_maker !== undefined ? freshTask.fee_maker : 0.0
    navFormRef.value.formData.priceStep = freshTask.price_step !== undefined ? freshTask.price_step : 0.0
    navFormRef.value.formData.slippageInSteps = freshTask.slippage_in_steps !== undefined ? freshTask.slippage_in_steps : 1.0
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

  // Don't save during backtesting
  if (isBacktestingRunning.value) {
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
      timeframe: formData.timeframe ? formData.timeframe.toString() : '',
      dateStart: formData.dateFrom ? new Date(formData.dateFrom).toISOString() : '',
      dateEnd: formData.dateTo ? new Date(formData.dateTo).toISOString() : '',
      fee_taker: formData.feeTaker !== undefined ? formData.feeTaker : 0.0,
      fee_maker: formData.feeMaker !== undefined ? formData.feeMaker : 0.0,
      price_step: formData.priceStep !== undefined ? formData.priceStep : 0.0,
      slippage_in_steps: formData.slippageInSteps !== undefined ? formData.slippageInSteps : 1.0,
      parameters: customParameters
    }

    ensureConnection()
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
  // Don't save during backtesting
  if (isBacktestingRunning.value) {
    return
  }
  
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
        timeframe: formData.timeframe ? formData.timeframe.toString() : '',
        dateStart: formData.dateFrom ? new Date(formData.dateFrom).toISOString() : '',
        dateEnd: formData.dateTo ? new Date(formData.dateTo).toISOString() : '',
        parameters: customParameters
      })

      // Use fetch with keepalive for PUT request (sendBeacon doesn't support PUT)
      try {
        // fetch with keepalive allows request to continue after page unload
        fetch(`${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8202'}/api/v1/backtesting/tasks/${currentTaskId.value}`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json'
          },
          body: taskData,
          keepalive: true // Allows request to continue after page unload
        }).catch(error => {
          // Silently handle errors during page unload
          console.error('Failed to save task on page unload:', error)
        })
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
    showAlert('error', 'No task selected. Please select or create a task first.')
    return
  }

  // Validate that we have a strategy file
  if (!currentStrategyFilePath.value) {
    showAlert('error', 'No strategy file selected. Please select a strategy first.')
    return
  }

  // Validate form data
  if (!formData.source || !formData.symbol || !formData.timeframe || !formData.dateFrom || !formData.dateTo) {
    showAlert('error', 'Please fill in all required fields: Source, Symbol, Timeframe, Date From, Date To')
    return
  }

  // Clear any pending auto-save timers BEFORE saving
  if (taskSaveTimeout.value) {
    clearTimeout(taskSaveTimeout.value)
    taskSaveTimeout.value = null
  }
  if (saveTimeout.value) {
    clearTimeout(saveTimeout.value)
    saveTimeout.value = null
  }

  // Save current task before starting backtest
  try {
    await saveAll()
    // Update currentTask with formData to ensure chart gets correct timeframe immediately
    if (currentTask.value) {
      currentTask.value = {
        ...currentTask.value,
        source: formData.source,
        symbol: formData.symbol,
        timeframe: formData.timeframe,
        dateFrom: formData.dateFrom,
        dateTo: formData.dateTo
      }
    }
  } catch (error) {
    console.error('Failed to save before starting backtest:', error)
    addLocalMessage({
      level: 'error',
      message: `Failed to save task before starting backtest: ${error.message}`
    })
    return
  }

  // Clear chart before starting new backtest
  // Reset flag to false first to ensure watcher triggers on next set to true
  clearChartFlag.value = false
  // Use nextTick to ensure the false value is processed before setting to true
  await nextTick()
  clearChartFlag.value = true
  
  // Clear results before starting new backtest
  clearResults()
  
  // Set backtesting state immediately for instant UI feedback
  setBacktestingStarted()
  
  try {
    // Ensure WebSocket connection before starting backtesting
    ensureConnection()
    // Call API to start backtesting
    const response = await backtestingApi.startBacktest(currentTaskId.value)
    
    // Save result_id from response
    if (response.result_id) {
      setResultId(response.result_id)
      
      // Set initial relevance time to date_start from form
      if (formData.dateFrom) {
        const dateStart = new Date(formData.dateFrom).toISOString()
        setRelevanceTime(dateStart)
      }
    }
    
    // State will also be updated by composable when backtesting_started event is received via WebSocket
    // But we set it immediately above for instant UI feedback
  } catch (error) {
    console.error('Failed to start backtesting:', error)
    // Reset state on error
    resetBacktestingState()
    clearResults()
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
    showAlert('error', 'No task selected. Cannot stop backtesting.')
    return
  }

  try {
    // Ensure WebSocket connection before stopping backtesting
    ensureConnection()
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
  // Only if task is fully loaded (not during loading) and backtesting is not running
  if (currentTaskId.value && !isTaskLoading.value && !isBacktestingRunning.value) {
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
  // Only if task is fully loaded (not during loading) and backtesting is not running
  if (currentTaskId.value && !isTaskLoading.value && !isBacktestingRunning.value) {
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
  
  // Don't save during backtesting
  if (isBacktestingRunning.value) {
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
  display: flex;
  flex-direction: column;
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
  flex-shrink: 0;
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
  flex: 1;
  min-height: 0;
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

.stats-panel {
  flex: 1;
  overflow: hidden;
  min-height: 150px;
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

.checkbox-label {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
  cursor: pointer;
  user-select: none;
}

.checkbox-input {
  width: 16px;
  height: 16px;
  cursor: pointer;
  accent-color: var(--color-primary);
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

/* Chart controls */
.chart-controls {
  gap: var(--spacing-xs);
}

.chart-date-input-wrapper {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
}

.chart-date-fields {
  display: flex;
  align-items: center;
  gap: 2px;
}

.chart-date-field {
  padding: var(--spacing-xs) 4px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: var(--font-size-xs);
  width: 45px;
  text-align: center;
  transition: all var(--transition-base);
}

.chart-date-field-year {
  width: 60px; /* Wider for 4-digit year */
}

.chart-date-field:focus {
  outline: none;
  border-color: var(--color-primary);
  background: var(--bg-hover);
}

.chart-date-field::placeholder {
  color: var(--text-tertiary);
  font-size: var(--font-size-xs);
  opacity: 0.6;
}

.chart-date-separator {
  color: var(--text-tertiary);
  font-size: var(--font-size-xs);
  padding: 0 2px;
  user-select: none;
}

.chart-date-input {
  padding: var(--spacing-xs) var(--spacing-sm);
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: var(--font-size-xs);
  width: 180px;
  transition: all var(--transition-base);
}

.chart-date-input:focus {
  outline: none;
  border-color: var(--color-primary);
  background: var(--bg-hover);
}

.chart-control-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-base);
  flex-shrink: 0;
}

.chart-control-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--color-primary);
}

.chart-control-btn.active {
  background: var(--color-primary);
  color: white;
  border-color: var(--color-primary);
}

.chart-control-btn .icon-small {
  width: 16px;
  height: 16px;
}

.chart-control-letter {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
  line-height: 1;
}

/* Chart settings dropdown */
.chart-settings-wrapper {
  position: relative;
}

.chart-settings-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  padding: var(--spacing-xs);
  min-width: 150px;
  z-index: 1000;
}

.settings-option {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  padding: var(--spacing-xs) var(--spacing-sm);
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: background-color var(--transition-base);
  font-size: var(--font-size-xs);
  color: var(--text-primary);
  user-select: none;
}

.settings-option:hover {
  background-color: var(--bg-hover);
}

.settings-option input[type="checkbox"] {
  cursor: pointer;
  width: 14px;
  height: 14px;
}

.settings-option span {
  flex: 1;
}

</style>
