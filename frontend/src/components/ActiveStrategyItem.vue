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
  padding: var(--spacing-sm);
  margin-bottom: var(--spacing-sm);
  background-color: var(--bg-primary);
  border: 1px solid var(--border-color-light);
  border-left: 3px solid transparent;
  border-radius: var(--radius-sm);
  transition: background-color var(--transition-base), border-color var(--transition-base);
  cursor: pointer;
}

.active-strategy-item:hover {
  background-color: var(--bg-hover);
}

.active-strategy-item.is-running {
  background-color: var(--color-success-light);
  border-color: var(--color-success);
  border-left-color: var(--color-success);
}

.active-strategy-item.is-running:hover {
  background-color: var(--color-success-lighter);
}

.active-strategy-item.is-active {
  background-color: var(--color-info-light);
  border-left-color: var(--color-info);
  border-color: var(--color-info-lighter);
}

.active-strategy-item.is-active:hover {
  background-color: var(--color-info-lighter);
}

.active-strategy-item.is-active.is-running {
  background-color: var(--color-success-light);
  border-left-color: var(--color-info);
  border-color: var(--color-success);
}

.active-strategy-item.is-active.is-running:hover {
  background-color: var(--color-success-lighter);
}

.strategy-info {
  flex: 1;
  min-width: 0;
}

.strategy-name {
  font-weight: var(--font-weight-semibold);
  font-size: var(--font-size-sm);
  color: var(--text-primary);
  margin-bottom: var(--spacing-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.strategy-id {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
}

.strategy-actions {
  display: flex;
  gap: var(--spacing-xs);
  flex-shrink: 0;
}

.action-btn {
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

.action-btn:hover {
  background-color: var(--bg-hover);
  border-color: var(--border-color);
}

.action-btn .icon {
  width: 16px;
  height: 16px;
  color: var(--text-tertiary);
}

.action-btn:hover .icon {
  color: var(--text-primary);
}

.edit-btn:hover {
  background-color: var(--color-info-light);
  border-color: var(--color-info);
}

.edit-btn:hover .icon {
  color: var(--color-info);
}

.start-btn:hover {
  background-color: var(--color-success-light);
  border-color: var(--color-success);
}

.start-btn:hover .icon {
  color: var(--color-success);
}

.stop-btn:hover {
  background-color: var(--color-warning-light);
  border-color: var(--color-warning);
}

.stop-btn:hover .icon {
  color: var(--color-warning);
}

.trading-btn.is-trading {
  background-color: var(--color-danger-light);
  border-color: var(--color-danger);
}

.trading-btn.is-trading .trading-icon {
  color: var(--color-danger);
}

.trading-btn:hover.is-trading {
  background-color: var(--color-danger-lighter);
}

.trading-btn .icon-text {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--text-tertiary);
}

.trading-btn:hover .icon-text {
  color: var(--text-primary);
}

.delete-btn:hover {
  background-color: var(--color-danger-light);
  border-color: var(--color-danger);
}

.delete-btn:hover .icon {
  color: var(--color-danger);
}
</style>

