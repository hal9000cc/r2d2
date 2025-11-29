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
  padding: 10px;
  border-bottom: 1px solid #ddd;
  background-color: #f8f9fa;
  overflow-y: auto;
}

.results-panel h3 {
  margin: 0 0 10px 0;
  font-size: 14px;
  font-weight: 600;
  color: #333;
}

.results-content {
  font-size: 12px;
  color: #666;
}
</style>

