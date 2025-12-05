<template>
  <div class="backtesting-nav-form">
    <StrategyInput
      v-model="formData.strategy"
      input-id="backtesting-strategy"
      :required="true"
    />
    <SourceInput
      v-model="formData.source"
      input-id="backtesting-source"
      :required="true"
      @valid="isSourceValid = $event"
    />
    <SymbolInput
      v-model="formData.symbol"
      :source="formData.source"
      :is-source-valid="isSourceValid"
      input-id="backtesting-symbol"
      :required="true"
    />
    <div class="form-group">
      <label for="dateFrom">Date From</label>
      <input
        id="dateFrom"
        v-model="formData.dateFrom"
        type="date"
        class="form-input"
      />
    </div>
    <div class="form-group">
      <label for="dateTo">Date To</label>
      <input
        id="dateTo"
        v-model="formData.dateTo"
        type="date"
        class="form-input"
      />
    </div>
    <button class="start-btn" @click="handleStart">Start</button>
  </div>
</template>

<script>
import SourceInput from './SourceInput.vue'
import SymbolInput from './SymbolInput.vue'
import StrategyInput from './StrategyInput.vue'

export default {
  name: 'BacktestingNavForm',
  components: {
    SourceInput,
    SymbolInput,
    StrategyInput
  },
  data() {
    return {
      formData: {
        strategy: '',
        source: '',
        symbol: '',
        dateFrom: '',
        dateTo: ''
      },
      isSourceValid: false
    }
  },
  methods: {
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
}

.form-input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
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

.start-btn:hover {
  background-color: var(--color-primary-hover);
}

.start-btn:active {
  background-color: var(--color-primary-active);
}
</style>

