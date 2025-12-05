<template>
  <div class="app-layout">
    <NavBar>
      <template #navbar-content>
        <!-- Content will be teleported here from views -->
      </template>
    </NavBar>
    <div class="app-content">
      <router-view />
    </div>
  </div>
</template>

<script>
import NavBar from './NavBar.vue'

export default {
  name: 'AppLayout',
  components: {
    NavBar
  }
}
</script>

<style scoped>
.app-layout {
  display: flex;
  flex-direction: column;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
}

.app-content {
  flex: 1;
  overflow: hidden;
  min-height: 0;
}
</style>

