<template>
  <div ref="chartContainer" class="backtesting-chart"></div>
</template>

<script>
import { createChart, ColorType, CandlestickSeries } from 'lightweight-charts'
import axios from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8202'

export default {
  name: 'BacktestingChart',
  props: {
    // Task parameters for loading quotes
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
    // Backtesting progress info
    backtestingProgress: {
      type: Object,
      default: null,
      validator: (value) => {
        if (!value) return true
        return value.date_start !== undefined && value.current_time !== undefined
      }
    },
    clearChart: {
      type: Boolean,
      default: false
    }
  },
  emits: ['chart-cleared', 'quotes-load-error', 'chart-message'],
  data() {
    return {
      chart: null,
      candlestickSeries: null,
      currentData: [], // Array of {time, open, high, low, close}
      
      // Logical range subscription
      logicalRangeSubscription: null,
      
      // Backtesting bounds
      backtestingDateStart: null, // Unix timestamp in seconds
      backtestingDateEnd: null, // Unix timestamp in seconds (current_time from progress)
      
      // Loading state
      isLoading: false,
      loadRequestId: 0, // For canceling outdated requests
      
      // Threshold for loading more data (number of bars from start)
      loadThreshold: 10,
      
      // Flag to prevent event handling during data updates
      isUpdatingData: false
    }
  },
  watch: {
    backtestingProgress: {
      handler(newProgress) {
        if (newProgress && newProgress.date_start && newProgress.current_time) {
          this.handleBacktestingProgress(newProgress)
        }
      },
      immediate: true,
      deep: true
    },
    clearChart(newValue) {
      if (newValue) {
        this.clearChartData()
        this.$nextTick(() => {
          this.$emit('chart-cleared')
        })
      }
    },
    source() {
      this.resetChart()
    },
    symbol() {
      this.resetChart()
    },
    timeframe() {
      this.resetChart()
    }
  },
  mounted() {
    this.initChart()
    this.setupLogicalRangeTracking()
  },
  beforeUnmount() {
    this.cleanup()
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

      // Create candlestick series
      this.candlestickSeries = this.chart.addSeries(CandlestickSeries, {
        upColor: '#26a69a',
        downColor: '#ef5350',
        borderVisible: false,
        wickUpColor: '#26a69a',
        wickDownColor: '#ef5350'
      })
    },
    
    setupLogicalRangeTracking() {
      if (!this.chart) return
      
      // Subscribe to logical range changes (like in the example)
      this.logicalRangeSubscription = this.chart.timeScale().subscribeVisibleLogicalRangeChange((logicalRange) => {
        if (!logicalRange) return
        
        // Ignore events during data updates to prevent loops
        if (this.isUpdatingData) {
          return
        }
        
        const dataLength = this.currentData.length
        
        // Load more data when approaching the start (scrolling left)
        if (logicalRange.from < this.loadThreshold) {
          const barsPastStart = Math.max(0, -logicalRange.from)
          const numberBarsToLoad = 50 + barsPastStart
          this.loadMoreHistory(numberBarsToLoad)
        }
        
        // Load more data when approaching the end (scrolling right)
        // FIX: logical range to can be greater than dataLength!
        if (logicalRange.to !== null && logicalRange.to > 0) {
          // Calculate how far we've scrolled beyond current data
          const distanceBeyondEnd = Math.max(0, logicalRange.to - dataLength)
          
          // If we're within threshold of end (or already beyond it)
          if (distanceBeyondEnd > 0 || dataLength - logicalRange.to < this.loadThreshold) {
            // Load at least 20 bars or enough to cover distanceBeyondEnd
            const numberBarsToLoad = Math.max(20, Math.ceil(distanceBeyondEnd * 1.5))
            this.loadMoreFuture(numberBarsToLoad)
          }
        }
      })
    },
    
    /**
     * Handle backtesting progress update
     */
    handleBacktestingProgress(progress) {
      // Convert ISO strings to Unix timestamps
      const dateStart = progress.date_start ? this.isoToUnix(progress.date_start) : null
      const dateCurrent = progress.current_time ? this.isoToUnix(progress.current_time) : null
      
      if (!dateStart || !dateCurrent) {
        return
      }
      
      // Update backtesting bounds
      const wasFirstProgress = this.backtestingDateStart === null
      this.backtestingDateStart = dateStart
      this.backtestingDateEnd = dateCurrent
      
      // On first progress, load initial data
      if (wasFirstProgress) {
        this.$nextTick(() => {
          this.loadInitialData()
        })
      }
    },
    
    /**
     * Load initial data when backtesting starts
     */
    async loadInitialData() {
      if (!this.backtestingDateStart || !this.backtestingDateEnd) {
        return
      }
      
      if (!this.source || !this.symbol || !this.timeframe) {
        return
      }
      
      // Load initial data: from date_start to current_time
      const quotes = await this.loadQuotes(this.backtestingDateStart, this.backtestingDateEnd)
      
      if (quotes.length > 0) {
        // Emit message with date range
        const dateFrom = quotes.length > 0 ? new Date(quotes[0].time * 1000).toISOString() : 'N/A'
        const dateTo = quotes.length > 0 ? new Date(quotes[quotes.length - 1].time * 1000).toISOString() : 'N/A'
        this.$emit('chart-message', {
          level: 'info',
          message: `setData: ${quotes.length} bars, date range: ${dateFrom} to ${dateTo}`
        })
        
        this.currentData = quotes
        this.candlestickSeries.setData(quotes)
        
        // Auto-fit content on first load
        this.$nextTick(() => {
          if (this.chart) {
            this.chart.timeScale().fitContent()
          }
        })
      }
    },
    
    /**
     * Load more future data (when scrolling right)
     */
    async loadMoreFuture(numberOfBars) {
      if (!this.source || !this.symbol || !this.timeframe) {
        return
      }
      
      if (this.isLoading) {
        return
      }
      
      if (this.currentData.length === 0) {
        return
      }
      
      // Calculate timeframe in seconds
      const timeframeSeconds = this.getTimeframeSeconds()
      if (timeframeSeconds === 0) {
        return
      }
      
      // Calculate time range to load (after current latest data)
      // FIX: Start loading from the next period after the latest known time
      const latestTime = this.currentData[this.currentData.length - 1].time
      const loadFrom = latestTime + timeframeSeconds // +1 period
      const timeRangeToLoad = numberOfBars * timeframeSeconds
      const loadTo = loadFrom + timeRangeToLoad
      
      // Clamp to maximum backtesting date if available
      let finalTo = loadTo
      if (this.backtestingDateEnd) {
        finalTo = Math.min(loadTo, this.backtestingDateEnd)
      }
      
      // If we've reached the limit - don't load
      if (loadFrom >= finalTo) {
        this.$emit('chart-message', {
          level: 'info',
          message: 'Reached end of available data'
        })
        return
      }
      
      this.isLoading = true
      const requestId = ++this.loadRequestId
      
      try {
        // Load quotes from API
        const quotes = await this.loadQuotes(loadFrom, finalTo)
        
        // Check if this request is still relevant
        if (requestId !== this.loadRequestId) {
          return // Outdated request, ignore
        }
        
        if (quotes.length === 0) {
          return
        }
        
        // Merge with existing data (new data goes to the end)
        // Remove duplicates based on time
        const existingTimes = new Set(this.currentData.map(d => d.time))
        const uniqueNewQuotes = quotes.filter(q => !existingTimes.has(q.time))
        
        // Combine: existing data (older) + new data (newer)
        const mergedData = [...this.currentData, ...uniqueNewQuotes]
        
        // Sort by time to ensure correct order
        mergedData.sort((a, b) => a.time - b.time)
        
        // Update chart with all data (like in the example)
        setTimeout(() => {
          if (requestId === this.loadRequestId) {
            // Emit message with date range
            const dateFrom = mergedData.length > 0 ? new Date(mergedData[0].time * 1000).toISOString() : 'N/A'
            const dateTo = mergedData.length > 0 ? new Date(mergedData[mergedData.length - 1].time * 1000).toISOString() : 'N/A'
            const oldDataLength = this.currentData.length
            const newDataLength = mergedData.length
            
            this.$emit('chart-message', {
              level: 'info',
              message: `setData (future): ${oldDataLength} -> ${newDataLength} bars, date range: ${dateFrom} to ${dateTo}`
            })
            
            // Set flag to prevent event handling during update
            this.isUpdatingData = true
            
            // Save logical range before setData
            const savedLogicalRange = this.chart.timeScale().getVisibleLogicalRange()
            
            this.currentData = mergedData
            this.candlestickSeries.setData(mergedData)
            
            // Restore logical range after setData
            if (savedLogicalRange) {
              this.chart.timeScale().setVisibleLogicalRange(savedLogicalRange)
            }
            
            // Re-enable event handling after a delay
            setTimeout(() => {
              this.isUpdatingData = false
            }, 300)
          }
        }, 250) // Add a loading delay like in the example
        
      } catch (error) {
        console.error('Failed to load more future:', error)
        this.$emit('quotes-load-error', error)
      } finally {
        if (requestId === this.loadRequestId) {
          this.isLoading = false
        }
      }
    },
    
    /**
     * Load more history data (when scrolling left)
     */
    async loadMoreHistory(numberOfBars) {
      if (!this.source || !this.symbol || !this.timeframe) {
        return
      }
      
      if (this.isLoading) {
        return
      }
      
      if (this.currentData.length === 0) {
        return
      }
      
      // Calculate timeframe in seconds
      const timeframeSeconds = this.getTimeframeSeconds()
      if (timeframeSeconds === 0) {
        return
      }
      
      // Calculate time range to load (before current earliest data)
      const earliestTime = this.currentData[0].time
      const timeRangeToLoad = numberOfBars * timeframeSeconds
      const loadTo = earliestTime
      const loadFrom = Math.max(earliestTime - timeRangeToLoad, this.backtestingDateStart)
      
      if (loadFrom >= loadTo) {
        return // Can't load more (reached start of backtesting)
      }
      
      this.isLoading = true
      const requestId = ++this.loadRequestId
      
      try {
        // Load quotes from API
        const quotes = await this.loadQuotes(loadFrom, loadTo)
        
        // Check if this request is still relevant
        if (requestId !== this.loadRequestId) {
          return // Outdated request, ignore
        }
        
        if (quotes.length === 0) {
          return
        }
        
        // Merge with existing data (new data goes to the beginning)
        // Remove duplicates based on time
        const existingTimes = new Set(this.currentData.map(d => d.time))
        const uniqueNewQuotes = quotes.filter(q => !existingTimes.has(q.time))
        
        // Combine: new data (older) + existing data (newer)
        const mergedData = [...uniqueNewQuotes, ...this.currentData]
        
        // Sort by time to ensure correct order
        mergedData.sort((a, b) => a.time - b.time)
        
        // Update chart with all data (like in the example)
        setTimeout(() => {
          if (requestId === this.loadRequestId) {
            // Emit message with date range
            const dateFrom = mergedData.length > 0 ? new Date(mergedData[0].time * 1000).toISOString() : 'N/A'
            const dateTo = mergedData.length > 0 ? new Date(mergedData[mergedData.length - 1].time * 1000).toISOString() : 'N/A'
            const oldDataLength = this.currentData.length
            const newDataLength = mergedData.length
            
            this.$emit('chart-message', {
              level: 'info',
              message: `setData (history): ${oldDataLength} -> ${newDataLength} bars, date range: ${dateFrom} to ${dateTo}`
            })
            
            // Set flag to prevent event handling during update
            this.isUpdatingData = true
            
            // Save logical range before setData
            const savedLogicalRange = this.chart.timeScale().getVisibleLogicalRange()
            
            this.currentData = mergedData
            this.candlestickSeries.setData(mergedData)
            
            // Restore logical range after setData
            if (savedLogicalRange) {
              this.chart.timeScale().setVisibleLogicalRange(savedLogicalRange)
            }
            
            // Re-enable event handling after a delay
            setTimeout(() => {
              this.isUpdatingData = false
            }, 300)
          }
        }, 250) // Add a loading delay like in the example
        
      } catch (error) {
        console.error('Failed to load more history:', error)
        this.$emit('quotes-load-error', error)
      } finally {
        if (requestId === this.loadRequestId) {
          this.isLoading = false
        }
      }
    },
    
    /**
     * Load quotes from API
     */
    async loadQuotes(fromTimestamp, toTimestamp) {
      if (!this.source || !this.symbol || !this.timeframe) {
        return []
      }
      
      try {
        // Convert Unix timestamps to ISO strings
        const fromISO = this.unixToISO(fromTimestamp)
        const toISO = this.unixToISO(toTimestamp)
        
        // Make API request - request only fields needed for candlestick chart
        const response = await axios.get(`${API_BASE_URL}/api/v1/common/quotes`, {
          params: {
            source: this.source,
            symbol: this.symbol,
            timeframe: this.timeframe,
            date_start: fromISO,
            date_end: toISO,
            fields: 'time,open,high,low,close'
          }
        })
        
        return response.data || []
      } catch (error) {
        console.error('Failed to load quotes:', error)
        this.$emit('quotes-load-error', error)
        return []
      }
    },
    
    /**
     * Get timeframe in seconds
     */
    getTimeframeSeconds() {
      if (!this.timeframe) {
        return 0
      }
      
      // Parse timeframe string (e.g., "1h", "5m", "1d")
      const match = this.timeframe.match(/^(\d+)([smhd])$/)
      if (!match) {
        return 0
      }
      
      const value = parseInt(match[1], 10)
      const unit = match[2]
      
      switch (unit) {
        case 's':
          return value
        case 'm':
          return value * 60
        case 'h':
          return value * 3600
        case 'd':
          return value * 86400
        default:
          return 0
      }
    },
    
    /**
     * Convert ISO string to Unix timestamp (seconds)
     */
    isoToUnix(isoString) {
      return Math.floor(new Date(isoString).getTime() / 1000)
    },
    
    /**
     * Convert Unix timestamp (seconds) to ISO string
     */
    unixToISO(timestamp) {
      return new Date(timestamp * 1000).toISOString()
    },
    
    clearChartData() {
      if (this.candlestickSeries) {
        this.candlestickSeries.setData([])
        this.currentData = []
      }
      this.backtestingDateStart = null
      this.backtestingDateEnd = null
    },
    
    resetChart() {
      // Cancel any pending requests
      this.loadRequestId++
      this.isLoading = false
      this.clearChartData()
    },
    
    cleanup() {
      if (this.logicalRangeSubscription) {
        this.chart.timeScale().unsubscribeVisibleLogicalRangeChange(this.logicalRangeSubscription)
        this.logicalRangeSubscription = null
      }
      
      if (this.chart) {
        this.chart.remove()
        this.chart = null
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
