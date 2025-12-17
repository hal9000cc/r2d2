<template>
  <div class="chart-panel">
    <BacktestingChart 
      :chart-data="chartData" 
      :clear-chart="clearChart"
      @chart-cleared="handleChartCleared"
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
    chartData: {
      type: Array,
      default: () => []
    },
    clearChart: {
      type: Boolean,
      default: false
    }
  },
  emits: ['chart-cleared'],
  methods: {
    handleChartCleared() {
      this.$emit('chart-cleared')
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

