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
</style>

