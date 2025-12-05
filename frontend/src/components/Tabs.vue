<template>
  <div class="tabs">
    <div class="tabs-header">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        class="tab-button"
        :class="{ active: activeTab === tab.id }"
        @click="selectTab(tab.id)"
      >
        {{ tab.label }}
      </button>
    </div>
    <div class="tabs-content">
      <slot :name="activeTab"></slot>
    </div>
  </div>
</template>

<script>
export default {
  name: 'Tabs',
  props: {
    tabs: {
      type: Array,
      required: true
    },
    defaultTab: {
      type: String,
      default: null
    }
  },
  data() {
    return {
      activeTab: this.defaultTab || (this.tabs.length > 0 ? this.tabs[0].id : null)
    }
  },
  methods: {
    selectTab(tabId) {
      this.activeTab = tabId
      this.$emit('tab-change', tabId)
    }
  }
}
</script>

<style scoped>
.tabs {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  overflow: hidden;
}

.tabs-header {
  display: flex;
  border-bottom: 1px solid var(--border-color);
  background-color: var(--bg-secondary);
  flex-shrink: 0;
}

.tab-button {
  padding: var(--spacing-md) var(--spacing-xl);
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  font-weight: var(--font-weight-medium);
  color: var(--text-tertiary);
  transition: all var(--transition-base);
}

.tab-button:hover {
  color: var(--text-secondary);
  background-color: var(--bg-tertiary);
}

.tab-button.active {
  color: var(--color-primary);
  border-bottom-color: var(--color-primary);
  background-color: var(--bg-primary);
}

.tabs-content {
  flex: 1;
  overflow: hidden;
  min-height: 0;
}
</style>

