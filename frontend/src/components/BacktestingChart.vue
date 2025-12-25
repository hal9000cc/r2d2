<template>
  <div ref="chartContainer" class="backtesting-chart"></div>
</template>

<script>
import { createChart, ColorType, CandlestickSeries, LineSeries, createSeriesMarkers } from 'lightweight-charts'
import { inject } from 'vue'
import axios from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8202'

// Constants for dynamic data loading thresholds
const LOAD_THRESHOLD_MULTIPLIER = 1.0  // Multiplier for load threshold (minimum distance from edge to trigger load)
const LOAD_BARS_MULTIPLIER = 5.0       // Multiplier for number of bars to load
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
  setup() {
    // Inject backtesting results from parent
    const backtestingResults = inject('backtestingResults', null)
    return { backtestingResults }
  },
  data() {
    return {
      chart: null,
      candlestickSeries: null,
      seriesMarkers: null, // Markers API for the series (lightweight-charts 5.x)
      dealLines: [], // Array of line series for deals
      currentData: [], // Array of {time, open, high, low, close}
      
      // Logical range subscription
      logicalRangeSubscription: null,
      
      // ResizeObserver for automatic chart resizing
      resizeObserver: null,
      handleResizeBound: null, // Bound resize handler for cleanup
      
      // Backtesting bounds
      backtestingDateStart: null, // Unix timestamp in seconds
      backtestingDateEnd: null, // Unix timestamp in seconds (current_time from progress)
      
      // Loading state
      isLoading: false,
      loadRequestId: 0, // For canceling outdated requests
      
      // Flag to prevent event handling during data updates
      isUpdatingData: false,
      
      // Price scale mode
      isLogScale: false
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
    },
    showTradeMarkers() {
      this.updateTradeMarkers()
    },
    showDealLines() {
      this.updateDealLines()
    }
  },
  mounted() {
    this.initChart()
    this.setupLogicalRangeTracking()
    this.setupResizeObserver()
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
      
      // Create markers API for the series (lightweight-charts 5.x)
      this.seriesMarkers = createSeriesMarkers(this.candlestickSeries, [])
    },
    
    /**
     * Check boundaries and load data if needed
     * @param {Object} logicalRange - Current logical range
     * @param {boolean} skipUpdateCheck - Skip isUpdatingData check (for programmatic calls)
     */
    checkAndLoadData(logicalRange, skipUpdateCheck = false) {
      if (!logicalRange) return
      
      // Ignore events during data updates to prevent loops (unless explicitly skipped)
      if (!skipUpdateCheck && this.isUpdatingData) {
        return
      }
      
      const dataLength = this.currentData.length
      
      // Calculate visible length and dynamic thresholds
      const visibleLength = logicalRange.to - logicalRange.from
      const loadThreshold = Math.max(visibleLength * LOAD_THRESHOLD_MULTIPLIER, 300)
      
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
    },
    
    setupLogicalRangeTracking() {
      if (!this.chart) return
      
      // Subscribe to logical range changes (like in the example)
      this.logicalRangeSubscription = this.chart.timeScale().subscribeVisibleLogicalRangeChange((logicalRange) => {
        this.checkAndLoadData(logicalRange, false)
      })
    },
    
    /**
     * Setup ResizeObserver to automatically resize chart when container size changes
     */
    setupResizeObserver() {
      if (!this.$refs.chartContainer) {
        return
      }
      
      if (typeof ResizeObserver !== 'undefined') {
        this.resizeObserver = new ResizeObserver((entries) => {
          for (const entry of entries) {
            if (this.chart && entry.target === this.$refs.chartContainer) {
              // Use requestAnimationFrame to debounce resize calls
              requestAnimationFrame(() => {
                this.resizeChart()
              })
            }
          }
        })
        
        this.resizeObserver.observe(this.$refs.chartContainer)
      } else {
        // Fallback: use window resize if ResizeObserver is not available
        // Bind to component instance
        this.handleResizeBound = this.handleResize.bind(this)
        window.addEventListener('resize', this.handleResizeBound)
      }
    },
    
    /**
     * Resize chart to match container dimensions
     */
    resizeChart() {
      if (!this.chart || !this.$refs.chartContainer) {
        return
      }
      
      const width = this.$refs.chartContainer.clientWidth
      const height = this.$refs.chartContainer.clientHeight
      
      if (width > 0 && height > 0) {
        this.chart.resize(width, height)
      }
    },
    
    /**
     * Handle window resize (fallback for browsers without ResizeObserver)
     */
    handleResize() {
      this.resizeChart()
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
              
              // Set all data with visible range from 0 to visibleRange
              const finalLogicalRange = {
                from: 0,
                to: visibleRange
              }
              this.updateChartData(quotes, finalLogicalRange)
            } else {
              // Fallback: if logical range is not available, use fitContent
              this.updateChartData(quotes, null, { skipEmitState: true })
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
        
        // Update chart with all data
        this.updateChartData(mergedData, null, {
          cleanupDirection: 'future',
          useUpdatingFlag: true,
          delay: 250,
          requestId: requestId
        })
        
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
        
        // Update chart with all data
        // Note: barsAdded is used to adjust logicalRange after cleanup (new data added to start shifts indices)
        this.updateChartData(mergedData, null, {
          cleanupDirection: 'history',
          useUpdatingFlag: true,
          delay: 250,
          requestId: requestId,
          adjustLogicalRange: (afterCleanupRange) => ({
            from: afterCleanupRange.from + barsAdded,
            to: afterCleanupRange.to + barsAdded
          })
        })
        
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
     * Universal chart data update procedure
     * @param {Array} data - Data array to set
     * @param {Object} logicalRange - Visible logical range to set (optional)
     * @param {Object} options - Options:
     *   - cleanupDirection: 'future' | 'history' | null - Direction for cleanup (null = no cleanup)
     *   - useUpdatingFlag: boolean - Use isUpdatingData flag (default: false)
     *   - delay: number - Delay before update in ms (default: 0)
     *   - skipEmitState: boolean - Skip emitDataState (default: false)
     *   - adjustLogicalRange: function - Function to adjust logicalRange after cleanup (receives afterCleanupRange, returns adjustedRange)
     *   - requestId: number - Request ID to check (for delayed updates, to skip if outdated)
     */
    updateChartData(data, logicalRange = null, options = {}) {
      if (!this.chart || !this.candlestickSeries) {
        return
      }
      
      const {
        cleanupDirection = null,
        useUpdatingFlag = false,
        delay = 0,
        skipEmitState = false,
        adjustLogicalRange = null,
        requestId = null
      } = options
      
      const updateProcedure = () => {
        // Check if request is still relevant (for delayed updates)
        if (requestId !== null && requestId !== this.loadRequestId) {
          return
        }
        
        // Set flag to prevent event handling during update if needed
        if (useUpdatingFlag) {
          this.isUpdatingData = true
        }
        
        // Save logical range before cleanup if cleanup is needed
        let savedLogicalRange = null
        let visibleLength = 0
        
        if (cleanupDirection) {
          savedLogicalRange = this.chart.timeScale().getVisibleLogicalRange()
          visibleLength = savedLogicalRange ? (savedLogicalRange.to - savedLogicalRange.from) : 0
        }
        
        // Cleanup old data if needed
        let finalData = data
        let finalLogicalRange = logicalRange || savedLogicalRange
        
        if (cleanupDirection && savedLogicalRange) {
          const cleanupResult = this.cleanupOldData(cleanupDirection, visibleLength, data, savedLogicalRange)
          finalData = cleanupResult.cleanedData
          const afterCleanupLogicalRange = cleanupResult.adjustedLogicalRange || savedLogicalRange
          
          // Apply additional adjustment if provided
          if (adjustLogicalRange && typeof adjustLogicalRange === 'function') {
            finalLogicalRange = adjustLogicalRange(afterCleanupLogicalRange)
          } else {
            finalLogicalRange = afterCleanupLogicalRange
          }
        }
        
        // Update current data
        this.currentData = finalData
        
        // Set data on chart
        this.candlestickSeries.setData(finalData)
        
        // Update trade markers after setting data
        this.updateTradeMarkers()
        
        // Update deal lines after setting data
        this.updateDealLines()
        
        // Set visible logical range if provided
        if (finalLogicalRange) {
          this.chart.timeScale().setVisibleLogicalRange(finalLogicalRange)
        }
        
        // Emit data state
        if (!skipEmitState) {
          this.emitDataState(finalData, finalLogicalRange)
        }
        
        // Re-enable event handling after a delay if flag was used
        if (useUpdatingFlag) {
          setTimeout(() => {
            this.isUpdatingData = false
          }, 300)
        }
      }
      
      if (delay > 0) {
        setTimeout(updateProcedure, delay)
      } else {
        updateProcedure()
      }
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
     * Update trade markers on chart based on current data range
     * Always brings state in line with showTradeMarkers flag
     */
    updateTradeMarkers() {
      // Check initialization first
      if (!this.chart) {
        return
      }
      
      if (!this.seriesMarkers) {
        this.$emit('chart-message', {
          level: 'debug',
          message: 'seriesMarkers not initialized, skipping trade markers update'
        })
        return
      }
      
      if (!this.currentData || this.currentData.length === 0) {
        return
      }
      
      // If flag is false, clear markers
      if (!this.showTradeMarkers) {
        try {
          this.seriesMarkers.setMarkers([])
        } catch (error) {
          this.$emit('chart-message', {
            level: 'debug',
            message: `Failed to clear trade markers: ${error.message}`
          })
        }
        return
      }
      
      // Flag is true, show markers
      if (!this.backtestingResults) {
        return
      }
      
      if (!this.candlestickSeries) {
        return
      }
      
      // Get time range from current data
      const firstTime = this.currentData[0].time
      const lastTime = this.currentData[this.currentData.length - 1].time
      
      // Convert Unix timestamps (seconds) to ISO strings for getTradesByDateRange
      const fromISO = new Date(firstTime * 1000).toISOString()
      const toISO = new Date(lastTime * 1000).toISOString()
      
      // Get trades for this time range
      const tradesInRange = this.backtestingResults.getTradesByDateRange(fromISO, toISO)
      
      // If no trades, clear markers
      if (!tradesInRange || tradesInRange.length === 0) {
        try {
          this.seriesMarkers.setMarkers([])
        } catch (error) {
          this.$emit('chart-message', {
            level: 'debug',
            message: `Failed to clear trade markers: ${error.message}`
          })
        }
        return
      }
      
      // Use direct color values (lightweight-charts doesn't support CSS variables)
      // Note: In lightweight-charts, text color is automatically determined by background brightness
      // Dark colors = white text, light colors = black text
      // We use darker colors for better visibility, but text will be white (library limitation)
      const tradeBuyColor = '#0d5d4a' // Darker green for buy markers
      const tradeSellColor = '#8b1f1a' // Darker red for sell markers
      
      // Convert trades to markers
      const markers = tradesInRange.map(trade => {
        // Parse time from ISO string to Unix timestamp (seconds)
        const tradeTime = Math.floor(new Date(trade.time).getTime() / 1000)
        
        // Determine marker shape and position based on side
        const isBuy = trade.side === 'buy'
        
        return {
          time: tradeTime,
          position: isBuy ? 'belowBar' : 'aboveBar',
          color: isBuy ? tradeBuyColor : tradeSellColor,
          shape: isBuy ? 'arrowUp' : 'arrowDown',
          text: `${isBuy ? 'Buy' : 'Sell'}: ${parseFloat(trade.price).toFixed(2)}`
        }
      })
      
      // Set markers using seriesMarkers API (lightweight-charts 5.x)
      try {
        this.seriesMarkers.setMarkers(markers)
      } catch (error) {
        this.$emit('chart-message', {
          level: 'debug',
          message: `Failed to set trade markers: ${error.message}`
        })
      }
    },
    
    /**
     * Update deal lines on chart
     * Always brings state in line with showDealLines flag
     */
    updateDealLines() {
      // Check initialization first
      if (!this.chart) {
        return
      }
      
      if (!this.currentData || this.currentData.length === 0) {
        return
      }
      
      // Remove existing deal lines first (always, regardless of flag)
      try {
        this.dealLines.forEach(lineSeries => {
          this.chart.removeSeries(lineSeries)
        })
        this.dealLines = []
      } catch (error) {
        this.$emit('chart-message', {
          level: 'debug',
          message: `Failed to remove deal lines: ${error.message}`
        })
      }
      
      // If flag is false, we're done (lines already removed)
      if (!this.showDealLines) {
        return
      }
      
      // Flag is true, show lines
      if (!this.backtestingResults) {
        return
      }
      
      // Get all closed deals
      const allDeals = this.backtestingResults.getAllDeals()
      const closedDeals = allDeals.filter(deal => deal.is_closed)
      
      // For each closed deal, create a line
      closedDeals.forEach(deal => {
        // Get trades for this deal
        const dealTrades = this.backtestingResults.getTradesForDeal(deal.deal_id)
        
        if (dealTrades.length === 0) {
          return
        }
        
        // Get first and last trade times
        const firstTrade = dealTrades[0]
        const lastTrade = dealTrades[dealTrades.length - 1]
        
        // Convert times to Unix timestamps (seconds)
        const startTime = Math.floor(new Date(firstTrade.time).getTime() / 1000)
        const endTime = Math.floor(new Date(lastTrade.time).getTime() / 1000)
        
        // Determine start and end prices based on deal type
        let startPrice, endPrice
        if (deal.type && deal.type.toLowerCase() === 'long') {
          // LONG: from avg_buy_price to avg_sell_price
          startPrice = parseFloat(deal.avg_buy_price)
          endPrice = parseFloat(deal.avg_sell_price)
        } else if (deal.type && deal.type.toLowerCase() === 'short') {
          // SHORT: from avg_sell_price to avg_buy_price
          startPrice = parseFloat(deal.avg_sell_price)
          endPrice = parseFloat(deal.avg_buy_price)
        } else {
          // Unknown type, skip
          return
        }
        
        // Determine color based on profit
        const profit = parseFloat(deal.profit || 0)
        const lineColor = profit >= 0 ? '#4caf50' : '#f44336' // Green for profit, red for loss
        
        // Create line series for this deal
        // In lightweight-charts 5.x, use addSeries() with LineSeries type
        try {
          const lineSeries = this.chart.addSeries(LineSeries, {
            color: lineColor,
            lineWidth: 1,
            lineStyle: 2, // Dashed line (0 = solid, 1 = dotted, 2 = dashed, 3 = large dashed, 4 = sparse dotted)
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false
          })
          
          // Set data: two points (start and end)
          lineSeries.setData([
            { time: startTime, value: startPrice },
            { time: endTime, value: endPrice }
          ])
          
          // Store line series reference
          this.dealLines.push(lineSeries)
        } catch (error) {
          this.$emit('chart-message', {
            level: 'debug',
            message: `Failed to add deal line for deal ${deal.deal_id}: ${error.message}`
          })
        }
      })
    },
    
    /**
     * Universal data loading procedure
     * @param {string} dataType - Type of data to load ('quotes', 'deals', 'indicators', etc.)
     * @param {number} fromTimestamp - Start timestamp in Unix seconds
     * @param {number} toTimestamp - End timestamp in Unix seconds
     * @param {Object} options - Additional options (fields, etc.)
     * @returns {Promise<Array>} Loaded data array
     */
    async loadData(dataType, fromTimestamp, toTimestamp, options = {}) {
      if (!this.source || !this.symbol || !this.timeframe) {
        return []
      }
      
      try {
        // Convert Unix timestamps to ISO strings
        const fromISO = this.unixToISO(fromTimestamp)
        const toISO = this.unixToISO(toTimestamp)
        
        // Build request parameters
        const params = {
          source: this.source,
          symbol: this.symbol,
          timeframe: this.timeframe,
          date_start: fromISO,
          date_end: toISO
        }
        
        // Add type-specific parameters
        if (dataType === 'quotes') {
          // For quotes, request only fields needed for candlestick chart
          params.fields = options.fields || 'time,open,high,low,close'
        }
        // Future: add handling for 'deals', 'indicators', etc.
        
        // Determine API endpoint based on data type
        let endpoint = '/api/v1/common/quotes'
        if (dataType === 'quotes') {
          endpoint = '/api/v1/common/quotes'
        }
        // Future: add endpoints for other data types
        // else if (dataType === 'deals') {
        //   endpoint = '/api/v1/common/deals'
        // }
        
        // Make API request
        const response = await axios.get(`${API_BASE_URL}${endpoint}`, { params })
        
        return response.data || []
      } catch (error) {
        console.error(`Failed to load ${dataType}:`, error)
        this.$emit('quotes-load-error', error)
        return []
      }
    },
    
    /**
     * Load quotes from API (wrapper for loadData)
     * @param {number} fromTimestamp - Start timestamp in Unix seconds
     * @param {number} toTimestamp - End timestamp in Unix seconds
     * @returns {Promise<Array>} Loaded quotes array
     */
    async loadQuotes(fromTimestamp, toTimestamp) {
      return this.loadData('quotes', fromTimestamp, toTimestamp)
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
      // Disconnect ResizeObserver
      if (this.resizeObserver) {
        this.resizeObserver.disconnect()
        this.resizeObserver = null
      }
      
      // Remove window resize listener (fallback)
      if (this.handleResizeBound) {
        window.removeEventListener('resize', this.handleResizeBound)
        this.handleResizeBound = null
      }
      
      // Unsubscribe from logical range changes
      if (this.logicalRangeSubscription && this.chart) {
        this.chart.timeScale().unsubscribeVisibleLogicalRangeChange(this.logicalRangeSubscription)
        this.logicalRangeSubscription = null
      }
      
      // Remove chart
      if (this.chart) {
        this.chart.remove()
        this.chart = null
      }
    },
    
    /**
     * Navigate to a specific date/time
     * @param {number} timestamp - Unix timestamp in seconds
     */
    async goToDate(timestamp) {
      if (!this.chart || !this.backtestingDateStart || !this.backtestingDateEnd) {
        return
      }
      
      if (!this.source || !this.symbol || !this.timeframe) {
        return
      }
      
      // Get current visible length to maintain zoom level
      const currentLogicalRange = this.chart.timeScale().getVisibleLogicalRange()
      if (!currentLogicalRange) {
        return
      }
      
      const visibleLength = currentLogicalRange.to - currentLogicalRange.from
      const timeframeSeconds = this.getTimeframeSeconds()
      if (timeframeSeconds === 0) {
        return
      }
      
      // Calculate load range
      // From: timestamp - (visibleLength * LOAD_BARS_MULTIPLIER * timeframeSeconds)
      const loadFrom = Math.max(
        this.backtestingDateStart,
        timestamp - (visibleLength * LOAD_BARS_MULTIPLIER * timeframeSeconds)
      )
      
      // To: timestamp + ((visibleLength * LOAD_BARS_MULTIPLIER + visibleLength) * timeframeSeconds)
      const loadTo = Math.min(
        this.backtestingDateEnd,
        timestamp + ((visibleLength * LOAD_BARS_MULTIPLIER + visibleLength) * timeframeSeconds)
      )
      
      if (loadFrom >= loadTo) {
        return
      }
      
      // Load data
      this.isLoading = true
      try {
        const quotes = await this.loadQuotes(loadFrom, loadTo)
        
        if (quotes.length === 0) {
          return
        }
        
        // Find the bar closest to the target timestamp
        let targetBarIndex = -1
        let minDiff = Infinity
        
        for (let i = 0; i < quotes.length; i++) {
          const diff = Math.abs(quotes[i].time - timestamp)
          if (diff < minDiff) {
            minDiff = diff
            targetBarIndex = i
          }
        }
        
        if (targetBarIndex === -1) {
          return
        }
        
        // Set data with visible range: from = targetBarIndex, to = targetBarIndex + visibleLength
        const finalLogicalRange = {
          from: targetBarIndex,
          to: Math.min(targetBarIndex + visibleLength, quotes.length)
        }
        this.updateChartData(quotes, finalLogicalRange)
      } catch (error) {
        console.error('Failed to navigate to date:', error)
        this.$emit('quotes-load-error', error)
      } finally {
        this.isLoading = false
      }
    },
    
    /**
     * Navigate to the start of the chart data
     */
    async goToStart() {
      if (!this.chart || !this.backtestingDateStart || !this.backtestingDateEnd) {
        return
      }
      
      if (!this.source || !this.symbol || !this.timeframe) {
        return
      }
      
      // Get current visible length to maintain zoom level
      const currentLogicalRange = this.chart.timeScale().getVisibleLogicalRange()
      if (!currentLogicalRange) {
        return
      }
      
      const visibleLength = currentLogicalRange.to - currentLogicalRange.from
      const timeframeSeconds = this.getTimeframeSeconds()
      if (timeframeSeconds === 0) {
        return
      }
      
      // Calculate number of bars to load: visibleLength * LOAD_BARS_MULTIPLIER
      const barsToLoad = visibleLength * LOAD_BARS_MULTIPLIER
      const timeRangeToLoad = barsToLoad * timeframeSeconds
      
      // Load from backtestingDateStart
      const loadFrom = this.backtestingDateStart
      const loadTo = Math.min(
        this.backtestingDateEnd,
        this.backtestingDateStart + timeRangeToLoad
      )
      
      if (loadFrom >= loadTo) {
        return
      }
      
      // Load data
      this.isLoading = true
      try {
        const quotes = await this.loadQuotes(loadFrom, loadTo)
        
        if (quotes.length === 0) {
          return
        }
        
        // Set data with visible range: from 0 to visibleLength
        const finalLogicalRange = {
          from: 0,
          to: Math.min(visibleLength, quotes.length)
        }
        this.updateChartData(quotes, finalLogicalRange)
      } catch (error) {
        console.error('Failed to navigate to start:', error)
        this.$emit('quotes-load-error', error)
      } finally {
        this.isLoading = false
      }
    },
    
    /**
     * Navigate to the end of the chart data
     */
    async goToEnd() {
      if (!this.chart || !this.backtestingDateStart || !this.backtestingDateEnd) {
        return
      }
      
      if (!this.source || !this.symbol || !this.timeframe) {
        return
      }
      
      // Get current visible length to maintain zoom level
      const currentLogicalRange = this.chart.timeScale().getVisibleLogicalRange()
      if (!currentLogicalRange) {
        return
      }
      
      const visibleLength = currentLogicalRange.to - currentLogicalRange.from
      const timeframeSeconds = this.getTimeframeSeconds()
      if (timeframeSeconds === 0) {
        return
      }
      
      // Calculate number of bars to load from end
      // Load from: (visibleLength * LOAD_BARS_MULTIPLIER + visibleLength) bars before end
      const barsToLoad = visibleLength * LOAD_BARS_MULTIPLIER + visibleLength
      const timeRangeToLoad = barsToLoad * timeframeSeconds
      
      // Load to backtestingDateEnd
      const loadTo = this.backtestingDateEnd
      const loadFrom = Math.max(
        this.backtestingDateStart,
        this.backtestingDateEnd - timeRangeToLoad
      )
      
      if (loadFrom >= loadTo) {
        return
      }
      
      // Load data
      this.isLoading = true
      try {
        const quotes = await this.loadQuotes(loadFrom, loadTo)
        
        if (quotes.length === 0) {
          return
        }
        
        // Set data with visible range: from end - visibleLength to end
        const finalLogicalRange = {
          from: Math.max(0, quotes.length - visibleLength),
          to: quotes.length
        }
        this.updateChartData(quotes, finalLogicalRange)
      } catch (error) {
        console.error('Failed to navigate to end:', error)
        this.$emit('quotes-load-error', error)
      } finally {
        this.isLoading = false
      }
    },
    
    /**
     * Toggle logarithmic price scale
     */
    toggleLogScale() {
      if (!this.chart || !this.candlestickSeries) {
        return
      }
      
      this.isLogScale = !this.isLogScale
      
      // Apply log scale through series options
      this.candlestickSeries.applyOptions({
        priceScaleId: '',
        priceFormat: {
          type: 'price',
          precision: 2,
          minMove: 0.01
        }
      })
      
      // Apply log scale to the price scale
      const priceScale = this.chart.priceScale('')
      if (priceScale) {
        priceScale.applyOptions({
          logScale: this.isLogScale
        })
      }
      
      // Emit event to update parent component state
      this.$emit('log-scale-changed', this.isLogScale)
    },
    
    /**
     * Auto-scale to fit all data
     */
    autoScale() {
      if (!this.chart) {
        return
      }
      
      this.chart.timeScale().fitContent()
    },
    
    /**
     * Scroll chart one page forward (PageDown)
     */
    pageDown() {
      if (!this.chart || !this.currentData || this.currentData.length === 0) {
        return
      }
      
      const currentLogicalRange = this.chart.timeScale().getVisibleLogicalRange()
      if (!currentLogicalRange) {
        return
      }
      
      const visibleLength = currentLogicalRange.to - currentLogicalRange.from
      const dataLength = this.currentData.length
      
      // Calculate new range: from = to + 1, to = from + visibleLength
      const newFrom = Math.floor(currentLogicalRange.to) + 1
      const newTo = newFrom + visibleLength
      
      // Set new visible range (even if beyond current data - this will trigger loading)
      this.chart.timeScale().setVisibleLogicalRange({
        from: newFrom,
        to: newTo
      })
      
      // Wait for chart to update, then check boundaries and load data if needed
      this.$nextTick(() => {
        const newLogicalRange = this.chart.timeScale().getVisibleLogicalRange()
        if (newLogicalRange) {
          this.checkAndLoadData(newLogicalRange, true)
        }
      })
    },
    
    /**
     * Scroll chart one page backward (PageUp)
     */
    pageUp() {
      if (!this.chart || !this.currentData || this.currentData.length === 0) {
        return
      }
      
      const currentLogicalRange = this.chart.timeScale().getVisibleLogicalRange()
      if (!currentLogicalRange) {
        return
      }
      
      const visibleLength = currentLogicalRange.to - currentLogicalRange.from
      
      // Calculate new range: to = from - 1, from = to - visibleLength
      const newTo = Math.floor(currentLogicalRange.from) - 1
      const newFrom = newTo - visibleLength
      
      // Set new visible range (even if before current data - this will trigger loading)
      this.chart.timeScale().setVisibleLogicalRange({
        from: newFrom,
        to: newTo
      })
      
      // Wait for chart to update, then check boundaries and load data if needed
      this.$nextTick(() => {
        const newLogicalRange = this.chart.timeScale().getVisibleLogicalRange()
        if (newLogicalRange) {
          this.checkAndLoadData(newLogicalRange, true)
        }
      })
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
