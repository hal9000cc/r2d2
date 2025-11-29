<template>
  <div class="messages-panel">
    <h3>Messages</h3>
    <div class="messages-content">
      <p>Messages panel placeholder</p>
    </div>
  </div>
</template>

<script>
export default {
  name: 'MessagesPanel'
}
</script>

<style scoped>
.messages-panel {
  flex: 1;
  min-height: 100px;
  padding: 10px;
  background-color: #f8f9fa;
  overflow-y: auto;
}

.messages-panel h3 {
  margin: 0 0 10px 0;
  font-size: 14px;
  font-weight: 600;
  color: #333;
}

.messages-content {
  font-size: 12px;
  color: #666;
}
</style>

