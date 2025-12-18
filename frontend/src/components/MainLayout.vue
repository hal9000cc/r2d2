<template>
  <div class="main-layout">
    <div class="left-panel">
      <ResultsPanel />
      <ResizablePanel
        v-if="chartHeight !== null"
        direction="vertical"
        :min-size="150"
        :max-size="chartMaxHeight"
        :default-size="chartHeight"
        storage-key="chart-panel-height"
        @resize="handleChartResize"
      >
        <ChartPanel />
      </ResizablePanel>
      <MessagesPanel :messages="[]" />
    </div>
    <ResizablePanel
      direction="horizontal"
      handle-side="left"
      :min-size="200"
      :max-size="activeStrategiesMaxWidth"
      :default-size="activeStrategiesWidth"
      storage-key="active-strategies-panel-width"
      @resize="handleActiveStrategiesResize"
    >
      <ActiveStrategiesPanel />
    </ResizablePanel>
  </div>
</template>

<script>
import ResizablePanel from './ResizablePanel.vue'
import ResultsPanel from './ResultsPanel.vue'
import ChartPanel from './ChartPanel.vue'
import MessagesPanel from './MessagesPanel.vue'
import ActiveStrategiesPanel from './ActiveStrategiesPanel.vue'

export default {
  name: 'MainLayout',
  components: {
    ResizablePanel,
    ResultsPanel,
    ChartPanel,
    MessagesPanel,
    ActiveStrategiesPanel
  },
  data() {
    return {
      chartHeight: null,
      chartMaxHeight: null,
      activeStrategiesWidth: 250,
      activeStrategiesMaxWidth: null
    }
  },
  mounted() {
    this.calculateSizes()
    // Update sizes when window is resized
    window.addEventListener('resize', this.calculateSizes)
  },
  beforeUnmount() {
    window.removeEventListener('resize', this.calculateSizes)
  },
  methods: {
    calculateSizes() {
      // Calculate available height (viewport height - navbar height 60px - results panel height ~10vh)
      const viewportHeight = window.innerHeight
      const navbarHeight = 60 // NavBar height
      const resultsPanelHeight = viewportHeight * 0.1 // 10vh
      const messagesMinHeight = 100 // Minimum height for Messages panel
      const availableHeight = viewportHeight - navbarHeight - resultsPanelHeight
      
      // Calculate max height for Chart (available height - min Messages height)
      this.chartMaxHeight = availableHeight - messagesMinHeight
      
      // Calculate max width for Active Strategies (50% of viewport width)
      this.activeStrategiesMaxWidth = Math.floor(window.innerWidth * 0.5)
      
      // Load saved sizes from localStorage or use defaults (only on first mount)
      if (this.chartHeight === null) {
        const savedChartHeight = localStorage.getItem('chart-panel-height')
        if (savedChartHeight) {
          const savedHeight = parseInt(savedChartHeight, 10)
          // Ensure saved height doesn't exceed max
          this.chartHeight = Math.min(savedHeight, this.chartMaxHeight)
        } else {
          // Default: 75% of available height for chart
          this.chartHeight = Math.floor(availableHeight * 0.75)
        }
      } else {
        // If window is resized, adjust chart height if it exceeds new max
        if (this.chartHeight > this.chartMaxHeight) {
          this.chartHeight = this.chartMaxHeight
        }
      }
      
      // Load active strategies width only on first mount
      if (this.activeStrategiesWidth === 250) {
        const savedActiveStrategiesWidth = localStorage.getItem('active-strategies-panel-width')
        if (savedActiveStrategiesWidth) {
          const savedWidth = parseInt(savedActiveStrategiesWidth, 10)
          // Ensure saved width doesn't exceed max
          this.activeStrategiesWidth = Math.min(savedWidth, this.activeStrategiesMaxWidth)
        } else {
          // Default: 20% of viewport width
          this.activeStrategiesWidth = Math.floor(window.innerWidth * 0.2)
        }
      } else {
        // If window is resized, adjust active strategies width if it exceeds new max
        if (this.activeStrategiesWidth > this.activeStrategiesMaxWidth) {
          this.activeStrategiesWidth = this.activeStrategiesMaxWidth
        }
      }
    },
    handleChartResize(size) {
      this.chartHeight = size
    },
    handleActiveStrategiesResize(size) {
      this.activeStrategiesWidth = size
    }
  }
}
</script>

<style scoped>
.main-layout {
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
</style>

