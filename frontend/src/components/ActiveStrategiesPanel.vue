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
        @edit="handleEdit"
        @start="handleStart"
        @stop="handleStop"
        @toggle-trading="handleToggleTrading"
        @delete="handleDelete"
      />
    </div>
    
    <ActiveStrategyEditModal
      :is-open="isEditModalOpen"
      :strategy="selectedStrategy"
      :is-new="isNewStrategy"
      :timeframes="timeframes"
      :sources="sources"
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
  data() {
    return {
      activeStrategies: [],
      isEditModalOpen: false,
      selectedStrategy: null,
      isNewStrategy: false,
      timeframes: [], // Cached list of timeframes
      sources: [] // Cached list of sources
    }
  },
  mounted() {
    this.loadStrategies()
  },
  methods: {
    async loadStrategies() {
      try {
        this.activeStrategies = await activeStrategiesApi.getActiveStrategies()
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
        // Remove from list
        this.activeStrategies = this.activeStrategies.filter(
          s => s.active_strategy_id !== id
        )
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
    }
  }
}
</script>

<style scoped>
.active-strategies-panel {
  width: 100%;
  height: 100%;
  padding: 10px;
  border-left: 1px solid #ddd;
  background-color: #f8f9fa;
  overflow-y: auto;
  min-width: 200px;
  display: flex;
  flex-direction: column;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
  flex-shrink: 0;
}

.active-strategies-panel h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: #333;
}

.add-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid #ddd;
  border-radius: 4px;
  background-color: #ffffff;
  cursor: pointer;
  transition: all 0.2s;
}

.add-btn:hover {
  background-color: #e8f5e9;
  border-color: #4caf50;
}

.add-btn .icon {
  width: 18px;
  height: 18px;
  color: #666;
}

.add-btn:hover .icon {
  color: #4caf50;
}

.active-strategies-content {
  flex: 1;
  overflow-y: auto;
}

.empty-state {
  padding: 20px;
  text-align: center;
  color: #999;
  font-size: 14px;
}
</style>

