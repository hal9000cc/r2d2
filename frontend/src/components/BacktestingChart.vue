<template>
  <div ref="chartContainer" class="backtesting-chart"></div>
</template>

<script>
import { createChart, ColorType, CandlestickSeries } from 'lightweight-charts'

export default {
  name: 'BacktestingChart',
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
  data() {
    return {
      chart: null,
      candlestickSeries: null,
      currentData: []
    }
  },
  watch: {
    chartData(newData) {
      if (newData && newData.length > 0) {
        this.updateChart(newData)
      }
    },
    clearChart(newValue) {
      if (newValue) {
        this.clearChartData()
        // Reset clearChart flag after clearing
        this.$nextTick(() => {
          this.$emit('chart-cleared')
        })
      }
    }
  },
  mounted() {
    this.initChart()
    if (this.chartData && this.chartData.length > 0) {
      this.updateChart(this.chartData)
    }
    // Handle window resize
    window.addEventListener('resize', this.handleResize)
  },
  beforeUnmount() {
    if (this.chart) {
      this.chart.remove()
      this.chart = null
    }
    window.removeEventListener('resize', this.handleResize)
  },
  methods: {
    initChart() {
      if (!this.$refs.chartContainer) {
        return
      }

      // Create chart
      this.chart = createChart(this.$refs.chartContainer, {
        layout: {
          background: { type: ColorType.Solid, color: 'transparent' },
          textColor: 'var(--text-primary, #333)'
        },
        grid: {
          vertLines: {
            color: 'var(--border-color, #e0e0e0)'
          },
          horzLines: {
            color: 'var(--border-color, #e0e0e0)'
          }
        },
        width: this.$refs.chartContainer.clientWidth,
        height: this.$refs.chartContainer.clientHeight,
        timeScale: {
          timeVisible: true,
          secondsVisible: false
        }
      })

      // Create candlestick series (API changed in v5.0+)
      this.candlestickSeries = this.chart.addSeries(CandlestickSeries, {
        upColor: '#26a69a',
        downColor: '#ef5350',
        borderVisible: false,
        wickUpColor: '#26a69a',
        wickDownColor: '#ef5350'
      })
    },
    updateChart(newData) {
      if (!this.candlestickSeries || !newData || newData.length === 0) {
        return
      }

      // Convert new data to format expected by lightweight-charts
      // newData is array of {time, open, high, low, close}
      const formattedData = newData.map(item => ({
        time: item.time, // Unix timestamp in seconds
        open: item.open,
        high: item.high,
        low: item.low,
        close: item.close
      }))

      // Add new data points incrementally
      // For candlestick series, we can use update() for each new candle
      // or setData() to replace all data (more efficient for large updates)
      if (this.currentData.length === 0) {
        // First data - set all at once
        this.candlestickSeries.setData(formattedData)
        this.currentData = [...formattedData]
      } else {
        // Add new candles incrementally
        formattedData.forEach(candle => {
          this.candlestickSeries.update(candle)
          this.currentData.push(candle)
        })
      }

      // Fit content to show all data
      this.chart.timeScale().fitContent()
    },
    clearChartData() {
      if (this.candlestickSeries) {
        this.candlestickSeries.setData([])
        this.currentData = []
      }
    },
    handleResize() {
      if (this.chart && this.$refs.chartContainer) {
        this.chart.applyOptions({
          width: this.$refs.chartContainer.clientWidth,
          height: this.$refs.chartContainer.clientHeight
        })
      }
    }
  }
}
</script>

<style scoped>
.backtesting-chart {
  width: 100%;
  height: 100%;
  min-height: 150px;
}
</style>
