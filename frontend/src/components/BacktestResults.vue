<template>
  <div class="backtest-results">
    <h3>Results</h3>
    <div class="results-content">
      <div v-if="isRunning" class="loading">
        <p>Running backtest...</p>
      </div>
      <div v-else-if="!results" class="empty">
        <p>Backtest results will be displayed here</p>
      </div>
      <div v-else class="results">
        <div class="statistics">
          <h4>Statistics</h4>
          <div class="stat-grid">
            <div class="stat-item">
              <span class="stat-label">Total Deals:</span>
              <span class="stat-value">{{ results.statistics.total_deals }}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">Winning Deals:</span>
              <span class="stat-value positive">{{ results.statistics.winning_deals }}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">Losing Deals:</span>
              <span class="stat-value negative">{{ results.statistics.losing_deals }}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">Win Rate:</span>
              <span class="stat-value">{{ results.statistics.win_rate.toFixed(2) }}%</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">Total Profit:</span>
              <span class="stat-value" :class="results.statistics.total_profit >= 0 ? 'positive' : 'negative'">
                {{ results.statistics.total_profit.toFixed(2) }}
              </span>
            </div>
            <div class="stat-item">
              <span class="stat-label">Total Fees:</span>
              <span class="stat-value">{{ results.statistics.total_fees.toFixed(2) }}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">Final Balance:</span>
              <span class="stat-value" :class="results.statistics.final_balance >= 0 ? 'positive' : 'negative'">
                {{ results.statistics.final_balance.toFixed(2) }}
              </span>
            </div>
          </div>
        </div>
        <div class="global-deal" v-if="results.global_deal">
          <h4>Global Deal</h4>
          <div class="deal-info">
            <div class="deal-item">
              <span class="deal-label">Entry Time:</span>
              <span class="deal-value">{{ formatDate(results.global_deal.entry_time) }}</span>
            </div>
            <div class="deal-item">
              <span class="deal-label">Exit Time:</span>
              <span class="deal-value">{{ formatDate(results.global_deal.exit_time) }}</span>
            </div>
            <div class="deal-item">
              <span class="deal-label">Entry Price:</span>
              <span class="deal-value">{{ results.global_deal.entry_price?.toFixed(2) || 'N/A' }}</span>
            </div>
            <div class="deal-item">
              <span class="deal-label">Exit Price:</span>
              <span class="deal-value">{{ results.global_deal.exit_price?.toFixed(2) || 'N/A' }}</span>
            </div>
            <div class="deal-item">
              <span class="deal-label">Profit:</span>
              <span class="deal-value" :class="results.global_deal.profit >= 0 ? 'positive' : 'negative'">
                {{ results.global_deal.profit?.toFixed(2) || 'N/A' }}
              </span>
            </div>
            <div class="deal-item">
              <span class="deal-label">Fees:</span>
              <span class="deal-value">{{ results.global_deal.fees?.toFixed(2) || 'N/A' }}</span>
            </div>
          </div>
        </div>
        <div class="deals" v-if="results.deals && results.deals.length > 0">
          <h4>Deals ({{ results.deals.length }})</h4>
          <div class="deals-list">
            <div 
              v-for="(deal, index) in results.deals" 
              :key="index" 
              class="deal-card"
              :class="deal.profit >= 0 ? 'positive' : 'negative'"
            >
              <div class="deal-header">
                <span class="deal-number">#{{ index + 1 }}</span>
                <span class="deal-side">{{ deal.side }}</span>
                <span class="deal-profit" :class="deal.profit >= 0 ? 'positive' : 'negative'">
                  {{ deal.profit?.toFixed(2) || 'N/A' }}
                </span>
              </div>
              <div class="deal-details">
                <div class="deal-detail-item">
                  <span>Entry:</span>
                  <span>{{ formatDate(deal.entry_time) }} @ {{ deal.entry_price?.toFixed(2) || 'N/A' }}</span>
                </div>
                <div class="deal-detail-item">
                  <span>Exit:</span>
                  <span>{{ formatDate(deal.exit_time) }} @ {{ deal.exit_price?.toFixed(2) || 'N/A' }}</span>
                </div>
                <div class="deal-detail-item">
                  <span>Fees:</span>
                  <span>{{ deal.fees?.toFixed(2) || 'N/A' }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'BacktestResults',
  props: {
    results: {
      type: Object,
      default: null
    },
    isRunning: {
      type: Boolean,
      default: false
    }
  },
  methods: {
    formatDate(dateStr) {
      if (!dateStr) return 'N/A'
      try {
        const date = new Date(dateStr)
        return date.toLocaleString()
      } catch (e) {
        return dateStr
      }
    }
  }
}
</script>

<style scoped>
.backtest-results {
  width: 100%;
  height: 100%;
  padding: var(--spacing-sm);
  background-color: var(--bg-primary);
  overflow: auto;
  min-height: 150px;
}

.backtest-results h3 {
  margin: 0 0 var(--spacing-sm) 0;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
}

.results-content {
  width: 100%;
  height: calc(100% - 30px);
  overflow-y: auto;
  color: var(--text-primary);
  font-size: var(--font-size-sm);
}

.loading, .empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-muted);
}

.results {
  padding: var(--spacing-xs);
}

.statistics {
  margin-bottom: var(--spacing-md);
}

.statistics h4,
.global-deal h4,
.deals h4 {
  margin: 0 0 var(--spacing-sm) 0;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--spacing-xs);
}

.stat-item {
  display: flex;
  justify-content: space-between;
  padding: var(--spacing-xs);
  background-color: var(--bg-secondary);
  border-radius: var(--radius-sm);
}

.stat-label {
  color: var(--text-secondary);
  font-size: var(--font-size-xs);
}

.stat-value {
  font-weight: var(--font-weight-medium);
  color: var(--text-primary);
}

.stat-value.positive {
  color: var(--color-success, #10b981);
}

.stat-value.negative {
  color: var(--color-danger, #ef4444);
}

.global-deal {
  margin-bottom: var(--spacing-md);
  padding: var(--spacing-sm);
  background-color: var(--bg-secondary);
  border-radius: var(--radius-md);
}

.deal-info {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--spacing-xs);
}

.deal-item {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
}

.deal-label {
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
}

.deal-value {
  font-weight: var(--font-weight-medium);
  color: var(--text-primary);
}

.deal-value.positive {
  color: var(--color-success, #10b981);
}

.deal-value.negative {
  color: var(--color-danger, #ef4444);
}

.deals-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
  max-height: 300px;
  overflow-y: auto;
}

.deal-card {
  padding: var(--spacing-sm);
  background-color: var(--bg-secondary);
  border-radius: var(--radius-md);
  border-left: 3px solid var(--border-color);
}

.deal-card.positive {
  border-left-color: var(--color-success, #10b981);
}

.deal-card.negative {
  border-left-color: var(--color-danger, #ef4444);
}

.deal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--spacing-xs);
}

.deal-number {
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
}

.deal-side {
  text-transform: uppercase;
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
}

.deal-profit {
  font-weight: var(--font-weight-semibold);
  font-size: var(--font-size-sm);
}

.deal-details {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
  font-size: var(--font-size-xs);
}

.deal-detail-item {
  display: flex;
  justify-content: space-between;
  color: var(--text-secondary);
}
</style>

