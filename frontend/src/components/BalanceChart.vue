<template>
  <div class="balance-chart">
    <h3>Balance Chart</h3>
    <div class="chart-content">
      <p>Balance chart will be displayed here</p>
    </div>
  </div>
</template>

<script>
export default {
  name: 'BalanceChart'
}
</script>

<style scoped>
.balance-chart {
  width: 100%;
  height: 100%;
  padding: var(--spacing-sm);
  background-color: var(--bg-primary);
  overflow: auto;
  min-height: 150px;
}

.balance-chart h3 {
  margin: 0 0 var(--spacing-sm) 0;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
}

.chart-content {
  width: 100%;
  height: calc(100% - 30px);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  font-size: var(--font-size-sm);
}
</style>

