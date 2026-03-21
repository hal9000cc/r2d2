<template>
  <div class="trading-view">
    <!-- Teleport form to navbar -->
    <Teleport to="#navbar-content-slot">
      <TradingNavForm 
        ref="navFormRef" 
        :disabled="!currentTaskId"
        :is-running="isRunning"
        :readonly="isReadonly"
        @start="handleStart"
        @stop="handleStop"
        @form-data-changed="handleFormDataChanged"
      />
    </Teleport>

    <div class="trading-layout">
      <!-- Left side: Chart and Bottom Tabs -->
      <div class="left-panel">
        <ResizablePanel
          v-if="chartHeight !== null"
          direction="vertical"
          :min-size="150"
          :max-size="chartMaxHeight"
          :default-size="chartHeight"
          storage-key="trading-chart-panel-height"
          @resize="handleChartResize"
        >
          <ChartPanel 
            ref="chartPanelRef"
            :source="currentSource"
            :symbol="currentSymbol"
            :timeframe="currentTimeframe"
          />
        </ResizablePanel>
        <Tabs
          :tabs="tabsWithBadge"
          default-tab="deals"
          @tab-change="handleTabChange"
        >
          <template #header-actions>
            <div v-if="activeTab === 'supervisor'" class="header-actions">
              <button 
                class="header-btn clear-btn" 
                @click="handleClearSupervisorClick"
                :disabled="supervisorErrors.length === 0"
                title="Clear supervisor errors"
              >
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="icon">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
                Clear
              </button>
            </div>
            <div v-if="activeTab === 'messages'" class="header-actions">
              <button 
                class="header-btn clear-btn" 
                @click="handleClearMessages"
                :disabled="allMessages.length === 0"
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
          <template #deals>
            <DataTable 
              :columns="dealsColumns"
              :data="dealsArray"
              row-key="deal_id"
              empty-message="No deals yet"
              :enabled="activeTab === 'deals'"
            />
          </template>
          <template #trades>
            <DataTable 
              :columns="tradesColumns"
              :data="allTradesArray"
              row-key="trade_id"
              empty-message="No trades yet"
              :enabled="activeTab === 'trades'"
            />
          </template>
          <template #orders>
            <DataTable 
              :columns="ordersColumns"
              :data="filteredOrders"
              row-key="order_id"
              empty-message="No orders yet"
              :enabled="activeTab === 'orders'"
            />
          </template>
          <template #errors>
            <ErrorsPanel :errors="errors" />
          </template>
          <template #supervisor>
            <ErrorsPanel :errors="supervisorErrors" />
          </template>
          <template #messages>
            <MessagesPanel :messages="allMessages" />
          </template>
        </Tabs>
      </div>
      
      <!-- Right side: Tasks and Stats -->
      <ResizablePanel
        direction="horizontal"
        handle-side="left"
        :min-size="200"
        :max-size="rightPanelMaxWidth"
        :default-size="rightPanelWidth"
        storage-key="trading-right-panel-width"
        @resize="handleRightPanelResize"
      >
        <div class="right-panel">
          <div class="tasks-panel">
            <TradingTaskList
              ref="taskListRef"
              :selected-task-id="currentTaskId"
              @task-selected="handleTaskSelected"
              @task-deleted="handleTaskDeleted"
            />
          </div>
          <div class="stats-panel">
            <TradingStats :stats="stats">
              <template #default="{ formatFee }">
                <div class="stats-separator"></div>
                <div class="stats-section-title">Trade parameters</div>
                <div class="stats-row">
                  <span class="stats-label">Fee Maker:</span>
                  <span class="stats-value">{{ formatFee(stats?.fee_maker) }}</span>
                </div>
                <div class="stats-row">
                  <span class="stats-label">Fee Taker:</span>
                  <span class="stats-value">{{ formatFee(stats?.fee_taker) }}</span>
                </div>
              </template>
            </TradingStats>
          </div>
        </div>
      </ResizablePanel>
    </div>

    <!-- Stop confirmation dialog -->
    <div v-if="showStopDialog" class="confirm-overlay" @click.self="showStopDialog = false">
      <div class="confirm-dialog">
        <p>Stop trading task <strong>{{ currentTask?.name }}</strong>?</p>
        <label class="checkbox-label">
          <input type="checkbox" v-model="closeDealsOnStop" class="checkbox-input" />
          <span>Close all open deals on stop</span>
        </label>
        <div class="confirm-actions">
          <button class="btn btn-cancel" @click="showStopDialog = false">Cancel</button>
          <button class="btn btn-danger" @click="confirmStop">Stop</button>
        </div>
      </div>
    </div>

    <div v-if="showClearSupervisorDialog" class="confirm-overlay" @click.self="showClearSupervisorDialog = false">
      <div class="confirm-dialog">
        <p>Clear all supervisor errors from UI and backend storage?</p>
        <div class="confirm-actions">
          <button class="btn btn-cancel" @click="showClearSupervisorDialog = false">Cancel</button>
          <button class="btn btn-danger" @click="confirmClearSupervisorErrors">Clear</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ResizablePanel from '../components/ResizablePanel.vue'
import ChartPanel from '../components/ChartPanel.vue'
import MessagesPanel from '../components/MessagesPanel.vue'
import DataTable from '../components/DataTable.vue'
import TradingNavForm from '../components/TradingNavForm.vue'
import TradingTaskList from '../components/TradingTaskList.vue'
import TradingStats from '../components/TradingStats.vue'
import ErrorsPanel from '../components/ErrorsPanel.vue'
import Tabs from '../components/Tabs.vue'
import { tradingApi } from '../services/tradingApi'
import { useBacktestingResults } from '../composables/useBacktestingResults'
import { useTrading } from '../composables/useTrading'
import { useSupervisor } from '../composables/useSupervisor'

const route = useRoute()
const router = useRouter()

// Trading results composable (manages trades/deals/orders/stats Maps)
const {
  stats,
  clearResults,
  addTrades,
  updateDeals,
  updateOrders,
  updateStats,
  getAllDeals,
  getAllTrades,
  getAllOrders
} = useBacktestingResults()

// Layout state
const chartHeight = ref(null)
const chartMaxHeight = ref(null)
const rightPanelWidth = ref(250)
const rightPanelMaxWidth = ref(null)

// Bottom tabs
const tabs = [
  { id: 'deals', label: 'Deals' },
  { id: 'trades', label: 'Trades' },
  { id: 'orders', label: 'Orders' },
  { id: 'errors', label: 'Errors' },
  { id: 'supervisor', label: 'Supervisor' },
  { id: 'messages', label: 'Messages' }
]
const activeTab = ref('deals')

// Task state
const currentTaskId = ref(null)
const currentTask = ref(null)
const currentResultId = ref(null)
const isRunning = ref(false)
const isReadonly = ref(true)
const hideCanceledOrders = ref(false)

// Errors state (managed locally, not in useBacktestingResults)
const errors = ref([])
const lastErrorId = ref(0)

// Supervisor composable — global channel, independent of selected task
const { supervisorErrors, clearErrors: clearSupervisorErrors } = useSupervisor()

// Trading WS composable (messages, events, reconnection)
const {
  allMessages,
  isTradingRunning,
  lastProgressTime,
  clearMessages,
  clearAllMessages,
  addLocalMessage,
  setTradingStarted,
  resetTradingState,
} = useTrading(computed(() => currentTaskId.value))

// Messages badge: count unread important messages when Messages tab is not active
const unreadImportantMessagesCount = ref(0)
const lastProcessedMessageIndex = ref(-1)

watch(allMessages, (newMessages) => {
  if (newMessages.length < lastProcessedMessageIndex.value) {
    // Messages were cleared
    lastProcessedMessageIndex.value = newMessages.length - 1
    return
  }
  if (activeTab.value !== 'messages') {
    for (let i = lastProcessedMessageIndex.value + 1; i < newMessages.length; i++) {
      const msg = newMessages[i]
      if (msg.level === 'error' || msg.level === 'warning') {
        unreadImportantMessagesCount.value++
      }
    }
  }
  lastProcessedMessageIndex.value = newMessages.length - 1
})

// Watch isTradingRunning from composable: sync to isRunning and reload on stop
watch(isTradingRunning, (running, wasRunning) => {
  if (running === wasRunning) return
  isRunning.value = running
  if (currentTask.value) currentTask.value.isRunning = running
  if (!running && wasRunning) {
    // Trading stopped — reload task list and final results
    taskListRef.value?.loadTasks()
    loadTradingResults()
  }
})

// Watch lastProgressTime from composable: incremental results reload on progress event
watch(lastProgressTime, async (newTime) => {
  if (!newTime) return
  if (!currentTaskId.value || !currentResultId.value) return
  try {
    const response = await tradingApi.getResults(
      currentTaskId.value, currentResultId.value, newTime, lastErrorId.value
    )
    if (response.success && response.data) {
      const data = response.data
      if (data.trades?.length) addTrades(data.trades)
      if (data.deals?.length) updateDeals(data.deals)
      if (data.orders?.length) updateOrders(data.orders)
      if (data.stats) updateStats(data.stats)
      if (data.errors?.length) {
        errors.value.push(...data.errors)
        lastErrorId.value = data.errors[data.errors.length - 1].id
      }
    }
  } catch (err) {
    console.error('Failed to load trading results (incremental):', err)
  }
})

// Stop confirmation dialog
const showStopDialog = ref(false)
const closeDealsOnStop = ref(false)
const showClearSupervisorDialog = ref(false)

// Current task data for chart
const currentSource = ref(null)
const currentSymbol = ref(null)
const currentTimeframe = ref(null)

// Component refs
const navFormRef = ref(null)
const chartPanelRef = ref(null)
const taskListRef = ref(null)

// Tabs with badges: errors count, supervisor errors count, unread messages count
const tabsWithBadge = computed(() => {
  return tabs.map(tab => {
    if (tab.id === 'errors' && errors.value.length > 0) {
      return { ...tab, badge: errors.value.length }
    }
    if (tab.id === 'supervisor' && supervisorErrors.value.length > 0) {
      return { ...tab, badge: supervisorErrors.value.length }
    }
    if (tab.id === 'messages' && unreadImportantMessagesCount.value > 0) {
      return { ...tab, badge: unreadImportantMessagesCount.value }
    }
    return tab
  })
})

// Table column definitions
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
    key: 'date_open', 
    label: 'Date Open', 
    width: '160px',
    format: (value) => value ? new Date(value).toISOString().replace('T', ' ').substring(0, 19) : '—'
  },
  { 
    key: 'date_close', 
    label: 'Date Close', 
    width: '160px',
    format: (value) => value ? new Date(value).toISOString().replace('T', ' ').substring(0, 19) : '—'
  },
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
  },
  { 
    key: 'close_type', 
    label: 'Close Type',
    width: '120px',
    format: (value) => {
      if (!value || value === 0) return '—'
      if (value === 1) return 'Stop Loss'
      if (value === 2) return 'Take Profit'
      return '—'
    }
  }
]

const ordersColumns = [
  { key: 'order_id', label: 'Order ID', width: '80px' },
  { key: 'exchange_order_id', label: 'Exchange Order ID', width: '150px' },
  { key: 'deal_id', label: 'Deal ID', width: '80px' },
  { 
    key: 'order_type', 
    label: 'Type',
    width: '80px',
    format: (value) => value ? value.toUpperCase() : '—'
  },
  { 
    key: 'order_group', 
    label: 'Group',
    width: '100px',
    format: (value) => {
      const groupMap = {
        0: 'None',
        1: 'Stop Loss',
        2: 'Take Profit'
      }
      return groupMap[value] !== undefined ? groupMap[value] : '—'
    }
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
    key: 'fraction', 
    label: 'Fraction',
    width: '100px',
    class: 'align-right',
    format: (value) => value !== null && value !== undefined ? parseFloat(value).toFixed(4) : '—'
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

// Computed: table data arrays
const dealsArray = computed(() => {
  const all = getAllDeals()
  return all.sort((a, b) => parseInt(a.deal_id, 10) - parseInt(b.deal_id, 10))
})

const allTradesArray = computed(() => getAllTrades())

const filteredOrders = computed(() => {
  const all = getAllOrders()
  if (!hideCanceledOrders.value) return all
  // Show only active orders or those with partial fills
  return all.filter(order => {
    const filledVolume = parseFloat(order.filled_volume) || 0
    return order.status === 1 || filledVolume !== 0
  })
})

/**
 * Load trading results from API and populate trades/deals/orders/stats/errors.
 */
async function loadTradingResults() {
  if (!currentTaskId.value || !currentResultId.value) return
  try {
    const response = await tradingApi.getResults(currentTaskId.value, currentResultId.value)
    if (response.success && response.data) {
      const data = response.data
      if (data.trades?.length) addTrades(data.trades)
      if (data.deals?.length) updateDeals(data.deals)
      if (data.orders?.length) updateOrders(data.orders)
      if (data.stats) updateStats(data.stats)
      if (data.errors?.length) {
        errors.value = data.errors
        lastErrorId.value = data.errors[data.errors.length - 1].id
      }
    }
  } catch (err) {
    console.error('Failed to load trading results:', err)
  }
}

// Layout calculations
function calculateSizes() {
  const viewportHeight = window.innerHeight
  const navbarHeight = 60
  const messagesMinHeight = 100
  const availableHeight = viewportHeight - navbarHeight
  
  chartMaxHeight.value = availableHeight - messagesMinHeight
  rightPanelMaxWidth.value = Math.floor(window.innerWidth * 0.5)
  
  if (chartHeight.value === null) {
    const savedChartHeight = localStorage.getItem('trading-chart-panel-height')
    if (savedChartHeight) {
      const savedHeight = parseInt(savedChartHeight, 10)
      chartHeight.value = Math.min(savedHeight, chartMaxHeight.value)
    } else {
      chartHeight.value = Math.floor(availableHeight * 0.65)
    }
  } else {
    if (chartHeight.value > chartMaxHeight.value) {
      chartHeight.value = chartMaxHeight.value
    }
  }
  
  if (rightPanelWidth.value === 250) {
    const savedWidth = localStorage.getItem('trading-right-panel-width')
    if (savedWidth) {
      const parsed = parseInt(savedWidth, 10)
      rightPanelWidth.value = Math.min(parsed, rightPanelMaxWidth.value)
    } else {
      rightPanelWidth.value = Math.floor(window.innerWidth * 0.2)
    }
  } else {
    if (rightPanelWidth.value > rightPanelMaxWidth.value) {
      rightPanelWidth.value = rightPanelMaxWidth.value
    }
  }
}

// Event handlers
function handleTabChange(tab) {
  activeTab.value = tab
  if (tab === 'messages') {
    unreadImportantMessagesCount.value = 0
  }
}

function handleChartResize(size) {
  chartHeight.value = size
}

function handleRightPanelResize(size) {
  rightPanelWidth.value = size
}

async function handleStart() {
  if (!currentTaskId.value) return
  try {
    const result = await tradingApi.startTask(currentTaskId.value)
    if (result.success) {
      isRunning.value = true
      currentResultId.value = result.result_id
      if (currentTask.value) currentTask.value.isRunning = true
      setTradingStarted(result.result_id)
      taskListRef.value?.loadTasks()
    }
  } catch (err) {
    const detail = err.response?.data?.detail || err.message
    console.error('Failed to start trading task:', detail)
    addLocalMessage({ level: 'error', message: `Start failed: ${detail}` })
  }
}

function handleStop() {
  showStopDialog.value = true
}

async function confirmStop() {
  showStopDialog.value = false
  if (!currentTaskId.value) return
  try {
    await tradingApi.stopTask(currentTaskId.value, closeDealsOnStop.value)
    // isRunning will be set via isTradingRunning watcher when trading_stopped event arrives
  } catch (err) {
    const detail = err.response?.data?.detail || err.message
    console.error('Failed to stop trading task:', detail)
    addLocalMessage({ level: 'error', message: `Stop failed: ${detail}` })
  }
}

function handleFormDataChanged() {
  // Placeholder — will handle form data changes
}

function handleTaskSelected(task) {
  clearResults()
  errors.value = []
  lastErrorId.value = 0

  currentTaskId.value = task.id
  currentTask.value = task
  currentResultId.value = task.result_id || null
  isRunning.value = task.isRunning || false
  isReadonly.value = true

  currentSource.value = task.source || null
  currentSymbol.value = task.symbol || null
  currentTimeframe.value = task.timeframe || null

  if (navFormRef.value) {
    navFormRef.value.setFormData({
      source: task.source || '',
      symbol: task.symbol || '',
      timeframe: task.timeframe || ''
    })
  }

  // useTrading composable auto-manages WS connection via taskId watcher

  // Load trading results
  if (task.result_id) {
    loadTradingResults()
  }
}

function handleTaskDeleted(taskId) {
  if (currentTaskId.value === taskId) {
    clearResults()
    errors.value = []
    lastErrorId.value = 0
    resetTradingState()
    currentTaskId.value = null
    currentTask.value = null
    currentResultId.value = null
    isRunning.value = false
    currentSource.value = null
    currentSymbol.value = null
    currentTimeframe.value = null
    if (navFormRef.value) {
      navFormRef.value.setFormData({ source: '', symbol: '', timeframe: '' })
    }
  }
}

function handleClearMessages() {
  clearAllMessages()
  unreadImportantMessagesCount.value = 0
  lastProcessedMessageIndex.value = -1
}

function handleClearSupervisorClick() {
  showClearSupervisorDialog.value = true
}

async function confirmClearSupervisorErrors() {
  showClearSupervisorDialog.value = false
  try {
    const result = await clearSupervisorErrors()
    if (!result?.success) {
      addLocalMessage({ level: 'error', message: result?.error_message || 'Failed to clear supervisor errors' })
    }
  } catch (err) {
    const detail = err.response?.data?.detail || err.message
    console.error('Failed to clear supervisor errors:', detail)
    addLocalMessage({ level: 'error', message: `Clear supervisor errors failed: ${detail}` })
  }
}

// Auto-select task from query parameter (e.g. after Deploy from Backtesting)
async function selectTaskFromQuery() {
  const taskId = Number(route.query.taskId)
  if (!taskId) return

  // Remove query param to avoid re-selecting on refresh
  router.replace({ query: {} })

  // Wait for TradingTaskList to finish loading
  await nextTick()
  
  // Retry a few times — loadTasks may still be in progress
  for (let i = 0; i < 10; i++) {
    const task = taskListRef.value?.getTaskById(taskId)
    if (task) {
      handleTaskSelected(task)
      return
    }
    await new Promise(r => setTimeout(r, 200))
  }
}

// Lifecycle
onMounted(() => {
  calculateSizes()
  window.addEventListener('resize', calculateSizes)
  selectTaskFromQuery()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', calculateSizes)
})
</script>

<style scoped>
.trading-view {
  width: 100%;
  height: 100%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.trading-layout {
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

.tasks-panel {
  flex: 1;
  min-height: 100px;
  padding: var(--spacing-sm);
  border-bottom: 1px solid var(--border-color-dark);
  background-color: var(--bg-secondary);
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--spacing-sm);
  flex-shrink: 0;
}

.panel-header h3 {
  margin: 0;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
}

.tasks-content {
  flex: 1;
  overflow-y: auto;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-muted);
  font-size: var(--font-size-sm);
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

.header-btn .icon {
  width: var(--font-size-sm);
  height: var(--font-size-sm);
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

/* Stop confirmation dialog */
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
  min-width: 300px;
  max-width: 420px;
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
}

.confirm-dialog p {
  margin: 0;
  font-size: var(--font-size-sm);
  color: var(--text-primary);
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
</style>
