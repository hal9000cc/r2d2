<template>
  <div class="chart-panel">
    <BacktestingChart 
      :source="source"
      :symbol="symbol"
      :timeframe="timeframe"
      :backtesting-progress="backtestingProgress"
      :clear-chart="clearChart"
      @chart-cleared="handleChartCleared"
      @quotes-load-error="handleQuotesLoadError"
      @chart-message="handleChartMessage"
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
    }
  },
  emits: ['chart-cleared', 'quotes-load-error', 'chart-message'],
  methods: {
    handleChartCleared() {
      this.$emit('chart-cleared')
    },
    handleQuotesLoadError(error) {
      this.$emit('quotes-load-error', error)
    },
    handleChartMessage(message) {
      this.$emit('chart-message', message)
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

