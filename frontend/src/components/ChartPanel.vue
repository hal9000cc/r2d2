<template>
  <div class="chart-panel">
    <BacktestingChart 
      ref="chartRef"
      :source="source"
      :symbol="symbol"
      :timeframe="timeframe"
      :backtesting-progress="backtestingProgress"
      :clear-chart="clearChart"
      :show-trade-markers="showTradeMarkers"
      :show-deal-lines="showDealLines"
      @chart-cleared="handleChartCleared"
      @quotes-load-error="handleQuotesLoadError"
      @chart-message="handleChartMessage"
      @log-scale-changed="handleLogScaleChanged"
    />
  </div>
</template>

<script>
import BacktestingChart from './BacktestingChart.vue'

export default {
  name: 'ChartPanel',
  components: {
    BacktestingChart
  },
  props: {
    source: {
      type: String,
      default: null
    },
    symbol: {
      type: String,
      default: null
    },
    timeframe: {
      type: String,
      default: null
    },
    backtestingProgress: {
      type: Object,
      default: null
    },
    clearChart: {
      type: Boolean,
      default: false
    },
    showTradeMarkers: {
      type: Boolean,
      default: true
    },
    showDealLines: {
      type: Boolean,
      default: true
    }
  },
  emits: ['chart-cleared', 'quotes-load-error', 'chart-message', 'log-scale-changed'],
  methods: {
    handleChartCleared() {
      this.$emit('chart-cleared')
    },
    handleQuotesLoadError(error) {
      this.$emit('quotes-load-error', error)
    },
    handleChartMessage(message) {
      this.$emit('chart-message', message)
    },
    handleLogScaleChanged(isLogScale) {
      this.$emit('log-scale-changed', isLogScale)
    },
    // Proxy methods for chart control
    goToDate(timestamp) {
      if (this.$refs.chartRef) {
        this.$refs.chartRef.goToDate(timestamp)
      }
    },
    goToStart() {
      if (this.$refs.chartRef) {
        this.$refs.chartRef.moveChartToStart()
      }
    },
    goToEnd() {
      if (this.$refs.chartRef) {
        this.$refs.chartRef.moveChartToEnd()
      }
    },
    toggleLogScale() {
      if (this.$refs.chartRef) {
        this.$refs.chartRef.toggleLogScale()
      }
    },
    autoScale() {
      if (this.$refs.chartRef) {
        this.$refs.chartRef.autoScale()
      }
    },
    pageDown() {
      if (this.$refs.chartRef) {
        this.$refs.chartRef.scrollChartBackward()
      }
    },
    pageUp() {
      if (this.$refs.chartRef) {
        this.$refs.chartRef.scrollChartForward()
      }
    }
  }
}
</script>

<style scoped>
.chart-panel {
  width: 100%;
  height: 100%;
  min-height: 150px;
  overflow: hidden;
}
</style>

