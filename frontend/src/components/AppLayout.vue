<template>
  <div class="app-layout">
    <div class="app-content">
      <router-view />
    </div>
    <!-- Global alert container -->
    <AlertContainer />
  </div>
</template>

<script>
import AlertContainer from './AlertContainer.vue'

export default {
  name: 'AppLayout',
  components: {
    AlertContainer
  }
}
</script>

<style scoped>
.app-layout {
  display: flex;
  flex-direction: column;
  width: 100vw;
  height: calc(100vh - var(--navbar-height));
  overflow: hidden;
}

.app-content {
  flex: 1;
  overflow: hidden;
  min-height: 0;
}
</style>

