<template>
  <div class="backtesting-stats">
    <div class="stats-header">
      <h3>Results</h3>
    </div>
    <div class="stats-content">
      <div v-if="!stats" class="empty-state">
        <!-- Empty state - nothing shown -->
      </div>
      <div v-else class="stats-data">
        <!-- Total deals with win ratio -->
        <div class="stats-row">
          <span class="stats-label">Total deals:</span>
          <span class="stats-value">
            {{ formatNumber(stats.total_deals) }}
            <span class="stats-sub">
              (win ratio {{ formatPercent(getWinRatio(stats)) }})
            </span>
          </span>
        </div>
        
        <!-- Profit: Net ( Gross | Fee ) -->
        <div class="stats-row">
          <span class="stats-label">Profit:</span>
          <span class="stats-value">
            Net: {{ formatCurrency(stats.profit) }}
            <span class="stats-sub">
              ( Gross: {{ formatCurrency(stats.profit_gross) }} | Fee: {{ formatCurrency(stats.total_fees) }} )
            </span>
          </span>
        </div>
        
        <!-- Deals: Total ( Long | Short ) -->
        <div class="stats-row">
          <span class="stats-label">Deals:</span>
          <span class="stats-value">
            Total: {{ formatNumber(stats.total_deals) }}
            <span class="stats-sub">
              ( Long: {{ formatNumber(stats.long_deals) }} | Short: {{ formatNumber(stats.short_deals) }} )
            </span>
          </span>
        </div>
        
        <!-- Profit per deal -->
        <div class="stats-row">
          <span class="stats-label">Profit per deal:</span>
          <span class="stats-value">{{ formatCurrency(stats.profit_per_deal) }}</span>
        </div>
        
        <!-- Maximum drawdown -->
        <div class="stats-row">
          <span class="stats-label">Max drawdown:</span>
          <span class="stats-value">{{ formatCurrency(stats.drawdown_max) }}</span>
        </div>
        
        <!-- Separator -->
        <div class="stats-separator"></div>
        
        <!-- Testing parameters section -->
        <div class="stats-section-title">Testing parameters</div>
        
        <!-- Source -->
        <div v-if="stats?.source" class="stats-row">
          <span class="stats-label">Source:</span>
          <span class="stats-value">{{ stats.source }}</span>
        </div>
        
        <!-- Symbol -->
        <div v-if="stats?.symbol" class="stats-row">
          <span class="stats-label">Symbol:</span>
          <span class="stats-value">{{ stats.symbol }}</span>
        </div>
        
        <!-- Timeframe -->
        <div v-if="stats?.timeframe" class="stats-row">
          <span class="stats-label">Timeframe:</span>
          <span class="stats-value">{{ stats.timeframe }}</span>
        </div>
        
        <!-- Date From -->
        <div v-if="stats?.date_start" class="stats-row">
          <span class="stats-label">Date From:</span>
          <span class="stats-value">{{ formatDate(stats.date_start) }}</span>
        </div>
        
        <!-- Date To -->
        <div v-if="stats?.date_end" class="stats-row">
          <span class="stats-label">Date To:</span>
          <span class="stats-value">{{ formatDate(stats.date_end) }}</span>
        </div>
        
        <!-- Fee Maker -->
        <div class="stats-row">
          <span class="stats-label">Fee Maker:</span>
          <span class="stats-value">{{ formatFee(stats.fee_maker) }}</span>
        </div>
        
        <!-- Fee Taker -->
        <div class="stats-row">
          <span class="stats-label">Fee Taker:</span>
          <span class="stats-value">{{ formatFee(stats.fee_taker) }}</span>
        </div>
        
        <!-- Slippage -->
        <div class="stats-row">
          <span class="stats-label">Slippage:</span>
          <span class="stats-value">{{ formatSlippage(stats.slippage, stats.price_step) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'BacktestingStats',
  props: {
    stats: {
      type: Object,
      default: null
    }
  },
  methods: {
    /**
     * Format number with space as thousands separator
     * @param {number|string|null} value - Value to format
     * @returns {string} Formatted number
     */
    formatNumber(value) {
      if (value === null || value === undefined || value === '') {
        return '—'
      }
      const num = typeof value === 'string' ? parseFloat(value) : value
      if (isNaN(num)) {
        return '—'
      }
      // Format with space as thousands separator
      return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
    },
    
    /**
     * Format currency (USD) with space as thousands separator and 2 decimal places
     * @param {number|string|null} value - Value to format
     * @returns {string} Formatted currency
     */
    formatCurrency(value) {
      if (value === null || value === undefined || value === '') {
        return '—'
      }
      const num = typeof value === 'string' ? parseFloat(value) : value
      if (isNaN(num)) {
        return '—'
      }
      // Format with 2 decimal places and space as thousands separator
      const formatted = num.toFixed(2)
      const parts = formatted.split('.')
      parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
      return parts.join('.')
    },
    
    /**
     * Calculate win ratio percentage
     * @param {Object} stats - Statistics object
     * @returns {number} Win ratio as percentage (0-100)
     */
    getWinRatio(stats) {
      if (!stats || !stats.total_deals || stats.total_deals === 0) {
        return 0
      }
      const profitDeals = stats.profit_deals || 0
      return (profitDeals / stats.total_deals) * 100
    },
    
    /**
     * Format percentage with 2 decimal places
     * @param {number} value - Percentage value (0-100)
     * @returns {string} Formatted percentage with % sign
     */
    formatPercent(value) {
      if (value === null || value === undefined || isNaN(value)) {
        return '0.00%'
      }
      return value.toFixed(2) + '%'
    },
    
    /**
     * Format fee as percentage (3 decimal places)
     * @param {number|string|null} value - Fee rate as fraction (e.g., 0.001 for 0.1%)
     * @returns {string} Formatted fee as percentage
     */
    formatFee(value) {
      if (value === null || value === undefined || value === '') {
        return '—'
      }
      const num = typeof value === 'string' ? parseFloat(value) : value
      if (isNaN(num)) {
        return '—'
      }
      // Convert fraction to percentage (0.001 -> 0.1%)
      return (num * 100).toFixed(3) + '%'
    },
    
    /**
     * Format slippage in currency (decimal places based on price_step, minimum 2)
     * @param {number|string|null} value - Slippage value in currency
     * @param {number|string|null} priceStep - Price step (minimum step size)
     * @returns {string} Formatted slippage
     */
    formatSlippage(value, priceStep) {
      if (value === null || value === undefined || value === '') {
        return '—'
      }
      const num = typeof value === 'string' ? parseFloat(value) : value
      if (isNaN(num)) {
        return '—'
      }
      
      // Calculate decimal places from price_step
      let decimalPlaces = 2 // minimum
      if (priceStep !== null && priceStep !== undefined && priceStep !== '') {
        const step = typeof priceStep === 'string' ? parseFloat(priceStep) : priceStep
        if (!isNaN(step) && step > 0) {
          // Count decimal places in price_step
          const stepStr = step.toString()
          if (stepStr.includes('.')) {
            const decimalPart = stepStr.split('.')[1]
            // Remove trailing zeros
            const significantDigits = decimalPart.replace(/0+$/, '')
            decimalPlaces = Math.max(significantDigits.length, 2)
          }
        }
      }
      
      return num.toFixed(decimalPlaces)
    },
    
    /**
     * Format date string (YYYY-MM-DD) to readable format
     * @param {string} dateStr - Date string in YYYY-MM-DD format
     * @returns {string} Formatted date
     */
    formatDate(dateStr) {
      if (!dateStr) {
        return '—'
      }
      try {
        const date = new Date(dateStr)
        if (isNaN(date.getTime())) {
          return dateStr // Return as-is if invalid
        }
        return date.toLocaleDateString('en-US', { 
          year: 'numeric', 
          month: '2-digit', 
          day: '2-digit' 
        })
      } catch (e) {
        return dateStr
      }
    }
  }
}
</script>

<style scoped>
.backtesting-stats {
  width: 100%;
  height: 100%;
  padding: var(--spacing-sm);
  background-color: var(--bg-primary);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  min-height: 150px;
}

.stats-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--spacing-sm);
  flex-shrink: 0;
}

.stats-header h3 {
  margin: 0;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
}

.stats-content {
  flex: 1;
  overflow: auto;
  width: 100%;
}

.empty-state {
  /* Empty state - nothing shown */
  display: none;
}

.stats-data {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
}

.stats-row {
  display: flex;
  align-items: baseline;
  gap: var(--spacing-xs);
  font-size: var(--font-size-xs);
  color: var(--text-primary);
}

.stats-label {
  font-weight: var(--font-weight-medium);
  min-width: 120px;
  flex-shrink: 0;
}

.stats-value {
  flex: 1;
  color: var(--text-primary);
  font-weight: var(--font-weight-bold);
  font-size: var(--font-size-sm);
}

.stats-sub {
  color: var(--text-secondary);
  font-size: 11px;
}

.stats-separator {
  height: 1px;
  background-color: var(--border-color);
  margin: var(--spacing-sm) 0;
  width: 100%;
}

.stats-section-title {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
  color: var(--text-secondary);
  margin-bottom: var(--spacing-xs);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
</style>

