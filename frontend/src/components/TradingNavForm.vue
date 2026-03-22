<template>
  <div class="trading-nav-form">
    <div class="form-row">
      <button
        v-if="!disabled && !isRunning && readonly"
        class="edit-btn"
        type="button"
        title="Edit trading task market parameters"
        @click="$emit('edit-clicked')"
      >
        <PencilSquareIcon class="btn-icon" />
        Edit
      </button>
      <SourceInput
        v-model="formData.source"
        input-id="trading-source"
        :required="true"
        :disabled="disabled || readonly"
        @valid="isSourceValid = $event"
        title="Exchange or data source"
      />
      <SymbolInput
        v-model="formData.symbol"
        :source="formData.source"
        :is-source-valid="isSourceValid"
        input-id="trading-symbol"
        :required="true"
        :disabled="disabled || readonly"
      />
      <div class="form-group">
        <label for="trading-timeframe">
          Timeframe
          <span class="required">*</span>
        </label>
        <input
          id="trading-timeframe"
          v-model="timeframeString"
          type="text"
          class="form-input"
          :class="{ 'invalid': formData.timeframe && timeframes.length > 0 && !isTimeframeValid }"
          :list="timeframeDatalistId"
          placeholder="Timeframe..."
          :disabled="disabled || readonly"
          :required="true"
          autocomplete="off"
          title="Trading timeframe (e.g., 1h, 1d, 5m)"
        />
        <datalist :id="timeframeDatalistId">
          <option v-for="tf in timeframes" :key="tf.name" :value="tf.name"></option>
        </datalist>
      </div>
      <button 
        :class="['action-btn', isRunning ? 'stop-btn' : 'start-btn']" 
        :disabled="disabled && !isRunning" 
        @click="handleAction"
      >
        <PlayIcon v-if="!isRunning" class="btn-icon" />
        <StopIcon v-else class="btn-icon" />
        {{ isRunning ? 'Stop' : 'Start' }}
      </button>
    </div>
  </div>
</template>

<script>
import { inject, computed } from 'vue'
import SourceInput from './SourceInput.vue'
import SymbolInput from './SymbolInput.vue'
import { PencilSquareIcon, PlayIcon, StopIcon } from '@heroicons/vue/24/outline'

export default {
  name: 'TradingNavForm',
  components: {
    SourceInput,
    SymbolInput,
    PencilSquareIcon,
    PlayIcon,
    StopIcon
  },
  emits: ['start', 'stop', 'form-data-changed', 'edit-clicked'],
  props: {
    disabled: {
      type: Boolean,
      default: false
    },
    isRunning: {
      type: Boolean,
      default: false
    },
    readonly: {
      type: Boolean,
      default: false
    }
  },
  setup() {
    const timeframesComposable = inject('timeframes')
    
    const timeframesList = computed(() => {
      if (!timeframesComposable) {
        return []
      }
      const list = timeframesComposable.timeframesList?.value || []
      return Array.isArray(list) ? list : []
    })
    
    return {
      timeframesComposable,
      timeframesList
    }
  },
  data() {
    return {
      formData: {
        source: '',
        symbol: '',
        timeframe: null
      },
      isSourceValid: false
    }
  },
  computed: {
    timeframeDatalistId() {
      return 'trading-timeframe-list'
    },
    timeframes() {
      return this.timeframesList
    },
    timeframeString: {
      get() {
        return this.formData.timeframe ? this.formData.timeframe.name : ''
      },
      set(value) {
        const timeframe = this.timeframesComposable?.getTimeframe(value)
        this.formData.timeframe = timeframe || null
      }
    },
    isTimeframeValid() {
      if (!this.formData.timeframe || !this.timeframes.length) {
        return false
      }
      return this.timeframes.some(tf => tf.equals(this.formData.timeframe))
    }
  },
  watch: {
    formData: {
      handler() {
        this.$emit('form-data-changed')
      },
      deep: true
    }
  },
  methods: {
    handleAction() {
      if (this.isRunning) {
        this.$emit('stop')
      } else {
        this.$emit('start', { ...this.formData })
      }
    },
    getFormData() {
      return {
        source: this.formData.source,
        symbol: this.formData.symbol,
        timeframe: this.formData.timeframe,
      }
    },
    setFormData(data) {
      if (data.source !== undefined) this.formData.source = data.source
      if (data.symbol !== undefined) this.formData.symbol = data.symbol
      if (data.timeframe !== undefined) {
        if (typeof data.timeframe === 'string') {
          const timeframe = this.timeframesComposable?.getTimeframe(data.timeframe)
          this.formData.timeframe = timeframe || null
        } else {
          this.formData.timeframe = data.timeframe
        }
      }
    }
  }
}
</script>

<style scoped>
.trading-nav-form {
  display: flex;
  flex-direction: column;
  height: auto;
  min-height: var(--navbar-height);
}

.form-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--spacing-lg);
  width: 100%;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
}

.form-group label {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--text-tertiary);
}

.form-input {
  padding: var(--spacing-sm) var(--spacing-md);
  border: 1px solid var(--border-color-dark);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  min-width: 120px;
  transition: border-color var(--transition-base);
  background-color: var(--bg-primary);
  color: var(--text-primary);
}

.form-input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.form-input.invalid {
  border-color: var(--color-danger);
  box-shadow: 0 0 0 0.2rem var(--color-danger-shadow);
}

.required {
  color: var(--color-danger);
  margin-left: 2px;
}

.action-btn {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  padding: var(--spacing-sm) var(--spacing-xl);
  border: none;
  border-radius: var(--radius-md);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  transition: background-color var(--transition-base);
  margin-top: 1.25rem;
}

.edit-btn {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  padding: var(--spacing-sm) var(--spacing-md);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background-color: var(--bg-primary);
  color: var(--text-primary);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  transition: all var(--transition-base);
  margin-top: 1.25rem;
}

.edit-btn:hover {
  background-color: var(--bg-hover);
  border-color: var(--color-primary);
}

.edit-btn .btn-icon {
  width: 1.25rem;
  height: 1.25rem;
}

.action-btn .btn-icon {
  width: 1.25rem;
  height: 1.25rem;
}

.start-btn {
  background-color: var(--color-primary);
  color: var(--text-inverse);
}

.start-btn:hover:not(:disabled) {
  background-color: var(--color-primary-hover);
}

.start-btn:active:not(:disabled) {
  background-color: var(--color-primary-active);
}

.stop-btn {
  background-color: var(--color-danger);
  color: var(--text-inverse);
}

.stop-btn:hover:not(:disabled) {
  background-color: var(--color-danger-hover);
}

.stop-btn:active:not(:disabled) {
  background-color: var(--color-danger-hover);
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>

