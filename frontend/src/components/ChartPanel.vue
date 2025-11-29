<template>
  <div class="chart-panel">
    <h3>Chart</h3>
    <div class="chart-content">
      <p>Chart panel placeholder</p>
    </div>
  </div>
</template>

<script>
export default {
  name: 'ChartPanel'
}
</script>

<style scoped>
.chart-panel {
  width: 100%;
  height: 100%;
  padding: 10px;
  border-bottom: 1px solid #ddd;
  background-color: #ffffff;
  overflow: auto;
  min-height: 150px;
}

.chart-panel h3 {
  margin: 0 0 10px 0;
  font-size: 14px;
  font-weight: 600;
  color: #333;
}

.chart-content {
  width: 100%;
  height: calc(100% - 30px);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #999;
  font-size: 14px;
}
</style>

