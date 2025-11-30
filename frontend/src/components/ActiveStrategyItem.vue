<template>
  <div 
    class="active-strategy-item"
    :class="{ 
      'is-running': strategy.isRunning,
      'is-active': isActive
    }"
  >
    <div class="strategy-info" @click="handleItemClick">
      <div class="strategy-name">{{ strategy.name }}</div>
      <div class="strategy-id">{{ strategy.strategy_id }}</div>
    </div>
    <div class="strategy-actions" @click.stop>
      <button 
        class="action-btn edit-btn"
        @click="$emit('edit', strategy.active_strategy_id)"
        title="Edit"
      >
        <PencilIcon class="icon" />
      </button>
      <button 
        v-if="strategy.isRunning"
        class="action-btn stop-btn"
        @click="$emit('stop', strategy.active_strategy_id)"
        title="Stop"
      >
        <PauseIcon class="icon" />
      </button>
      <button 
        v-else
        class="action-btn start-btn"
        @click="$emit('start', strategy.active_strategy_id)"
        title="Start"
      >
        <PlayIcon class="icon" />
      </button>
      <button 
        class="action-btn trading-btn"
        :class="{ 'is-trading': strategy.isTrading }"
        @click="$emit('toggle-trading', strategy.active_strategy_id)"
        :title="strategy.isTrading ? 'Disable trading' : 'Enable trading'"
      >
        <ExclamationTriangleIcon v-if="strategy.isTrading" class="icon trading-icon" />
        <span v-else class="icon-text">D</span>
      </button>
      <button 
        class="action-btn delete-btn"
        @click="$emit('delete', strategy.active_strategy_id)"
        title="Delete"
      >
        <TrashIcon class="icon" />
      </button>
    </div>
  </div>
</template>

<script>
import { PencilIcon, PlayIcon, PauseIcon, ExclamationTriangleIcon, TrashIcon } from '@heroicons/vue/24/outline'

export default {
  name: 'ActiveStrategyItem',
  props: {
    strategy: {
      type: Object,
      required: true
    },
    isActive: {
      type: Boolean,
      default: false
    }
  },
  components: {
    PencilIcon,
    PlayIcon,
    PauseIcon,
    ExclamationTriangleIcon,
    TrashIcon
  },
  emits: ['edit', 'start', 'stop', 'toggle-trading', 'delete', 'select'],
  methods: {
    handleItemClick() {
      this.$emit('select', this.strategy.active_strategy_id)
    }
  }
}
</script>

<style scoped>
.active-strategy-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px;
  margin-bottom: 8px;
  background-color: #ffffff;
  border: 1px solid #e0e0e0;
  border-left: 3px solid transparent;
  border-radius: 4px;
  transition: background-color 0.2s, border-color 0.2s;
  cursor: pointer;
}

.active-strategy-item:hover {
  background-color: #f5f5f5;
}

.active-strategy-item.is-running {
  background-color: #e8f5e9;
  border-color: #4caf50;
  border-left-color: #4caf50;
}

.active-strategy-item.is-running:hover {
  background-color: #d4edda;
}

.active-strategy-item.is-active {
  background-color: #e3f2fd;
  border-left-color: #2196f3;
  border-color: #90caf9;
}

.active-strategy-item.is-active:hover {
  background-color: #bbdefb;
}

.active-strategy-item.is-active.is-running {
  background-color: #c8e6c9;
  border-left-color: #2196f3;
  border-color: #81c784;
}

.active-strategy-item.is-active.is-running:hover {
  background-color: #a5d6a7;
}

.strategy-info {
  flex: 1;
  min-width: 0;
}

.strategy-name {
  font-weight: 600;
  font-size: 14px;
  color: #333;
  margin-bottom: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.strategy-id {
  font-size: 12px;
  color: #666;
}

.strategy-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.action-btn {
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

.action-btn:hover {
  background-color: #f5f5f5;
  border-color: #bbb;
}

.action-btn .icon {
  width: 16px;
  height: 16px;
  color: #666;
}

.action-btn:hover .icon {
  color: #333;
}

.edit-btn:hover {
  background-color: #e3f2fd;
  border-color: #2196f3;
}

.edit-btn:hover .icon {
  color: #2196f3;
}

.start-btn:hover {
  background-color: #e8f5e9;
  border-color: #4caf50;
}

.start-btn:hover .icon {
  color: #4caf50;
}

.stop-btn:hover {
  background-color: #fff3e0;
  border-color: #ff9800;
}

.stop-btn:hover .icon {
  color: #ff9800;
}

.trading-btn.is-trading {
  background-color: #ffebee;
  border-color: #f44336;
}

.trading-btn.is-trading .trading-icon {
  color: #f44336;
}

.trading-btn:hover.is-trading {
  background-color: #ffcdd2;
}

.trading-btn .icon-text {
  font-size: 14px;
  font-weight: 600;
  color: #666;
}

.trading-btn:hover .icon-text {
  color: #333;
}

.delete-btn:hover {
  background-color: #ffebee;
  border-color: #f44336;
}

.delete-btn:hover .icon {
  color: #f44336;
}
</style>

