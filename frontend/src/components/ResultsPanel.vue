<template>
  <div class="results-panel">
    <h3>Results</h3>
    <div class="results-content">
      <p>Results panel placeholder</p>
    </div>
  </div>
</template>

<script>
export default {
  name: 'ResultsPanel'
}
</script>

<style scoped>
.results-panel {
  flex: 0 0 10vh;
  min-height: 80px;
  max-height: 120px;
  padding: var(--spacing-sm);
  border-bottom: 1px solid var(--border-color-dark);
  background-color: var(--bg-secondary);
  overflow-y: auto;
}

.results-panel h3 {
  margin: 0 0 var(--spacing-sm) 0;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
}

.results-content {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
}
</style>

