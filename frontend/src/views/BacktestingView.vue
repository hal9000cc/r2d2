<template>
  <div class="backtesting-view">
    <!-- Teleport form to navbar -->
    <Teleport to="#navbar-content-slot">
      <BacktestingNavForm @start="handleStart" />
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
          <ChartPanel />
        </ResizablePanel>
        <Tabs
          :tabs="tabs"
          default-tab="balance"
          @tab-change="handleTabChange"
        >
          <template #balance>
            <BalanceChart />
          </template>
          <template #messages>
            <MessagesPanel :active-strategy-id="null" />
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
            <StrategyParameters />
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
import BalanceChart from '../components/BalanceChart.vue'
import Tabs from '../components/Tabs.vue'

export default {
  name: 'BacktestingView',
  components: {
    ResizablePanel,
    ChartPanel,
    MessagesPanel,
    BacktestingNavForm,
    StrategyParameters,
    BacktestResults,
    BalanceChart,
    Tabs
  },
  data() {
    return {
      chartHeight: null,
      chartMaxHeight: null,
      rightPanelWidth: 250,
      rightPanelMaxWidth: null,
      parametersHeight: null,
      parametersMaxHeight: null,
      tabs: [
        { id: 'balance', label: 'Balance' },
        { id: 'messages', label: 'Messages' }
      ]
    }
  },
  mounted() {
    this.calculateSizes()
    window.addEventListener('resize', this.calculateSizes)
  },
  beforeUnmount() {
    window.removeEventListener('resize', this.calculateSizes)
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
          // Default: 20% of viewport width (same as ActiveStrategiesPanel)
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
    handleTabChange(tabId) {
      // Handle tab change if needed
    },
    handleStart(formData) {
      console.log('Start backtesting with:', formData)
      // TODO: Implement backtesting start logic
    }
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
</style>
