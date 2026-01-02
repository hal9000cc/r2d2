<template>
  <div 
    ref="chartContainer" 
    class="backtesting-chart"
  ></div>
</template>

<script>
import { createChart, ColorType, LineSeries } from 'lightweight-charts'
import { inject } from 'vue'
import axios from 'axios'
import { backtestingApi } from '../services/backtestingApi.js'
import { DataSeriesManager } from '../lib/dataSeriesManager.js'
import { SeriesType } from '../lib/dataSeriesWrapper.js'
import { isoToUnix, unixToISO } from '../utils/dateUtils.js'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8202'

// Trade marker colors
const TRADE_BUY_COLOR = '#0d5d4a'  // Darker green for buy markers
const TRADE_SELL_COLOR = '#8b1f1a' // Darker red for sell markers

// Date marker color
const DATE_MARKER_COLOR = '#1976D2' // Blue color for date marker

// Chart grid colors
const GRID_LINE_COLOR = '#e0e0e0' // Gray color for grid lines

// Candlestick colors
const CANDLESTICK_UP_COLOR = '#26a69a'   // Green color for bullish candles
const CANDLESTICK_DOWN_COLOR = '#ef5350' // Red color for bearish candles

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
      type: Object,
      default: null
    },
    // Task ID for loading indicators
    taskId: {
      type: Number,
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
    },
    showIndicators: {
      type: Boolean,
      default: true
    }
  },
  emits: ['chart-cleared', 'log-scale-changed', 'quotes-load-error', 'chart-error', 'chart-message'],
  setup() {
    // Inject backtesting results from parent
    const backtestingResults = inject('backtestingResults', null)
    // Inject global timeframes composable
    const timeframesComposable = inject('timeframes')
    return { backtestingResults, timeframesComposable }
  },
  data() {
    return {
      chart: null,
      seriesManager: null, // Manager for working with data series
      dealLines: [], // Array of line series for deals
      dateMarkerTimestamp: null, // Timestamp of the current date marker (for removal)
      
      // ResizeObserver for automatic chart resizing
      resizeObserver: null,
      handleResizeBound: null, // Bound resize handler for cleanup
      
      // Backtesting bounds
      backtestingDateStart: null, // Unix timestamp in seconds
      backtestingDateEnd: null, // Unix timestamp in seconds (current_time from progress)
      
      // Indicator data cache
      _indicatorCacheData: null,
      _indicatorCacheFrom: null,
      _indicatorCacheTo: null,
      _indicatorCacheTaskId: null,
      _indicatorCacheResultId: null,
      
      currentData: [], // Array of {time, open, high, low, close}
      
      // Flags to block concurrent updates
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
        // Handle date_end from backtesting_completed
        if (newProgress && newProgress.date_end) {
          const dateEnd = isoToUnix(newProgress.date_end)
          if (dateEnd) {
            this.backtestingDateEnd = dateEnd
          }
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
    showTradeMarkers() {
      this.updateTradeMarkers()
    },
    showDealLines() {
      this.updateDealLines()
    },
    showIndicators() {
      // TODO: Handle indicators visibility change
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
      return (this.seriesManager?.isUpdating) || this.isUpdatingTradeMarkers || this.isUpdatingDealLines
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
            color: GRID_LINE_COLOR
          },
          horzLines: {
            color: GRID_LINE_COLOR
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

      // Create manager for data series
      this.createSeriesManager()
    },
    
    /**
     * Create series manager with current props
     * Can be called multiple times to recreate manager with updated parameters
     */
    createSeriesManager() {
      if (!this.chart) {
        return
      }
      
      // Create manager for data series
      this.seriesManager = new DataSeriesManager(this.chart, {
        source: this.source,
        symbol: this.symbol,
        timeframe: this.timeframe,
        taskId: this.taskId,
        resultId: this.backtestingResults?.resultId,
        onDataUpdated: (data) => {
          // Synchronize with currentData for compatibility
          this.currentData = data
        },
        onError: (error, context) => {
          console.error('[BacktestingChart] Series manager error:', error, context)
          this.$emit('quotes-load-error', error)
        }
      })
      
      // Add quotes series (main series)
      this.seriesManager.addSeries('quotes', SeriesType.quotes, {
        upColor: CANDLESTICK_UP_COLOR,
        downColor: CANDLESTICK_DOWN_COLOR,
        borderVisible: false,
        wickUpColor: CANDLESTICK_UP_COLOR,
        wickDownColor: CANDLESTICK_DOWN_COLOR
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
      // Convert ISO strings to Unix timestamps
      const dateStart = progress.date_start ? isoToUnix(progress.date_start) : null
      const dateCurrent = progress.current_time ? isoToUnix(progress.current_time) : null
      
      if (!dateStart || !dateCurrent) {
        return
      }
      
      // Initialize backtesting bounds on first progress
      if (this.backtestingDateStart === null) {
        this.backtestingDateStart = dateStart
        this.backtestingDateEnd = dateCurrent
        // Load initial data on first progress
        this.loadInitialData()
      } else {
        // Update backtestingDateEnd on each progress message
        this.backtestingDateEnd = dateCurrent
      }
      
      // Update indicator series on each progress
      this.updateIndicatorSeries()
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
      
      // Wait for chart initialization if not ready yet
      // Use a loop with nextTick to wait for initialization
      while (!this.seriesManager || !this.seriesManager.isInitialized) {
        await this.$nextTick()
        // Safety check: if component is being destroyed, exit
        if (!this.$refs.chartContainer) {
          return
        }
      }
      
      // Set initial dummy bar through manager (will be replaced by moveToBegin)
      this.seriesManager.setDummyBar(this.backtestingDateStart)
      
      // Move to begin (this will load real data)
      this.$nextTick(async () => {
        await this.moveToBegin()
      })
    },
    
    /**
     * Move chart view to the beginning (start of backtesting period)
     * Loads initial data and sets visible range
     */
    async moveToBegin() {
      if (!this.chart || !this.seriesManager || !this.seriesManager.isInitialized) {
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
      
      // Move to begin through manager (isUpdating is managed by manager)
      const adjustedRange = await this.seriesManager.moveToBegin(
        visibleRange,
        this.backtestingDateStart,
        this.backtestingDateEnd
      )
      
      if (adjustedRange) {
        // Set visible logical range
        this.chart.timeScale().setVisibleLogicalRange(adjustedRange)
      }
    },
    
    /**
     * Move chart view to the end (current time of backtesting)
     * Loads data from end and sets visible range
     */
    async moveToEnd() {
      if (!this.chart || !this.seriesManager || !this.seriesManager.isInitialized) {
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
      
      // Move to end through manager (isUpdating is managed by manager)
      const adjustedRange = await this.seriesManager.moveToEnd(
        visibleLength,
        this.backtestingDateStart,
        this.backtestingDateEnd
      )
      
      if (adjustedRange) {
        // Set visible logical range
        this.chart.timeScale().setVisibleLogicalRange(adjustedRange)
      }
    },
    
    /**
     * Universal chart data update procedure
     * Checks if data needs to be loaded on left or right and updates chart
     */
    async updateChartBars() {
      if (!this.chart || !this.seriesManager || !this.seriesManager.dataLength || this.seriesManager.dataLength === 0) {
        return
      }
      
      // Don't run if chart is busy with any operation or manager is updating
      if (this.chartIsBusy() || this.seriesManager?.isUpdating) {
        return
      }
      
      const logicalRange = this.chart.timeScale().getVisibleLogicalRange()
      if (!logicalRange) {
        return
      }
      
      // Use manager's updateBars method (isUpdating is managed by manager)
      const adjustedRange = await this.seriesManager.updateBars(
        logicalRange,
        this.backtestingDateStart,
        this.backtestingDateEnd
      )
      
      // Set visible range if data was modified
      if (adjustedRange) {
        this.chart.timeScale().setVisibleLogicalRange({
          from: adjustedRange.from,
          to: adjustedRange.to
        })
      }
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
      
      if (!this.seriesManager || !this.seriesManager.seriesMarkers) {
        return
      }
      
      if (!this.seriesManager.dataLength || this.seriesManager.dataLength === 0) {
        return
      }
      
      if (!this.backtestingResults) {
        return
      }
      
      const seriesMarkers = this.seriesManager?.seriesMarkers
      if (!seriesMarkers) {
        return
      }

      this.isUpdatingTradeMarkers = true
      
      try {
        // If flag is false, clear markers (but preserve date marker)
        if (!this.showTradeMarkers) {
          try {
            const dateMarker = this.getDateMarker()
            seriesMarkers.setMarkers(dateMarker ? [dateMarker] : [])
          } catch (error) {
            // Silently ignore errors when clearing
          }
          return
        }
                
        // Get visible time range from chart
        const visibleRange = this.chart.timeScale().getVisibleRange()
        if (!visibleRange) {
          // If visible range is not available, clear markers (but preserve date marker)
          try {
            const dateMarker = this.getDateMarker()
            seriesMarkers.setMarkers(dateMarker ? [dateMarker] : [])
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
        
        // If no trades, clear markers (but preserve date marker)
        if (!tradesInRange || tradesInRange.length === 0) {
          try {
            const dateMarker = this.getDateMarker()
            seriesMarkers.setMarkers(dateMarker ? [dateMarker] : [])
          } catch (error) {
            // Silently ignore errors when clearing
          }
          return
        }
        
        // Convert trades to markers
        const tradeMarkers = tradesInRange.map(trade => {
          // Parse time from ISO string to Unix timestamp (seconds)
          const tradeTime = Math.floor(new Date(trade.time).getTime() / 1000)
          
          // Determine marker shape and position based on side
          const isBuy = trade.side === 'buy'
          
          return {
            time: tradeTime,
            position: isBuy ? 'belowBar' : 'aboveBar',
            color: isBuy ? TRADE_BUY_COLOR : TRADE_SELL_COLOR,
            shape: isBuy ? 'arrowUp' : 'arrowDown',
            text: `${trade.trade_id ? trade.trade_id + ' ' : ''}${isBuy ? 'Buy' : 'Sell'}: ${parseFloat(trade.price).toFixed(2)}`
          }
        })
        
        // Preserve date marker if exists
        const dateMarker = this.getDateMarker()
        
        // Combine trade markers with date marker
        const allMarkers = dateMarker ? [...tradeMarkers, dateMarker] : tradeMarkers
        
        // Set markers using seriesMarkers API (lightweight-charts 5.x)
        try {
          seriesMarkers.setMarkers(allMarkers)
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
      
      if (!this.seriesManager || !this.seriesManager.dataLength || this.seriesManager.dataLength === 0) {
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
    
    clearChartData() {
      // Destroy existing manager (removes all series from chart)
      if (this.seriesManager) {
        this.seriesManager.destroy()
        this.seriesManager = null
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
      
      // Recreate manager with current props (source, symbol, timeframe)
      this.createSeriesManager()
      
      // Update currentData for compatibility
      this.currentData = []
      this.backtestingDateStart = null
      this.backtestingDateEnd = null
      this.dateMarkerTimestamp = null
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
     * TODO: Implement log scale functionality
     */
    toggleLogScale() {
      // Placeholder - functionality not yet implemented
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
     * Get current time at the center of visible range
     * @returns {number|null} Unix timestamp in seconds, or null if chart/data not available
     */
    getChartCurrentTime() {
      if (!this.chart || !this.seriesManager || !this.seriesManager.dataLength || this.seriesManager.dataLength === 0) {
        return null
      }
      
      // Get visible logical range
      const logicalRange = this.chart.timeScale().getVisibleLogicalRange()
      if (!logicalRange) {
        return null
      }
      
      const from = logicalRange.from
      const to = logicalRange.to
      
      // Calculate center index
      let centerIndex = Math.round((from + to) / 2)
      
      // Clamp to data bounds
      if (centerIndex < 0) {
        centerIndex = 0
      } else if (centerIndex >= this.seriesManager.dataLength) {
        centerIndex = this.seriesManager.dataLength - 1
      }
      
      // Return timestamp of the bar at center
      return this.currentData[centerIndex].time
    },
    
    /**
     * Navigate chart to a specific trade
     * @param {string|number} tradeId - Trade ID
     * @param {boolean} showMarker - Whether to show a marker at the trade time (default: true)
     */
    async goToTrade(tradeId, showMarker = true) {
      if (!this.backtestingResults) {
        this.$emit('chart-error', 'Backtesting results are not available')
        return
      }
      
      // Get trade by ID
      const trade = this.backtestingResults.getTradeById(tradeId)
      if (!trade) {
        this.$emit('chart-error', `Trade with ID ${tradeId} not found`)
        return
      }
      
      // Convert trade time (ISO string) to Unix timestamp (seconds)
      const timestamp = isoToUnix(trade.time)
      
      // Navigate to trade time
      await this.goToTime(timestamp, showMarker)
    },
    
    /**
     * Navigate chart to the start of a specific deal (first trade of the deal)
     * @param {string|number} dealId - Deal ID
     * @param {boolean} showMarker - Whether to show a marker at the deal start time (default: true)
     */
    async goToDeal(dealId, showMarker = true) {
      if (!this.backtestingResults) {
        this.$emit('chart-error', 'Backtesting results are not available')
        return
      }
      
      // Get trades for this deal
      const dealTrades = this.backtestingResults.getTradesForDeal(dealId)
      if (!dealTrades || dealTrades.length === 0) {
        this.$emit('chart-error', `No trades found for deal with ID ${dealId}`)
        return
      }
      
      // Get first trade (trades are already sorted by time)
      const firstTrade = dealTrades[0]
      
      // Navigate to first trade using goToTrade
      await this.goToTrade(firstTrade.trade_id, showMarker)
    },
    
    /**
     * Go to specific time on the chart
     * Loads data around the selected time and centers it in the visible range
     * @param {number} timestamp - Unix timestamp in seconds
     * @param {boolean} showDateMarker - Whether to show a marker at the selected date
     */
    async goToTime(timestamp, showDateMarker = false) {
      if (!this.chart || !this.seriesManager || !this.seriesManager.isInitialized) {
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
      
      // Check if timestamp is within backtesting bounds
      if (timestamp < this.backtestingDateStart || timestamp > this.backtestingDateEnd) {
        return
      }
      
      // Get current visible range length
      const logicalRange = this.chart.timeScale().getVisibleLogicalRange()
      if (!logicalRange) {
        return
      }
      
      const visibleLength = logicalRange.to - logicalRange.from
      
      // Go to time through manager (isUpdating is managed by manager)
      const result = await this.seriesManager.goToTime(
        timestamp,
        visibleLength,
        this.backtestingDateStart,
        this.backtestingDateEnd
      )
      
      if (!result) {
        return
      }
      
      // Set visible logical range
      this.chart.timeScale().setVisibleLogicalRange({
        from: result.from,
        to: result.to
      })
      
      // Handle date marker if requested
      if (showDateMarker) {
        // Set date marker timestamp (will be drawn by updateChartOthers)
        this.dateMarkerTimestamp = result.markerTime
      } else {
        // Clear date marker if not requested
        this.dateMarkerTimestamp = null
      }
      
      // Update trade markers and deal lines after a short delay
      // This ensures the chart has finished adjusting the range
      // updateChartOthers will also restore the date marker if dateMarkerTimestamp is set
      setTimeout(() => {
        const currentRange = this.chart.timeScale().getVisibleLogicalRange()
        if (currentRange) {
          this.updateChartOthers(currentRange)
        }
      }, 100)
    },
    
    /**
     * Draw date marker at specified timestamp
     * @param {number} timestamp - Unix timestamp in seconds
     */
    drawDateMarker(timestamp) {
      const seriesMarkers = this.seriesManager?.seriesMarkers
      if (!seriesMarkers || !this.seriesManager || !this.seriesManager.dataLength || this.seriesManager.dataLength === 0) {
        return
      }
      
      // Find the bar for the timestamp (or closest bar)
      let markerTime = timestamp
      let found = false
      
      for (let i = 0; i < this.seriesManager.dataLength; i++) {
        if (this.currentData[i].time >= timestamp) {
          markerTime = this.currentData[i].time
          found = true
          break
        }
      }
      
      // If timestamp is after all bars, use last bar
      if (!found && this.seriesManager.dataLength > 0) {
        markerTime = this.seriesManager.lastBarTime
      }
      
      // Get current markers (to preserve trade markers)
      const currentMarkers = seriesMarkers.markers() || []
      
      // Create date marker
      const dateMarker = {
        time: markerTime,
        position: 'aboveBar',
        color: DATE_MARKER_COLOR,
        shape: 'arrowDown',
        size: 3,
        text: ''
      }
      
      // Add date marker to existing markers
      const allMarkers = [...currentMarkers, dateMarker]
      
      // Set all markers
      try {
        seriesMarkers.setMarkers(allMarkers)
        // Store timestamp for future removal
        this.dateMarkerTimestamp = markerTime
      } catch (error) {
        // Silently ignore errors
      }
    },
    
    /**
     * Remove date marker if exists
     */
    /**
     * Get current date marker if exists
     * @returns {Object|null} Date marker object or null
     */
    getDateMarker() {
      if (!this.dateMarkerTimestamp) {
        return null
      }
      
      return {
        time: this.dateMarkerTimestamp,
        position: 'aboveBar',
        color: DATE_MARKER_COLOR,
        shape: 'arrowDown',
        size: 3,
        text: ''
      }
    },
    
    /**
     * Go to the beginning of the chart (public method for external control)
     */
    async goToStart() {
      await this.moveToBegin()
    },
    
    /**
     * Go to the end of the chart (public method for external control)
     */
    async goToEnd() {
      await this.moveToEnd()
    },
    
    /**
     * Scroll chart one page backward (public method for external control)
     */
    scrollPageBackward() {
      if (!this.chart || !this.seriesManager || !this.seriesManager.dataLength || this.seriesManager.dataLength === 0) {
        return
      }
      
      // Don't run if chart is busy with any operation
      if (this.chartIsBusy()) {
        return
      }
      
      const currentLogicalRange = this.chart.timeScale().getVisibleLogicalRange()
      if (!currentLogicalRange) {
        return
      }
      
      const visibleLength = currentLogicalRange.to - currentLogicalRange.from
      const dataLength = this.seriesManager.dataLength
      
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
    },
    
    /**
     * Scroll chart one page forward (public method for external control)
     */
    scrollPageForward() {
      if (!this.chart || !this.seriesManager || !this.seriesManager.dataLength || this.seriesManager.dataLength === 0) {
        return
      }
      
      // Don't run if chart is busy with any operation
      if (this.chartIsBusy()) {
        return
      }
      
      const currentLogicalRange = this.chart.timeScale().getVisibleLogicalRange()
      if (!currentLogicalRange) {
        return
      }
      
      const visibleLength = currentLogicalRange.to - currentLogicalRange.from
      const dataLength = this.seriesManager.dataLength
      
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
    },
    
    /**
     * Update indicator series based on loaded results
     * Loads list of indicators from API and creates/updates series
     */
    async updateIndicatorSeries() {
      if (!this.showIndicators) {
        return
      }
      
      if (!this.taskId || !this.backtestingResults?.resultId) {
        return
      }
      
      if (!this.seriesManager) {
        return
      }
      
      try {
        // Load indicator keys from API
        const response = await backtestingApi.getBacktestingIndicatorKeys(
          this.taskId,
          this.backtestingResults.resultId
        )
        
        if (!response.success || !response.data) {
          console.error('Failed to load indicator keys:', response.error_message)
          return
        }
        
        // Get current series keys from manager
        const currentSeriesKeys = this.seriesManager.getIndicatorSeriesKeys()
        
        // Get indicator keys from API response
        const apiKeys = new Set(response.data.map(indicator => indicator.key))
        
        // Initialize set of indicator keys to add (start with all API keys)
        const indicatorKeysToAdd = new Set(apiKeys)
        
        // Remove series for indicators that are no longer in API
        // Extract indicator key from each series key and check if it's still in API
        for (const seriesKey of currentSeriesKeys) {
          const pipeIndex = seriesKey.indexOf('|')
          const indicatorKey = pipeIndex >= 0 ? seriesKey.substring(0, pipeIndex) : seriesKey
          
          // Remove this indicator key from set of keys to add (it's already present)
          indicatorKeysToAdd.delete(indicatorKey)
          
          if (!apiKeys.has(indicatorKey)) {
            // This indicator is no longer in API, remove the series
            try {
              this.seriesManager.removeSeries(seriesKey)
            } catch (error) {
              console.error(`Failed to remove indicator series "${seriesKey}":`, error)
              this.$emit('chart-message', {
                level: 'error',
                message: `Failed to remove indicator series "${seriesKey}": ${error.message || error}`
              })
            }
          }
        }
        
        // Add new series for new indicators
        if (indicatorKeysToAdd.size > 0) {
          this.addIndicatorSeries(response.data, indicatorKeysToAdd)
        }
      } catch (error) {
        console.error('Error loading indicator keys:', error)
        this.$emit('chart-message', {
          level: 'error',
          message: `Error loading indicator keys: ${error.message || error}`
        })
      }
    },
    
    /**
     * Get series key for indicator and series index
     * @param {Object} indicator - Indicator object
     * @param {number} seriesIndex - Index in series_info array
     * @returns {string} Series key in format "indicator.key|seriesIndex"
     */
    getSeriesKey(indicator, seriesIndex) {
      return `${indicator.key}|${seriesIndex}`
    },
    
    /**
     * Add all series for new indicators
     * @param {Array<Object>} indicators - Array of all indicator objects from API
     * @param {Set<string>} indicatorKeysToAdd - Set of indicator keys to add
     */
    addIndicatorSeries(indicators, indicatorKeysToAdd) {
      for (const indicator of indicators) {
        if (!indicatorKeysToAdd.has(indicator.key)) {
          continue
        }
        
        // Add series for each element in series_info with is_price === true
        for (let seriesIndex = 0; seriesIndex < indicator.series_info.length; seriesIndex++) {
          const seriesInfo = indicator.series_info[seriesIndex]
          // Only add series with is_price === true
          if (seriesInfo.is_price === true) {
            const seriesKey = this.getSeriesKey(indicator, seriesIndex)
            try {
              // Pass loadIndicatorData function, indicator object, seriesIndex, and color from backend
              const added = this.seriesManager.addSeries(
                seriesKey,
                SeriesType.indicatorPrice,
                {
                  loadIndicatorData: this.loadIndicatorData.bind(this),
                  indicator: indicator,
                  seriesIndex: seriesIndex,
                  color: seriesInfo.color || '#808080' // Use color from backend or gray fallback
                }
              )
              
              if (!added) {
                this.$emit('chart-message', {
                  level: 'error',
                  message: `Failed to add indicator series "${seriesKey}"`
                })
              }
            } catch (error) {
              console.error(`Failed to add indicator series "${seriesKey}":`, error)
              this.$emit('chart-message', {
                level: 'error',
                message: `Failed to add indicator series "${seriesKey}": ${error.message || error}`
              })
            }
          }
        }
      }
    },
    
    /**
     * Load indicators data from cache or API
     * @param {number} fromTimestamp - Start timestamp in Unix seconds
     * @param {number} toTimestamp - End timestamp in Unix seconds
     * @returns {Promise<Array|null>} Indicators data array or null on error
     */
    async _loadIndicatorsData(fromTimestamp, toTimestamp) {
      if (!this.taskId || !this.backtestingResults?.resultId) {
        return null
      }
      
      const currentTaskId = this.taskId
      // Ensure resultId is a string (handle Vue ref objects)
      const currentResultId = String((this.backtestingResults.resultId?.value ?? this.backtestingResults.resultId) || '')
      
      // Clear cache if taskId or resultId changed
      if (this._indicatorCacheTaskId !== currentTaskId || this._indicatorCacheResultId !== currentResultId) {
        this._indicatorCacheData = null
        this._indicatorCacheFrom = null
        this._indicatorCacheTo = null
        this._indicatorCacheTaskId = currentTaskId
        this._indicatorCacheResultId = currentResultId
      }
      
      // Check if we can use cached data
      if (this._indicatorCacheData && this._indicatorCacheFrom === fromTimestamp && this._indicatorCacheTo === toTimestamp) {
        return this._indicatorCacheData
      }
      
      // Need to fetch new data
      try {
        const dateStartISO = unixToISO(fromTimestamp)
        const dateEndISO = unixToISO(toTimestamp)
        
        const response = await backtestingApi.getBacktestingIndicators(
          currentTaskId,
          currentResultId, // Already converted to string above
          dateStartISO,
          dateEndISO
        )
        
        if (!response.success || !response.data) {
          const errorMsg = response.error_message || 'Failed to load indicator data'
          console.error('Failed to load indicator data:', errorMsg)
          this.$emit('chart-message', {
            level: 'error',
            message: errorMsg
          })
          return null
        }
        
        // Cache the data
        this._indicatorCacheData = response.data
        this._indicatorCacheFrom = fromTimestamp
        this._indicatorCacheTo = toTimestamp
        
        return this._indicatorCacheData
      } catch (error) {
        console.error('Error loading indicator data:', error)
        this.$emit('chart-message', {
          level: 'error',
          message: `Error loading indicator data: ${error.message || error}`
        })
        return null
      }
    },
    
    /**
     * Load indicator data for specific indicator and series
     * @param {Object} indicator - Indicator object
     * @param {number} seriesIndex - Index in series_info array
     * @param {number} fromTimestamp - Start timestamp in Unix seconds
     * @param {number} toTimestamp - End timestamp in Unix seconds
     * @returns {Promise<Array>} Loaded indicator data in format [{time, value}, ...]
     */
    async loadIndicatorData(indicator, seriesIndex, fromTimestamp, toTimestamp) {
      // Load indicators data from cache or API
      const indicatorsData = await this._loadIndicatorsData(fromTimestamp, toTimestamp)
      if (!indicatorsData) {
        return []
      }
      
      // Find indicator by key
      const indicatorData = indicatorsData.find(ind => ind.key === indicator.key)
      if (!indicatorData) {
        return []
      }
      
      // Extract series values
      let seriesValues = null
      if (indicatorData.is_tuple) {
        // Multiple series - values is an object with series names as keys
        const seriesName = indicatorData.series_info[seriesIndex]?.name
        if (!seriesName) {
          return []
        }
        seriesValues = indicatorData.values[seriesName]
        if (!Array.isArray(seriesValues)) {
          return []
        }
      } else {
        // Single series - values is an array
        seriesValues = indicatorData.values
        if (!Array.isArray(seriesValues)) {
          return []
        }
      }
      
      // Get time array
      const timeArray = indicatorData.time
      if (!Array.isArray(timeArray)) {
        return []
      }
      
      // Check array lengths match
      if (timeArray.length !== seriesValues.length) {
        console.error(`Time and values array lengths don't match for indicator "${indicator.key}", series ${seriesIndex}: time=${timeArray.length}, values=${seriesValues.length}`)
        this.$emit('chart-message', {
          level: 'error',
          message: `Data inconsistency for indicator "${indicator.key}": time and values arrays have different lengths`
        })
        return []
      }
      
      // Convert to [{time, value}, ...] format
      // Filter out null values as lightweight-charts requires numbers
      const result = []
      for (let i = 0; i < timeArray.length; i++) {
        const timeISO = timeArray[i]
        const value = seriesValues[i]
        const timeUnix = isoToUnix(timeISO)
        result.push({ time: timeUnix, value })
      }
      
      return result
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
