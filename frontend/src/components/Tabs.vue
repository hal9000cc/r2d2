<template>
  <div class="tabs">
    <div class="tabs-header">
      <div class="tabs-buttons">
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
      <div v-if="strategyName && strategyName.length > 0" class="strategy-name-wrapper">
        <span class="strategy-name">{{ strategyName }}</span>
      </div>
      
      <!-- Slot for additional controls (e.g., Select button) -->
      <slot name="header-actions"></slot>
      
      <button 
        v-if="strategyName && strategyName.length > 0"
        class="close-button" 
        @click="closeStrategy" 
        title="Close strategy"
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M1 1L11 11M11 1L1 11" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
        </svg>
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
    },
    strategyName: {
      type: String,
      default: ''
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
    },
    closeStrategy() {
      this.$emit('close-strategy')
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
  align-items: center;
  border-bottom: 1px solid var(--border-color);
  background-color: var(--bg-secondary);
  flex-shrink: 0;
  position: relative;
}

.tabs-buttons {
  display: flex;
  flex: 0 0 auto;
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

.strategy-name-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  padding: 0 var(--spacing-md);
}

.strategy-name {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 400px;
}

.close-button {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  margin-right: var(--spacing-md);
  background: none;
  border: none;
  border-radius: var(--border-radius);
  color: var(--text-tertiary);
  cursor: pointer;
  transition: all var(--transition-base);
  flex-shrink: 0;
}

.close-button:hover {
  background-color: var(--bg-tertiary);
  color: var(--text-primary);
}

.close-button:active {
  background-color: var(--bg-hover);
}

.tabs-content {
  flex: 1;
  overflow: hidden;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
</style>

