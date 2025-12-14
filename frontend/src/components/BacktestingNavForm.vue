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
    <button class="start-btn" :disabled="disabled" @click="handleStart">Start</button>
  </div>
</template>

<script>
import SourceInput from './SourceInput.vue'
import SymbolInput from './SymbolInput.vue'
import { strategiesApi } from '../services/strategiesApi'

export default {
  name: 'BacktestingNavForm',
  components: {
    SourceInput,
    SymbolInput
  },
  emits: ['start', 'form-data-changed'],
  props: {
    disabled: {
      type: Boolean,
      default: false
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
      isSourceValid: false,
      timeframes: []
    }
  },
  computed: {
    timeframeDatalistId() {
      return 'backtesting-timeframe-list'
    },
    isTimeframeValid() {
      return this.formData.timeframe && this.timeframes.includes(this.formData.timeframe)
    }
  },
  mounted() {
    this.loadTimeframes()
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
    async loadTimeframes() {
      try {
        this.timeframes = await strategiesApi.getTimeframes()
      } catch (error) {
        console.error('Failed to load timeframes:', error)
        // Fallback to common timeframes if API fails
        this.timeframes = ['1s', '1m', '3m', '5m', '10m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '1w']
      }
    },
    handleStart() {
      this.$emit('start', { ...this.formData })
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
  border-color: var(--color-danger, #ef4444);
  box-shadow: 0 0 0 0.2rem rgba(244, 67, 54, 0.25);
}

.required {
  color: var(--color-danger, #ef4444);
  margin-left: 2px;
}


.start-btn {
  padding: var(--spacing-sm) var(--spacing-xl);
  background-color: var(--color-primary);
  color: var(--text-inverse);
  border: none;
  border-radius: var(--radius-md);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  transition: background-color var(--transition-base);
  margin-top: 1.25rem;
}

.start-btn:hover:not(:disabled) {
  background-color: var(--color-primary-hover);
}

.start-btn:active:not(:disabled) {
  background-color: var(--color-primary-active);
}

.start-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>

