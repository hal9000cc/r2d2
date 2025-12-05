<template>
  <div class="backtest-results">
    <h3>Results</h3>
    <div class="results-content">
      <p>Backtest results will be displayed here</p>
    </div>
  </div>
</template>

<script>
export default {
  name: 'BacktestResults'
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
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  font-size: var(--font-size-sm);
}
</style>

