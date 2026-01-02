<template>
  <div class="active-strategies-panel">
    <div class="panel-header">
      <h3>Active Strategies</h3>
    </div>
    <div class="active-strategies-content">
      <!-- Content will be added later -->
    </div>
  </div>
</template>

<script>
export default {
  name: 'ActiveStrategiesPanel'
}
</script>

<style scoped>
.active-strategies-panel {
  width: 100%;
  height: 100%;
  padding: var(--spacing-sm);
  border-left: 1px solid var(--border-color-dark);
  background-color: var(--bg-secondary);
  overflow-y: auto;
  min-width: 200px;
  display: flex;
  flex-direction: column;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--spacing-sm);
  flex-shrink: 0;
}

.active-strategies-panel h3 {
  margin: 0;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
}

.active-strategies-content {
  flex: 1;
  overflow-y: auto;
}
</style>

