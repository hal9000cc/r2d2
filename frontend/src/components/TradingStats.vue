<template>
  <div class="trading-stats">
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
        
        <!-- Profit per deal with win/loss averages -->
        <div class="stats-row">
          <span class="stats-label">Profit per deal:</span>
          <span class="stats-value">
            {{ formatCurrency(stats.profit_per_deal) }}
            <span class="stats-sub" v-if="(stats.avg_profit_per_winning_deal !== null && stats.avg_profit_per_winning_deal !== undefined) || (stats.avg_loss_per_losing_deal !== null && stats.avg_loss_per_losing_deal !== undefined)">
              (win {{ formatCurrency(stats.avg_profit_per_winning_deal) }} | loss {{ formatCurrency(stats.avg_loss_per_losing_deal) }})
            </span>
          </span>
        </div>
        
        <!-- Maximum drawdown -->
        <div class="stats-row">
          <span class="stats-label">Max drawdown:</span>
          <span class="stats-value">{{ formatCurrency(stats.drawdown_max) }}</span>
        </div>
        
        <!-- Slot for context-specific section (Testing/Trade parameters) -->
        <slot 
          :format-currency="formatCurrency"
          :format-number="formatNumber"
          :format-percent="formatPercent"
          :format-fee="formatFee"
          :format-slippage="formatSlippage"
          :format-date="formatDate"
        ></slot>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'TradingStats',
  props: {
    stats: {
      type: Object,
      default: null
    }
  },
  methods: {
    formatNumber(value) {
      if (value === null || value === undefined || value === '') {
        return '—'
      }
      const num = typeof value === 'string' ? parseFloat(value) : value
      if (isNaN(num)) {
        return '—'
      }
      return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
    },
    
    formatCurrency(value) {
      if (value === null || value === undefined || value === '') {
        return '—'
      }
      const num = typeof value === 'string' ? parseFloat(value) : value
      if (isNaN(num)) {
        return '—'
      }
      const formatted = num.toFixed(2)
      const parts = formatted.split('.')
      parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
      return parts.join('.')
    },
    
    getWinRatio(stats) {
      if (!stats || !stats.total_deals || stats.total_deals === 0) {
        return 0
      }
      const profitDeals = stats.profit_deals || 0
      return (profitDeals / stats.total_deals) * 100
    },
    
    formatPercent(value) {
      if (value === null || value === undefined || isNaN(value)) {
        return '0.00%'
      }
      return value.toFixed(2) + '%'
    },
    
    formatFee(value) {
      if (value === null || value === undefined || value === '') {
        return '—'
      }
      const num = typeof value === 'string' ? parseFloat(value) : value
      if (isNaN(num)) {
        return '—'
      }
      return (num * 100).toFixed(3) + '%'
    },
    
    formatSlippage(value, priceStep) {
      if (value === null || value === undefined || value === '') {
        return '—'
      }
      const num = typeof value === 'string' ? parseFloat(value) : value
      if (isNaN(num)) {
        return '—'
      }
      
      let decimalPlaces = 2
      if (priceStep !== null && priceStep !== undefined && priceStep !== '') {
        const step = typeof priceStep === 'string' ? parseFloat(priceStep) : priceStep
        if (!isNaN(step) && step > 0) {
          const stepStr = step.toString()
          if (stepStr.includes('.')) {
            const decimalPart = stepStr.split('.')[1]
            const significantDigits = decimalPart.replace(/0+$/, '')
            decimalPlaces = Math.max(significantDigits.length, 2)
          }
        }
      }
      
      return num.toFixed(decimalPlaces)
    },
    
    formatDate(dateStr) {
      if (!dateStr) {
        return '—'
      }
      try {
        const date = new Date(dateStr)
        if (isNaN(date.getTime())) {
          return dateStr
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
.trading-stats {
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
  display: none;
}

.stats-data {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
}
</style>

<!-- Shared styles for stat rows (also used in slot content) -->
<style>
.trading-stats .stats-row {
  display: flex;
  align-items: baseline;
  gap: var(--spacing-xs);
  font-size: var(--font-size-xs);
  color: var(--text-primary);
}

.trading-stats .stats-label {
  font-weight: var(--font-weight-medium);
  min-width: 120px;
  flex-shrink: 0;
}

.trading-stats .stats-value {
  flex: 1;
  color: var(--text-primary);
  font-weight: var(--font-weight-bold);
  font-size: var(--font-size-sm);
}

.trading-stats .stats-sub {
  color: var(--text-secondary);
  font-size: 11px;
}

.trading-stats .stats-separator {
  height: 1px;
  background-color: var(--border-color);
  margin: var(--spacing-sm) 0;
  width: 100%;
}

.trading-stats .stats-section-title {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
  color: var(--text-secondary);
  margin-bottom: var(--spacing-xs);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
</style>

