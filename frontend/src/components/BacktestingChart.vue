<template>
  <div ref="chartContainer" class="backtesting-chart"></div>
</template>

<script>
import { createChart, ColorType, CandlestickSeries } from 'lightweight-charts'
import axios from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8202'

// Constants for dynamic data loading thresholds
const LOAD_THRESHOLD_MULTIPLIER = 1.0  // Multiplier for load threshold (minimum distance from edge to trigger load)
const LOAD_BARS_MULTIPLIER = 2.0       // Multiplier for number of bars to load
const CLEANUP_THRESHOLD_MULTIPLIER = 5.0  // Multiplier for cleanup threshold (when to remove old data)

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
        
        // Calculate visible length and dynamic thresholds
        const visibleLength = logicalRange.to - logicalRange.from
        const loadThreshold = Math.max(visibleLength * LOAD_THRESHOLD_MULTIPLIER, 300)
        //const numberBarsToLoad = Math.max(visibleLength * LOAD_BARS_MULTIPLIER, 600)
        
        // Load more data when approaching the start (scrolling left)
        // Calculate left boundary condition: logicalRange.from - visibleLength * LOAD_THRESHOLD_MULTIPLIER
        const leftBoundaryIndex = logicalRange.from - visibleLength * LOAD_THRESHOLD_MULTIPLIER
        
        if (leftBoundaryIndex < 0) {
          // Need to load more history
          // Calculate index of bar to load: logicalRange.from - visibleLength * LOAD_BARS_MULTIPLIER
          const loadBarIndex = logicalRange.from - visibleLength * LOAD_BARS_MULTIPLIER
          const barsToLoad = Math.abs(loadBarIndex) // This is negative, so we need absolute value
          
          this.loadMoreHistory(barsToLoad)
        }
        
        // Load more data when approaching the end (scrolling right)
        // Check if bars after right boundary are less than threshold
        if (logicalRange.to !== null && logicalRange.to > 0) {
          const barsAfterRightBoundary = dataLength - logicalRange.to
          
          // If we're within threshold of end (or already beyond it)
          if (barsAfterRightBoundary < loadThreshold) {
            // Calculate right boundary for loading: logicalRange.to + visibleLength * LOAD_BARS_MULTIPLIER
            const rightBoundaryIndex = logicalRange.to + visibleLength * LOAD_BARS_MULTIPLIER
            this.loadMoreFuture(rightBoundaryIndex)
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
      
      // Limit initial load to maximum 5000 bars
      const timeframeSeconds = this.getTimeframeSeconds()
      const maxBars = 5000
      const maxTimeRange = maxBars * timeframeSeconds
      const maxDateEnd = this.backtestingDateStart + maxTimeRange
      const limitedDateEnd = Math.min(this.backtestingDateEnd, maxDateEnd)
      
      // Load initial data: from date_start to limited date_end (max 5000 bars)
      const quotes = await this.loadQuotes(this.backtestingDateStart, limitedDateEnd)
      
      if (quotes.length > 0) {
        this.currentData = quotes
        
        // Set initial single bar to determine visible range
        this.candlestickSeries.setData([quotes[0]])
        
        // Get visible logical range with single bar
        this.$nextTick(() => {
          if (this.chart) {
            const logicalRange = this.chart.timeScale().getVisibleLogicalRange()
            if (logicalRange) {
              // Calculate visible range (number of bars)
              const visibleRange = logicalRange.to - logicalRange.from
              
              // Set all data
              this.candlestickSeries.setData(quotes)
              
              // Set visible range from 0 to visibleRange
              const finalLogicalRange = {
                from: 0,
                to: visibleRange
              }
              this.chart.timeScale().setVisibleLogicalRange(finalLogicalRange)
              
              // Emit data state
              this.emitDataState(quotes, finalLogicalRange)
            } else {
              // Fallback: if logical range is not available, use fitContent
              this.candlestickSeries.setData(quotes)
              this.chart.timeScale().fitContent()
              
              // Emit data state with current logical range
              this.$nextTick(() => {
                const currentLogicalRange = this.chart.timeScale().getVisibleLogicalRange()
                this.emitDataState(quotes, currentLogicalRange)
              })
            }
          }
        })
      }
    },
    
    /**
     * Load more future data (when scrolling right)
     * @param {number} rightBoundaryIndex - Target bar index (logicalRange.to + visibleLength * LOAD_BARS_MULTIPLIER)
     */
    async loadMoreFuture(rightBoundaryIndex) {
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
      
      const dataLength = this.currentData.length
      const latestTime = this.currentData[dataLength - 1].time
      
      // Start loading from the next period after the latest known time
      const loadFrom = latestTime + timeframeSeconds
      
      // Calculate loadTo based on rightBoundaryIndex
      let loadTo
      if (rightBoundaryIndex >= dataLength) {
        // Target index is at or beyond current data, calculate time
        // We need to load at least 1 bar, so if rightBoundaryIndex === dataLength, load 1 bar
        const barsToLoad = Math.max(1, rightBoundaryIndex - dataLength)
        loadTo = latestTime + barsToLoad * timeframeSeconds
      } else {
        // Target index is within current data, use that bar's time
        loadTo = this.currentData[rightBoundaryIndex].time
      }
      
      // Clamp to maximum backtesting date if available
      let finalTo = loadTo
      if (this.backtestingDateEnd) {
        finalTo = Math.min(loadTo, this.backtestingDateEnd)
      }
      
      // If we've reached the limit - don't load
      if (loadFrom >= finalTo) {
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
            // Set flag to prevent event handling during update
            this.isUpdatingData = true
            
            // Save logical range before cleanup
            const savedLogicalRange = this.chart.timeScale().getVisibleLogicalRange()
            
            // Cleanup old data if needed (remove data beyond cleanup threshold)
            // Get visibleLength from saved logical range
            const visibleLength = savedLogicalRange ? (savedLogicalRange.to - savedLogicalRange.from) : 0
            const cleanupResult = this.cleanupOldData('future', visibleLength, mergedData, savedLogicalRange)
            
            // Use cleaned data and adjusted logical range
            const finalData = cleanupResult.cleanedData
            const finalLogicalRange = cleanupResult.adjustedLogicalRange || savedLogicalRange
            
            this.currentData = finalData
            this.candlestickSeries.setData(finalData)
            
            // Restore logical range after setData
            if (finalLogicalRange) {
              this.chart.timeScale().setVisibleLogicalRange(finalLogicalRange)
            }
            
            // Emit data state after cleanup
            this.emitDataState(finalData, finalLogicalRange)
            
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
     * @param {number} barsToLoad - Number of bars to load (absolute value of negative index)
     */
    async loadMoreHistory(barsToLoad) {
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
      // loadTo = time of first bar - timeframe (last bar to load)
      const earliestTime = this.currentData[0].time
      const loadTo = earliestTime - timeframeSeconds
      
      // loadFrom = earliestTime - (barsToLoad * timeframeSeconds)
      const timeRangeToLoad = barsToLoad * timeframeSeconds
      let loadFrom = earliestTime - timeRangeToLoad
      
      // If we've reached the start of backtesting period, we cannot load more
      if (this.backtestingDateStart && earliestTime <= this.backtestingDateStart) {
        return
      }
      
      // Clamp loadFrom to backtesting start date if needed
      if (this.backtestingDateStart && loadFrom < this.backtestingDateStart) {
        loadFrom = this.backtestingDateStart
      }
      
      // Final check: if loadFrom >= loadTo, we can't load
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
        const barsAdded = mergedData.length - this.currentData.length
        if (barsAdded === 0) {
          return
        }

        // Sort by time to ensure correct order
        mergedData.sort((a, b) => a.time - b.time)
        
        // Update chart with all data (like in the example)
        setTimeout(() => {
          if (requestId === this.loadRequestId) {
            // Set flag to prevent event handling during update
            this.isUpdatingData = true
            
            // Save logical range before cleanup
            const savedLogicalRange = this.chart.timeScale().getVisibleLogicalRange()
            
            // Cleanup old data if needed (remove data beyond cleanup threshold)
            // Get visibleLength from saved logical range
            const visibleLength = savedLogicalRange ? (savedLogicalRange.to - savedLogicalRange.from) : 0
            const cleanupResult = this.cleanupOldData('history', visibleLength, mergedData, savedLogicalRange)
            
            // Use cleaned data and adjusted logical range
            const finalData = cleanupResult.cleanedData
            const afterCleanupLogicalRange = cleanupResult.adjustedLogicalRange || savedLogicalRange
            
            const finalLogicalRange = {
              from: afterCleanupLogicalRange.from + barsAdded,
              to: afterCleanupLogicalRange.to + barsAdded
            }

            this.currentData = finalData
            this.candlestickSeries.setData(finalData)
            
            // Restore logical range after setData
            if (finalLogicalRange) {
              this.chart.timeScale().setVisibleLogicalRange(finalLogicalRange)
            }
            
            // Emit data state after cleanup
            this.emitDataState(finalData, finalLogicalRange)
            
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
     * Cleanup old data to free memory
     * @param {string} direction - 'future' or 'history'
     * @param {number} visibleLength - Number of visible bars
     * @param {Array} dataToClean - Data array to clean (mergedData)
     * @param {Object} savedLogicalRange - Saved logical range (for history cleanup)
     * @returns {Object} { cleanedData, adjustedLogicalRange }
     */
    cleanupOldData(direction, visibleLength, dataToClean, savedLogicalRange = null) {
      // Default return: no cleanup performed
      const defaultResult = {
        cleanedData: dataToClean,
        adjustedLogicalRange: savedLogicalRange
      }
      
      if (!dataToClean || dataToClean.length === 0 || visibleLength === 0) {
        return defaultResult
      }
      
      // Calculate cleanup threshold
      const cleanupThreshold = visibleLength * CLEANUP_THRESHOLD_MULTIPLIER
      
      if (!savedLogicalRange) {
        return defaultResult
      }
      
      let cleanedData = []
      let barsRemoved = 0
      let adjustedLogicalRange = savedLogicalRange
      
      if (direction === 'future') {
        // Remove old data from the beginning (keep visible area + buffer)
        // Keep data from (logicalRange.from - visibleLength) to end
        const keepFromIndex = Math.max(0, Math.floor(savedLogicalRange.from) - Math.floor(cleanupThreshold))
        if (keepFromIndex === 0) {
          return defaultResult
        }
        cleanedData = dataToClean.slice(keepFromIndex)
        barsRemoved = keepFromIndex
        // For future cleanup: we remove data from start, so indices shift left
        // Adjust logical range: subtract removed bars from both boundaries
        adjustedLogicalRange = {
          from: savedLogicalRange.from - barsRemoved,
          to: savedLogicalRange.to - barsRemoved
        }
        // Ensure adjusted range is valid
        if (adjustedLogicalRange.from < 0 || adjustedLogicalRange.to <= adjustedLogicalRange.from) {
          adjustedLogicalRange = savedLogicalRange
        }
      } else if (direction === 'history') {
        // Remove new data from the end (keep visible area + buffer)
        // Keep data from start to (logicalRange.to + visibleLength)
        const keepToIndex = Math.min(
          dataToClean.length,
          Math.ceil(savedLogicalRange.to) + Math.ceil(cleanupThreshold)
        )
        cleanedData = dataToClean.slice(0, keepToIndex)
        barsRemoved = dataToClean.length - keepToIndex
        // For history cleanup: we remove data from end, indices at start don't change
        // But savedLogicalRange was calculated before new data was added to start
        // After adding data to start, indices shift right by number of new bars
        // After removing data from end, indices at start remain the same
        // So savedLogicalRange remains valid (no adjustment needed)
        adjustedLogicalRange = savedLogicalRange
      }
      
      // Only return cleaned data if we actually removed data
      if (barsRemoved > 0 && cleanedData.length < dataToClean.length) {
        return {
          cleanedData,
          adjustedLogicalRange
        }
      }
      
      return defaultResult
    },
    
    /**
     * Emit data state message with comprehensive information
     * @param {Array} data - Data array used in setData
     * @param {Object} logicalRange - Visible logical range
     */
    emitDataState(data, logicalRange) {
      if (!data || data.length === 0) {
        return
      }
      
      // Calculate data info
      const barCount = data.length
      const firstBarDate = new Date(data[0].time * 1000).toISOString()
      const lastBarDate = new Date(data[data.length - 1].time * 1000).toISOString()
      
      // Calculate visible range info
      let visibleRangeStart = 'N/A'
      let visibleRangeEnd = 'N/A'
      
      if (logicalRange && logicalRange.from !== null && logicalRange.to !== null) {
        const fromIndex = Math.max(0, Math.floor(logicalRange.from))
        const toIndex = Math.min(data.length - 1, Math.ceil(logicalRange.to))
        
        if (fromIndex < data.length && toIndex < data.length && fromIndex <= toIndex) {
          visibleRangeStart = new Date(data[fromIndex].time * 1000).toISOString()
          visibleRangeEnd = new Date(data[toIndex].time * 1000).toISOString()
        }
      }
      
      // Format message: bars count, first bar date, last bar date, visible range start, visible range end
      const message = `${barCount} bars | First: ${firstBarDate} | Last: ${lastBarDate} | Visible: ${visibleRangeStart} to ${visibleRangeEnd}`
      
      this.$emit('chart-message', {
        level: 'info',
        message
      })
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
