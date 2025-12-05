<template>
  <div class="form-group">
    <label :for="inputId">
      Strategy
      <span v-if="required" class="required">*</span>
    </label>
    <input
      :id="inputId"
      type="text"
      :value="modelValue"
      :class="['form-input', { 'invalid': modelValue && !isValid }]"
      :list="datalistId"
      :placeholder="placeholder"
      :required="required"
      autocomplete="off"
      @input="handleInput"
    />
    <datalist :id="datalistId">
      <option v-for="strategy in strategies" :key="strategy" :value="strategy"></option>
    </datalist>
  </div>
</template>

<script>
import { activeStrategiesApi } from '../services/activeStrategiesApi'

export default {
  name: 'StrategyInput',
  props: {
    modelValue: {
      type: String,
      default: ''
    },
    required: {
      type: Boolean,
      default: false
    },
    placeholder: {
      type: String,
      default: 'Type to search strategy...'
    },
    inputId: {
      type: String,
      default: 'strategy-input'
    }
  },
  emits: ['update:modelValue', 'change', 'valid'],
  data() {
    return {
      strategies: []
    }
  },
  computed: {
    datalistId() {
      return `${this.inputId}-list`
    },
    isValid() {
      return this.modelValue && this.strategies.includes(this.modelValue)
    }
  },
  watch: {
    isValid(newVal) {
      this.$emit('valid', newVal)
    }
  },
  mounted() {
    this.loadStrategies()
  },
  methods: {
    async loadStrategies() {
      try {
        this.strategies = await activeStrategiesApi.getStrategies()
      } catch (error) {
        console.error('Failed to load strategies:', error)
        this.strategies = []
      }
    },
    handleInput(event) {
      const inputValue = event.target.value
      this.$emit('update:modelValue', inputValue)
      this.$emit('change', inputValue)
      
      if (!inputValue) {
        return
      }
      
      // Filter strategies that start with input value (case insensitive)
      const searchText = inputValue.toLowerCase()
      const matchingStrategies = this.strategies.filter(strategy => 
        strategy.toLowerCase().startsWith(searchText)
      )
      
      // Auto-select if only one matching strategy remains
      if (matchingStrategies.length === 1) {
        this.$nextTick(() => {
          this.$emit('update:modelValue', matchingStrategies[0])
          this.$emit('change', matchingStrategies[0])
        })
      }
    }
  }
}
</script>

<style scoped>
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

.required {
  color: var(--color-danger);
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

.form-input.invalid {
  border-color: var(--color-danger);
  box-shadow: 0 0 0 0.2rem rgba(244, 67, 54, 0.25);
}
</style>

