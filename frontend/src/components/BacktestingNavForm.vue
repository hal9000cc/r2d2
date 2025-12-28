<template>
  <div class="backtesting-nav-form">
    <SourceInput
      v-model="formData.source"
      input-id="backtesting-source"
      :required="true"
      :disabled="disabled"
      @valid="isSourceValid = $event"
    />
    <SymbolInput
      v-model="formData.symbol"
      :source="formData.source"
      :is-source-valid="isSourceValid"
      input-id="backtesting-symbol"
      :required="true"
      :disabled="disabled"
    />
    <div class="form-group">
      <label for="timeframe">
        Timeframe
        <span class="required">*</span>
      </label>
      <input
        id="timeframe"
        v-model="formData.timeframe"
        type="text"
        class="form-input"
        :class="{ 'invalid': formData.timeframe && !isTimeframeValid }"
        :list="timeframeDatalistId"
        placeholder="Type to search timeframe..."
        :disabled="disabled"
        :required="true"
        autocomplete="off"
      />
      <datalist :id="timeframeDatalistId">
        <option v-for="tf in timeframes" :key="tf" :value="tf"></option>
      </datalist>
    </div>
    <div class="form-group">
      <label for="dateFrom">Date From</label>
      <input
        id="dateFrom"
        v-model="formData.dateFrom"
        type="date"
        class="form-input"
        :disabled="disabled"
      />
    </div>
    <div class="form-group">
      <label for="dateTo">Date To</label>
      <input
        id="dateTo"
        v-model="formData.dateTo"
        type="date"
        class="form-input"
        :disabled="disabled"
      />
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
</template>

<script>
import { inject, computed } from 'vue'
import SourceInput from './SourceInput.vue'
import SymbolInput from './SymbolInput.vue'
import { PlayIcon, StopIcon } from '@heroicons/vue/24/outline'

export default {
  name: 'BacktestingNavForm',
  components: {
    SourceInput,
    SymbolInput,
    PlayIcon,
    StopIcon
  },
  emits: ['start', 'stop', 'form-data-changed'],
  props: {
    disabled: {
      type: Boolean,
      default: false
    },
    isRunning: {
      type: Boolean,
      default: false
    }
  },
  setup() {
    const timeframesComposable = inject('timeframes')
    
    return {
      timeframesComposable
    }
  },
  data() {
    return {
      formData: {
        source: '',
        symbol: '',
        timeframe: '',
        dateFrom: '',
        dateTo: ''
      },
      isSourceValid: false
    }
  },
  computed: {
    timeframeDatalistId() {
      return 'backtesting-timeframe-list'
    },
    timeframes() {
      return this.timeframesComposable.timeframesList
    },
    isTimeframeValid() {
      return this.formData.timeframe && this.timeframes.includes(this.formData.timeframe)
    }
  },
  watch: {
    formData: {
      handler() {
        // Emit change event when form data changes
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
    }
  }
}
</script>

<style scoped>
.backtesting-nav-form {
  display: flex;
  align-items: center;
  gap: var(--spacing-lg);
  height: 100%;
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

