<template>
  <div 
    ref="chartContainer" 
    class="backtesting-chart"
    tabindex="0"
    @keydown="handleKeyDown"
  ></div>
</template>

<script>
import { createChart, ColorType, CandlestickSeries, LineSeries, createSeriesMarkers } from 'lightweight-charts'
import { inject } from 'vue'
import axios from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8202'

const LOAD_THRESHOLD_MULTIPLIER = 1.2  // Multiplier for load threshold (minimum distance from edge to trigger load)
const LOAD_BARS_MULTIPLIER = 1.8       // Multiplier for number of bars to load
const CLEANUP_THRESHOLD_MULTIPLIER = 3.0  // Multiplier for cleanup threshold (when to remove old data)

// Trade marker colors
const TRADE_BUY_COLOR = '#0d5d4a'  // Darker green for buy markers
const TRADE_SELL_COLOR = '#8b1f1a' // Darker red for sell markers

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
  emits: ['chart-cleared', 'log-scale-changed', 'quotes-load-error'],
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
      
      // ResizeObserver for automatic chart resizing
      resizeObserver: null,
      handleResizeBound: null, // Bound resize handler for cleanup
      
      // Backtesting bounds
      backtestingDateStart: null, // Unix timestamp in seconds
      backtestingDateEnd: null, // Unix timestamp in seconds (current_time from progress)
      
      currentData: [], // Array of {time, open, high, low, close}
      
      // Flags to block concurrent updates
      isUpdatingChart: false,      // Flag for chart bars update
      isUpdatingTradeMarkers: false, // Flag for trade markers update
      isUpdatingDealLines: false,   // Flag for deal lines update
      
      // Debounce mechanism for visible range changes
      debounceTimer: null,
      
      // Debounce timer for chart other elements (trades, markers, etc.)
      othersDebounceTimer: null,
      
      // Logical range subscription
      logicalRangeSubscription: null,
      
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
    /**
     * Check if chart is busy with any update operation
     * @returns {boolean} True if any update is in progress
     */
    chartIsBusy() {
      return this.isUpdatingChart || this.isUpdatingTradeMarkers || this.isUpdatingDealLines
    },
    
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
          secondsVisible: false,
          shiftVisibleRangeOnNewBar: false  // Disable automatic range shift when new data is added
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
     * Setup subscription to visible logical range changes
     */
    setupLogicalRangeTracking() {
      if (!this.chart) {
        return
      }
      
      // Subscribe to logical range changes with debounce mechanism
      this.logicalRangeSubscription = this.chart.timeScale().subscribeVisibleLogicalRangeChange((logicalRange) => {
        this.handleVisibleRangeChange(logicalRange)
      })
    },
    
    /**
     * Handle visible range change with debounce
     * @param {Object} logicalRange - Current logical range
     */
    handleVisibleRangeChange(logicalRange) {
      // If chart is being updated, ignore the event
      if (this.chartIsBusy()) {
        return
      }
      
      // Update chart other elements (trades, markers, etc.) with separate debounce
      // Reset others debounce timer
      if (this.othersDebounceTimer) {
        clearTimeout(this.othersDebounceTimer)
      }
      
      // Start new debounce timer for other elements (longer delay)
      this.othersDebounceTimer = setTimeout(() => {
        this.othersDebounceTimer = null
        this.updateChartOthers(logicalRange)
      }, 250)
      
      // Reset current debounce timer for data loading
      if (this.debounceTimer) {
        clearTimeout(this.debounceTimer)
      }
      
      // Start new debounce timer for data loading
      this.debounceTimer = setTimeout(() => {
        this.debounceTimer = null
        this.processRangeChange()
      }, 100)
    },
    
    /**
     * Process visible range change (called after debounce)
     */
    processRangeChange() {
      // If chart is being updated, skip
      if (this.chartIsBusy()) {
        return
      }
      
      // Update chart bars
      this.updateChartBars()
    },
    
    /**
     * Handle backtesting progress update
     */
    handleBacktestingProgress(progress) {
      // If chart is already initialized, ignore all subsequent progress messages
      if (this.backtestingDateStart !== null) {
        return
      }
      
      // Convert ISO strings to Unix timestamps
      const dateStart = progress.date_start ? this.isoToUnix(progress.date_start) : null
      const dateCurrent = progress.current_time ? this.isoToUnix(progress.current_time) : null
      
      if (!dateStart || !dateCurrent) {
        return
      }
      
      // Update backtesting bounds (only on first progress)
      this.backtestingDateStart = dateStart
      this.backtestingDateEnd = dateCurrent
      
      // Load initial data on first progress
      this.loadInitialData()
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
      const maxBars = 1
      const maxTimeRange = maxBars * timeframeSeconds
      const maxDateEnd = this.backtestingDateStart + maxTimeRange
      const limitedDateEnd = Math.min(this.backtestingDateEnd, maxDateEnd)
      
      // Load initial data: from date_start to limited date_end (max 5000 bars)
      const quotes = await this.loadQuotes(this.backtestingDateStart, limitedDateEnd)
      
      if (quotes.length > 0) {
        // Set initial single bar to determine visible range
        this.candlestickSeries.setData([quotes[0]])
        
        // Move to begin
        this.$nextTick(async () => {
          await this.moveToBegin()
        })
      }
    },
    
    /**
     * Move chart view to the beginning (start of backtesting period)
     * Loads initial data and sets visible range
     */
    async moveToBegin() {
      if (!this.chart || !this.candlestickSeries) {
        return
      }
      
      // Don't run if chart is busy with any operation
      if (this.chartIsBusy()) {
        return
      }
      
      // Check if backtesting dates are set
      if (!this.backtestingDateStart || !this.backtestingDateEnd) {
        return
      }
      
      const logicalRange = this.chart.timeScale().getVisibleLogicalRange()
      if (!logicalRange) {
        return
      }
      
      // Calculate visible range (number of bars)
      const visibleRange = logicalRange.to - logicalRange.from
      
      // Calculate timeframe in seconds
      const timeframeSeconds = this.getTimeframeSeconds()
      if (timeframeSeconds === 0) {
        return
      }
      
      // Calculate time range to load: visibleRange bars
      const timeRangeToLoad = visibleRange * (1 + LOAD_BARS_MULTIPLIER) * timeframeSeconds
      const loadFrom = this.backtestingDateStart
      const loadTo = Math.min(
        this.backtestingDateEnd,
        this.backtestingDateStart + timeRangeToLoad
      )
      
      // Block visible range updates during chart update
      this.isUpdatingChart = true
      try {
        // Load quotes for visible range
        const loadedQuotes = await this.loadQuotes(loadFrom, loadTo)
        
        if (loadedQuotes.length > 0) {
          // Update current data
          this.currentData = loadedQuotes
          
          // Set data on chart
          this.candlestickSeries.setData(loadedQuotes)
          
          // Set visible logical range from 0 to visibleRange
          this.chart.timeScale().setVisibleLogicalRange({
            from: 0,
            to: visibleRange
          })
        }
      } finally {
        this.isUpdatingChart = false
      }
    },
    
    /**
     * Move chart view to the end (current time of backtesting)
     * Loads data from end and sets visible range
     */
    async moveToEnd() {
      if (!this.chart || !this.candlestickSeries) {
        return
      }
      
      // Don't run if chart is busy with any operation
      if (this.chartIsBusy()) {
        return
      }
      
      // Check if backtesting dates are set
      if (!this.backtestingDateStart || !this.backtestingDateEnd) {
        return
      }
      
      // Check if source, symbol, and timeframe are set
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
      
      // Block visible range updates during chart update
      this.isUpdatingChart = true
      try {
        // Load quotes from calculated range
        const loadedQuotes = await this.loadQuotes(loadFrom, loadTo)
        
        if (loadedQuotes.length === 0) {
          return
        }
        
        // Update current data
        this.currentData = loadedQuotes
        
        // Set data on chart
        this.candlestickSeries.setData(loadedQuotes)
        
        // Set visible logical range: from end - visibleLength to end
        this.chart.timeScale().setVisibleLogicalRange({
          from: Math.max(0, loadedQuotes.length - visibleLength),
          to: loadedQuotes.length
        })
      } finally {
        this.isUpdatingChart = false
      }
    },
    
    /**
     * Calculate number of bars to load on the left side
     * @param {number} from - Start index of visible range (logical range from)
     * @param {number} to - End index of visible range (logical range to)
     * @returns {number} Number of bars to load (0 if no load needed)
     */
    calculateBarsToLoadLeft(from, to) {
      if (!this.currentData || this.currentData.length === 0) {
        return 0
      }
      
      const visibleLength = to - from
      const barsOnLeft = from
      const loadThreshold = visibleLength * LOAD_THRESHOLD_MULTIPLIER
      
      // If we have enough bars on the left, no need to load
      if (barsOnLeft >= loadThreshold) {
        return 0
      }
      
      // Calculate how many bars we need to have on the left after loading
      const targetBarsOnLeft = visibleLength * LOAD_BARS_MULTIPLIER
      
      // Calculate how many bars to load
      const barsToLoad = Math.max(0, targetBarsOnLeft - barsOnLeft)
      
      return barsToLoad
    },
    
    /**
     * Calculate number of bars to load on the right side
     * @param {number} from - Start index of visible range (logical range from)
     * @param {number} to - End index of visible range (logical range to)
     * @returns {number} Number of bars to load (0 if no load needed)
     */
    calculateBarsToLoadRight(from, to) {
      if (!this.currentData || this.currentData.length === 0) {
        return 0
      }
      
      const visibleLength = to - from
      const barsOnRight = this.currentData.length - to
      const loadThreshold = visibleLength * LOAD_THRESHOLD_MULTIPLIER
      
      // If we have enough bars on the right, no need to load
      if (barsOnRight >= loadThreshold) {
        return 0
      }
      
      // Calculate how many bars we need to have on the right after loading
      const targetBarsOnRight = visibleLength * LOAD_BARS_MULTIPLIER
      
      // Calculate how many bars to load
      const barsToLoad = Math.max(0, targetBarsOnRight - barsOnRight)
      
      return barsToLoad
    },
    
    /**
     * Load chart data on the left side
     * @param {number} from - Start index of visible range (logical range from)
     * @param {number} to - End index of visible range (logical range to)
     * @returns {Promise<Array>} Loaded quotes array (empty if no load needed)
     */
    async loadChartDataLeft(from, to) {
      // Calculate how many bars to load
      const barsToLoad = this.calculateBarsToLoadLeft(from, to)
      
      if (barsToLoad === 0) {
        return []
      }
      
      if (!this.currentData || this.currentData.length === 0) {
        return []
      }
      
      // Calculate timeframe in seconds
      const timeframeSeconds = this.getTimeframeSeconds()
      if (timeframeSeconds === 0) {
        return []
      }
      
      // Calculate time range to load (before current earliest data)
      const earliestTime = this.currentData[0].time
      const timeRangeToLoad = barsToLoad * timeframeSeconds
      const loadTo = earliestTime - timeframeSeconds // Last bar to load (one period before earliest)
      const loadFrom = earliestTime - timeRangeToLoad // First bar to load
      
      // Clamp to backtesting start date if needed
      let finalFrom = loadFrom
      if (this.backtestingDateStart && loadFrom < this.backtestingDateStart) {
        finalFrom = this.backtestingDateStart
      }
      
      // Final check: if loadFrom >= loadTo, we can't load
      if (finalFrom >= loadTo) {
        return []
      }
      
      // Load quotes from API
      const quotes = await this.loadQuotes(finalFrom, loadTo)
      
      return quotes || []
    },
    
    /**
     * Load chart data on the right side
     * @param {number} from - Start index of visible range (logical range from)
     * @param {number} to - End index of visible range (logical range to)
     * @returns {Promise<Array>} Loaded quotes array (empty if no load needed)
     */
    async loadChartDataRight(from, to) {
      // Calculate how many bars to load
      const barsToLoad = this.calculateBarsToLoadRight(from, to)
      
      if (barsToLoad === 0) {
        return []
      }
      
      if (!this.currentData || this.currentData.length === 0) {
        return []
      }
      
      // Calculate timeframe in seconds
      const timeframeSeconds = this.getTimeframeSeconds()
      if (timeframeSeconds === 0) {
        return []
      }
      
      // Calculate time range to load (after current latest data)
      const latestTime = this.currentData[this.currentData.length - 1].time
      const loadFrom = latestTime + timeframeSeconds // First bar to load (one period after latest)
      const timeRangeToLoad = barsToLoad * timeframeSeconds
      const loadTo = latestTime + timeRangeToLoad // Last bar to load
      
      // Clamp to backtesting end date if needed
      let finalTo = loadTo
      if (this.backtestingDateEnd && loadTo > this.backtestingDateEnd) {
        finalTo = this.backtestingDateEnd
      }
      
      // Final check: if loadFrom >= finalTo, we can't load
      if (loadFrom >= finalTo) {
        return []
      }
      
      // Load quotes from API
      const quotes = await this.loadQuotes(loadFrom, finalTo)
      
      return quotes || []
    },
    
    /**
     * Universal chart data update procedure
     * Checks if data needs to be loaded on left or right and updates chart
     */
    async updateChartBars() {
      if (!this.chart || !this.currentData || this.currentData.length === 0) {
        return
      }
      
      // Don't run if chart is busy with any operation
      if (this.chartIsBusy()) {
        return
      }
      
      // Block visible range updates during chart update
      this.isUpdatingChart = true
      try {
        const logicalRange = this.chart.timeScale().getVisibleLogicalRange()
        if (!logicalRange) {
          return
        }
        
        // Create range object that will be adjusted by addChartBars
        const range = {
          from: logicalRange.from,
          to: logicalRange.to
        }

        const wasDeleted = await this.deleteOldChartBars(range)
        const wasAdded = await this.addChartBars(range)

        // Update chart only if data was modified
        if (wasDeleted || wasAdded) {
          // Set data on chart
          this.candlestickSeries.setData(this.currentData)
          
          // Set visible range using adjusted values
          this.chart.timeScale().setVisibleLogicalRange({
            from: range.from,
            to: range.to
          })
        }

      } finally {
        this.isUpdatingChart = false
      }
    },
    
    /**
     * Delete old chart bars from both ends
     * Removes data that is too far from visible range to free memory
     * @param {Object} range - Range object with from and to properties (will be modified if data removed from left)
     * @returns {boolean} True if data was modified, false otherwise
     */
    async deleteOldChartBars(range) {
      if (!this.currentData || this.currentData.length === 0) {
        return false
      }
      
      // Calculate visible range length
      const visibleLength = range.to - range.from
      
      // Calculate thresholds:
      // cleanupThreshold - when to trigger cleanup (check if we have too much data)
      // loadBarsBuffer - how much buffer to keep (prevent immediate reload)
      const cleanupThreshold = visibleLength * CLEANUP_THRESHOLD_MULTIPLIER
      const loadBarsBuffer = visibleLength * LOAD_BARS_MULTIPLIER
      
      let barsRemovedLeft = 0
      let barsRemovedRight = 0
      let cleanedData = this.currentData
      
      // Check if we need to remove data from the left
      if (range.from > cleanupThreshold) {
        // Keep data starting from (range.from - loadBarsBuffer)
        const keepFromIndex = Math.max(0, Math.floor(range.from - loadBarsBuffer))
        
        if (keepFromIndex > 0) {
          barsRemovedLeft = keepFromIndex
          cleanedData = cleanedData.slice(keepFromIndex)
        }
      }
      
      // Check if we need to remove data from the right
      const barsOnRight = cleanedData.length - (range.to - barsRemovedLeft)
      if (barsOnRight > cleanupThreshold) {
        // Keep data up to (range.to + loadBarsBuffer)
        const keepToIndex = Math.min(
          cleanedData.length,
          Math.ceil(range.to - barsRemovedLeft + loadBarsBuffer)
        )
        
        if (keepToIndex < cleanedData.length) {
          barsRemovedRight = cleanedData.length - keepToIndex
          cleanedData = cleanedData.slice(0, keepToIndex)
        }
      }
      
      // Update current data if anything was removed
      if (barsRemovedLeft > 0 || barsRemovedRight > 0) {
        this.currentData = cleanedData
        
        // Adjust range for bars removed from the left
        if (barsRemovedLeft > 0) {
          range.from -= barsRemovedLeft
          range.to -= barsRemovedLeft
        }
        
        return true
      }
      
      return false
    },

    /**
     * Add chart bars based on visible range
     * Adjusts the range object to account for bars added on the left
     * @param {Object} range - Range object with from and to properties (will be modified)
     * @returns {boolean} True if data was modified, false otherwise
     */
    async addChartBars(range) {
      // Load data from left and right
      const [leftData, rightData] = await Promise.all([
        this.loadChartDataLeft(range.from, range.to),
        this.loadChartDataRight(range.from, range.to)
      ])
      
      // Determine exact number of bars added on left and right
      const barsAddedLeft = leftData.length
      const barsAddedRight = rightData.length
      
      // If no data was added, nothing to do
      if (barsAddedLeft === 0 && barsAddedRight === 0) {
        return false
      }
      
      // Merge data: left (new) + current + right (new)
      const mergedData = [...leftData, ...this.currentData, ...rightData]
      
      // Update current data
      this.currentData = mergedData
      
      // Adjust range to account for bars added on the left
      if (barsAddedLeft > 0) {
        range.from += barsAddedLeft
        range.to += barsAddedLeft
      }
      
      return true
    },
    
    /**
     * Update chart other elements (trades, markers, deal lines, etc.)
     * Called when visible range changes (with 500ms debounce)
     * @param {Object} logicalRange - Current visible logical range
     */
    updateChartOthers(logicalRange) {
      if (!this.chart || !logicalRange) {
        return
      }
      
      // Update trade markers and deal lines
      this.updateTradeMarkers()
      this.updateDealLines()
    },
    
    /**
     * Update trade markers on chart based on current visible range
     * Always brings state in line with showTradeMarkers flag
     */
    updateTradeMarkers() {
      // Check if chart is busy
      if (this.chartIsBusy()) {
        return
      }
      
      // Check initialization first
      if (!this.chart) {
        return
      }
      
      if (!this.seriesMarkers) {
        return
      }
      
      if (!this.currentData || this.currentData.length === 0) {
        return
      }
      
      // Set busy flag
      this.isUpdatingTradeMarkers = true
      
      try {
        // If flag is false, clear markers
        if (!this.showTradeMarkers) {
          try {
            this.seriesMarkers.setMarkers([])
          } catch (error) {
            // Silently ignore errors when clearing
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
        
        // Get visible time range from chart
        const visibleRange = this.chart.timeScale().getVisibleRange()
        if (!visibleRange) {
          // If visible range is not available, clear markers
          try {
            this.seriesMarkers.setMarkers([])
          } catch (error) {
            // Silently ignore errors when clearing
          }
          return
        }
        
        // Convert Unix timestamps (seconds) to ISO strings for getTradesByDateRange
        const fromISO = new Date(visibleRange.from * 1000).toISOString()
        const toISO = new Date(visibleRange.to * 1000).toISOString()
        
        // Get trades for visible time range
        const tradesInRange = this.backtestingResults.getTradesByDateRange(fromISO, toISO)
        
        // If no trades, clear markers
        if (!tradesInRange || tradesInRange.length === 0) {
          try {
            this.seriesMarkers.setMarkers([])
          } catch (error) {
            // Silently ignore errors when clearing
          }
          return
        }
        
        // Convert trades to markers
        const markers = tradesInRange.map(trade => {
          // Parse time from ISO string to Unix timestamp (seconds)
          const tradeTime = Math.floor(new Date(trade.time).getTime() / 1000)
          
          // Determine marker shape and position based on side
          const isBuy = trade.side === 'buy'
          
          return {
            time: tradeTime,
            position: isBuy ? 'belowBar' : 'aboveBar',
            color: isBuy ? TRADE_BUY_COLOR : TRADE_SELL_COLOR,
            shape: isBuy ? 'arrowUp' : 'arrowDown',
            text: `${isBuy ? 'Buy' : 'Sell'}: ${parseFloat(trade.price).toFixed(2)}`
          }
        })
        
        // Set markers using seriesMarkers API (lightweight-charts 5.x)
        try {
          this.seriesMarkers.setMarkers(markers)
        } catch (error) {
          // Silently ignore errors
        }
      } finally {
        this.isUpdatingTradeMarkers = false
      }
    },
    
    /**
     * Update deal lines on chart
     * Always brings state in line with showDealLines flag
     */
    updateDealLines() {
      // Check if chart is busy
      if (this.chartIsBusy()) {
        return
      }
      
      // Check initialization first
      if (!this.chart) {
        return
      }
      
      if (!this.currentData || this.currentData.length === 0) {
        return
      }
      
      // Set busy flag
      this.isUpdatingDealLines = true
      
      try {
        // Remove existing deal lines first (always, regardless of flag)
        try {
          this.dealLines.forEach(lineSeries => {
            this.chart.removeSeries(lineSeries)
          })
          this.dealLines = []
        } catch (error) {
          // Silently ignore errors
        }
        
        // If flag is false, we're done (lines already removed)
        if (!this.showDealLines) {
          return
        }
        
        // Flag is true, show lines
        if (!this.backtestingResults) {
          return
        }
        
        // Get visible time range from chart
        const visibleRange = this.chart.timeScale().getVisibleRange()
        if (!visibleRange) {
          // If visible range is not available, don't show any deals
          return
        }
        
        // Get all closed deals
        const allDeals = this.backtestingResults.getAllDeals()
        const closedDeals = allDeals.filter(deal => deal.is_closed)
        
        // For each closed deal, create a line if it's visible
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
          
          // Check if deal is visible:
          // 1. At least one end (start or end) must be in visible range, OR
          // 2. Deal crosses the visible range (one end is before, other is after)
          const isStartVisible = startTime >= visibleRange.from && startTime <= visibleRange.to
          const isEndVisible = endTime >= visibleRange.from && endTime <= visibleRange.to
          const crossesRange = startTime < visibleRange.from && endTime > visibleRange.to
          if (!isStartVisible && !isEndVisible && !crossesRange) {
            // Deal is not visible, skip it
            return
          }
          
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
            // Silently ignore errors
          }
        })
      } finally {
        this.isUpdatingDealLines = false
      }
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
      }
      
      // Clear trade markers
      if (this.seriesMarkers) {
        try {
          this.seriesMarkers.setMarkers([])
        } catch (error) {
          // Silently ignore errors
        }
      }
      
      // Remove deal lines
      if (this.chart && this.dealLines.length > 0) {
        try {
          this.dealLines.forEach(lineSeries => {
            this.chart.removeSeries(lineSeries)
          })
          this.dealLines = []
        } catch (error) {
          // Silently ignore errors
        }
      }
      
      this.currentData = []
      this.backtestingDateStart = null
      this.backtestingDateEnd = null
    },
    
    resetChart() {
      this.clearChartData()
    },
    
    cleanup() {
      // Clear debounce timers
      if (this.debounceTimer) {
        clearTimeout(this.debounceTimer)
        this.debounceTimer = null
      }
      
      if (this.othersDebounceTimer) {
        clearTimeout(this.othersDebounceTimer)
        this.othersDebounceTimer = null
      }
      
      // Unsubscribe from logical range changes
      if (this.logicalRangeSubscription && this.chart) {
        this.chart.timeScale().unsubscribeVisibleLogicalRangeChange(this.logicalRangeSubscription)
        this.logicalRangeSubscription = null
      }
      
      // Remove deal lines
      if (this.chart && this.dealLines.length > 0) {
        try {
          this.dealLines.forEach(lineSeries => {
            this.chart.removeSeries(lineSeries)
          })
          this.dealLines = []
        } catch (error) {
          // Silently ignore errors
        }
      }
      
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
      
      // Remove chart
      if (this.chart) {
        this.chart.remove()
        this.chart = null
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
    
    // Navigation method stubs (to be implemented later)
    async goToDate(timestamp) {
      // TODO: implement navigation to specific date
    },
    
    /**
     * Move chart to the beginning
     */
    async moveChartToStart() {
      await this.moveToBegin()
    },
    
    /**
     * Move chart to the end
     */
    async moveChartToEnd() {
      await this.moveToEnd()
    },
    
    /**
     * Scroll chart one page backward
     */
    scrollChartBackward() {
      if (!this.chart || !this.currentData || this.currentData.length === 0) {
        return
      }
      
      // Don't run if chart is busy with any operation
      if (this.chartIsBusy()) {
        return
      }
      
      // Block visible range updates during chart update
      this.isUpdatingChart = true
      try {
        const currentLogicalRange = this.chart.timeScale().getVisibleLogicalRange()
        if (!currentLogicalRange) {
          return
        }
        
        const visibleLength = currentLogicalRange.to - currentLogicalRange.from
        const dataLength = this.currentData.length
        
        // Calculate new range: to = from - 1, from = to - visibleLength
        let newTo = Math.floor(currentLogicalRange.from) - 1
        let newFrom = newTo - visibleLength
        
        // Check if we're going before the start of data
        if (newFrom < 0) {
          // Set range to the beginning: from = 0, to = visibleLength
          newFrom = 0
          newTo = Math.min(dataLength, visibleLength)
        }
        
        // Set new visible range
        this.chart.timeScale().setVisibleLogicalRange({
          from: newFrom,
          to: newTo
        })
      } finally {
        this.isUpdatingChart = false
      }
    },
    
    /**
     * Scroll chart one page forward
     */
    scrollChartForward() {
      if (!this.chart || !this.currentData || this.currentData.length === 0) {
        return
      }
      
      // Don't run if chart is busy with any operation
      if (this.chartIsBusy()) {
        return
      }
      
      // Block visible range updates during chart update
      this.isUpdatingChart = true
      try {
        const currentLogicalRange = this.chart.timeScale().getVisibleLogicalRange()
        if (!currentLogicalRange) {
          return
        }
        
        const visibleLength = currentLogicalRange.to - currentLogicalRange.from
        const dataLength = this.currentData.length
        
        // Calculate new range: from = to + 1, to = from + visibleLength
        let newFrom = Math.floor(currentLogicalRange.to) + 1
        let newTo = newFrom + visibleLength
        
        // Check if we're going beyond the end of data
        if (newTo > dataLength) {
          // Set range to the end: to = dataLength, from = dataLength - visibleLength
          newTo = dataLength
          newFrom = Math.max(0, dataLength - visibleLength)
        }
        
        // Set new visible range
        this.chart.timeScale().setVisibleLogicalRange({
          from: newFrom,
          to: newTo
        })
      } finally {
        this.isUpdatingChart = false
      }
    },
    
    /**
     * Handle keyboard events for chart navigation
     * @param {KeyboardEvent} event - Keyboard event
     */
    handleKeyDown(event) {
      // Ignore if focus is in input or textarea
      if (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA') {
        return
      }
      
      // Only handle Shift+key combinations
      if (!event.shiftKey) {
        return
      }
      
      // Prevent default behavior
      event.preventDefault()
      
      // Handle Shift+key combinations
      switch (event.key) {
        case 'Home':
          this.moveChartToStart()
          break
        case 'End':
          this.moveChartToEnd()
          break
        case 'PageDown':
          this.scrollChartBackward()
          break
        case 'PageUp':
          this.scrollChartForward()
          break
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
