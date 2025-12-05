<template>
  <div class="active-strategies-panel">
    <div class="panel-header">
      <h3>Active Strategies</h3>
      <button class="add-btn" @click="handleAdd" title="Add Strategy">
        <PlusIcon class="icon" />
      </button>
    </div>
    <div class="active-strategies-content">
      <div v-if="activeStrategies.length === 0" class="empty-state">
        <p>No active strategies</p>
      </div>
      <ActiveStrategyItem
        v-for="strategy in activeStrategies"
        :key="strategy.active_strategy_id"
        :strategy="strategy"
        :is-active="activeStrategyId === strategy.active_strategy_id"
        @edit="handleEdit"
        @start="handleStart"
        @stop="handleStop"
        @toggle-trading="handleToggleTrading"
        @delete="handleDelete"
        @select="handleSelect"
      />
    </div>
    
    <ActiveStrategyEditModal
      :is-open="isEditModalOpen"
      :strategy="selectedStrategy"
      :is-new="isNewStrategy"
      :timeframes="timeframes"
      :sources="sources"
      :strategies="strategies"
      @close="closeEditModal"
      @save="handleSaveStrategy"
    />
  </div>
</template>

<script>
import { PlusIcon } from '@heroicons/vue/24/outline'
import { activeStrategiesApi } from '../services/activeStrategiesApi'
import ActiveStrategyItem from './ActiveStrategyItem.vue'
import ActiveStrategyEditModal from './ActiveStrategyEditModal.vue'

export default {
  name: 'ActiveStrategiesPanel',
  components: {
    PlusIcon,
    ActiveStrategyItem,
    ActiveStrategyEditModal
  },
  emits: ['active-strategy-changed'],
  data() {
    return {
      activeStrategies: [],
      isEditModalOpen: false,
      selectedStrategy: null,
      isNewStrategy: false,
      activeStrategyId: null, // ID of currently active/selected strategy
      timeframes: [], // Cached list of timeframes
      sources: [], // Cached list of sources
      strategies: [] // Cached list of strategies
    }
  },
  mounted() {
    this.loadStrategies()
  },
  methods: {
    async loadStrategies() {
      try {
        this.activeStrategies = await activeStrategiesApi.getActiveStrategies()
        // Select first strategy if available and none is selected
        if (this.activeStrategies.length > 0 && this.activeStrategyId === null) {
          this.activeStrategyId = this.activeStrategies[0].active_strategy_id
          // Emit event to parent
          this.$emit('active-strategy-changed', this.activeStrategyId)
        }
      } catch (error) {
        alert(`Failed to load strategies: ${error.message}`)
      }
    },
    async handleAdd() {
      try {
        // Load timeframes and sources if not already loaded
        await this.loadTimeframesAndSources()
        
        this.selectedStrategy = await activeStrategiesApi.getActiveStrategy(0)
        this.isNewStrategy = true
        this.isEditModalOpen = true
      } catch (error) {
        alert(`Failed to create new strategy: ${error.message}`)
      }
    },
    async handleEdit(id) {
      try {
        // Load timeframes and sources if not already loaded
        await this.loadTimeframesAndSources()
        
        this.selectedStrategy = await activeStrategiesApi.getActiveStrategy(id)
        this.isNewStrategy = false
        this.isEditModalOpen = true
      } catch (error) {
        alert(`Failed to load strategy: ${error.message}`)
      }
    },
    async loadTimeframesAndSources() {
      // Load timeframes if not cached
      if (this.timeframes.length === 0) {
        try {
          this.timeframes = await activeStrategiesApi.getTimeframes()
        } catch (error) {
          console.error('Failed to load timeframes:', error)
          this.timeframes = []
        }
      }
      
      // Load sources if not cached
      if (this.sources.length === 0) {
        try {
          this.sources = await activeStrategiesApi.getSources()
        } catch (error) {
          console.error('Failed to load sources:', error)
          this.sources = []
        }
      }
      
      // Load strategies if not cached
      if (this.strategies.length === 0) {
        try {
          this.strategies = await activeStrategiesApi.getStrategies()
        } catch (error) {
          console.error('Failed to load strategies:', error)
          this.strategies = []
        }
      }
    },
    closeEditModal() {
      this.isEditModalOpen = false
      this.selectedStrategy = null
      this.isNewStrategy = false
    },
    async handleSaveStrategy(data) {
      try {
        const updatedStrategy = await activeStrategiesApi.updateStrategy(
          data.active_strategy_id,
          data
        )
        // Update or add the strategy in the list
        const index = this.activeStrategies.findIndex(
          s => s.active_strategy_id === updatedStrategy.active_strategy_id
        )
        if (index !== -1) {
          // Update existing
          this.activeStrategies[index] = updatedStrategy
        } else {
          // Add new
          this.activeStrategies.push(updatedStrategy)
          // Select newly added strategy if no strategy is selected
          if (this.activeStrategyId === null) {
            this.activeStrategyId = updatedStrategy.active_strategy_id
          }
        }
        this.closeEditModal()
      } catch (error) {
        alert(`Failed to save strategy: ${error.message}`)
      }
    },
    async handleDelete(id) {
      if (!confirm('Are you sure you want to delete this strategy?')) {
        return
      }
      
      try {
        await activeStrategiesApi.deleteStrategy(id)
        // Find index of deleted strategy
        const deletedIndex = this.activeStrategies.findIndex(
          s => s.active_strategy_id === id
        )
        // Remove from list
        this.activeStrategies = this.activeStrategies.filter(
          s => s.active_strategy_id !== id
        )
        
        // If deleted strategy was active, select another one
        if (this.activeStrategyId === id) {
          if (this.activeStrategies.length > 0) {
            // Select next strategy, or first if deleted was last
            const nextIndex = deletedIndex < this.activeStrategies.length ? deletedIndex : 0
            this.activeStrategyId = this.activeStrategies[nextIndex].active_strategy_id
          } else {
            // No strategies left
            this.activeStrategyId = null
          }
        }
      } catch (error) {
        alert(`Failed to delete strategy: ${error.message}`)
      }
    },
    async handleStart(id) {
      try {
        const updatedStrategy = await activeStrategiesApi.startStrategy(id)
        // Update the strategy in the list
        const index = this.activeStrategies.findIndex(
          s => s.active_strategy_id === id
        )
        if (index !== -1) {
          this.activeStrategies[index] = updatedStrategy
        }
      } catch (error) {
        alert(`Failed to start strategy: ${error.message}`)
      }
    },
    async handleStop(id) {
      try {
        const updatedStrategy = await activeStrategiesApi.stopStrategy(id)
        // Update the strategy in the list
        const index = this.activeStrategies.findIndex(
          s => s.active_strategy_id === id
        )
        if (index !== -1) {
          this.activeStrategies[index] = updatedStrategy
        }
      } catch (error) {
        alert(`Failed to stop strategy: ${error.message}`)
      }
    },
    async handleToggleTrading(id) {
      try {
        const updatedStrategy = await activeStrategiesApi.toggleTrading(id)
        // Update the strategy in the list
        const index = this.activeStrategies.findIndex(
          s => s.active_strategy_id === id
        )
        if (index !== -1) {
          this.activeStrategies[index] = updatedStrategy
        }
      } catch (error) {
        alert(`Failed to toggle trading: ${error.message}`)
      }
    },
    handleSelect(id) {
      // Set active strategy (always select, no toggle)
      this.activeStrategyId = id
      // Emit event to parent
      this.$emit('active-strategy-changed', id)
    }
  }
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

.add-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: var(--button-height-sm);
  height: var(--button-height-sm);
  padding: 0;
  border: 1px solid var(--border-color-dark);
  border-radius: var(--radius-sm);
  background-color: var(--bg-primary);
  cursor: pointer;
  transition: all var(--transition-base);
}

.add-btn:hover {
  background-color: var(--color-success-light);
  border-color: var(--color-success);
}

.add-btn .icon {
  width: 18px;
  height: 18px;
  color: var(--text-tertiary);
}

.add-btn:hover .icon {
  color: var(--color-success);
}

.active-strategies-content {
  flex: 1;
  overflow-y: auto;
}

.empty-state {
  padding: var(--spacing-xl);
  text-align: center;
  color: var(--text-muted);
  font-size: var(--font-size-sm);
}
</style>

