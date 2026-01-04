<template>
  <div class="form-group">
    <label :for="inputId">
      Symbol
      <span v-if="required" class="required">*</span>
    </label>
    <input
      :id="inputId"
      type="text"
      :value="modelValue"
      :class="['form-input', { 'invalid': modelValue && !isValid }]"
      :list="datalistId"
      :placeholder="placeholder"
      :disabled="disabled || !isSourceValid"
      :required="required"
      autocomplete="off"
      title="Trading symbol (e.g., BTC/USDT, ETH/USD)"
      @input="handleInput"
      @blur="handleBlur"
      @keydown.enter="handleEnter"
      @change="handleChange"
    />
    <datalist :id="datalistId">
      <option v-for="symbol in symbols" :key="symbol" :value="symbol"></option>
    </datalist>
  </div>
</template>

<script>
import { strategiesApi } from '../services/strategiesApi'

export default {
  name: 'SymbolInput',
  props: {
    modelValue: {
      type: String,
      default: ''
    },
    source: {
      type: String,
      default: ''
    },
    isSourceValid: {
      type: Boolean,
      default: false
    },
    required: {
      type: Boolean,
      default: false
    },
    placeholder: {
      type: String,
      default: 'Type to search symbol...'
    },
    inputId: {
      type: String,
      default: 'symbol-input'
    },
    disabled: {
      type: Boolean,
      default: false
    }
  },
  emits: ['update:modelValue', 'change', 'valid', 'load-info'],
  data() {
    return {
      symbolsCache: {} // Cache symbols by source: { source: [symbols] }
    }
  },
  computed: {
    datalistId() {
      return `${this.inputId}-list`
    },
    symbols() {
      return this.getSymbolsForSource(this.source)
    },
    isValid() {
      // Symbol is valid only if:
      // 1. Source is valid
      // 2. Symbol exists in the list for selected source (case insensitive)
      if (!this.isSourceValid || !this.modelValue) {
        return false
      }
      // If symbols are not loaded yet, consider it valid (will be validated on submit)
      if (this.symbols.length === 0) {
        return true
      }
      // Case-insensitive check
      return this.symbols.some(s => s.toLowerCase() === this.modelValue.toLowerCase())
    }
  },
  watch: {
    source: {
      handler(newSource, oldSource) {
        // Clear symbol when source changes (but only if source actually changed and is not empty)
        // Don't clear if we're just setting the same source or if oldSource was empty (initial load)
        if (newSource !== oldSource && oldSource !== undefined && oldSource !== '') {
          this.$emit('update:modelValue', '')
          this.$emit('change', '')
        }
        // Load symbols if source is valid
        if (newSource && this.isSourceValid && !this.symbolsCache[newSource]) {
          this.loadSymbolsForSource(newSource)
        }
      }
    },
    isSourceValid: {
      handler(newVal) {
        // Load symbols when source becomes valid
        if (newVal && this.source && !this.symbolsCache[this.source]) {
          this.loadSymbolsForSource(this.source)
        }
      },
      immediate: true
    },
    isValid(newVal) {
      this.$emit('valid', newVal)
    }
  },
  mounted() {
    // Load symbols if source is already set and valid
    if (this.source && this.isSourceValid && !this.symbolsCache[this.source]) {
      this.loadSymbolsForSource(this.source)
    }
  },
  methods: {
    async loadSymbolsForSource(source) {
      if (!source || this.symbolsCache[source]) {
        return
      }
      
      try {
        const symbols = await strategiesApi.getSourceSymbols(source)
        this.symbolsCache[source] = symbols
      } catch (error) {
        console.error(`Failed to load symbols for source ${source}:`, error)
        this.symbolsCache[source] = []
      }
    },
    getSymbolsForSource(source) {
      return this.symbolsCache[source] || []
    },
    handleInput(event) {
      const inputValue = event.target.value
      this.$emit('update:modelValue', inputValue)
      this.$emit('change', inputValue)
      
      if (!inputValue || !this.source) {
        return
      }
      
      if (this.symbols.length === 0) {
        return
      }
      
      // Filter symbols that start with input value (case insensitive)
      const searchText = inputValue.toLowerCase()
      const matchingSymbols = this.symbols.filter(symbol => 
        symbol.toLowerCase().startsWith(searchText)
      )
      
      // Auto-select if only one matching symbol remains
      if (matchingSymbols.length === 1) {
        this.$nextTick(() => {
          this.$emit('update:modelValue', matchingSymbols[0])
          this.$emit('change', matchingSymbols[0])
        })
      } else {
        // If exact match found (case insensitive), use the original case from list
        const exactMatch = this.symbols.find(symbol => 
          symbol.toLowerCase() === searchText
        )
        if (exactMatch) {
          this.$nextTick(() => {
            this.$emit('update:modelValue', exactMatch)
            this.$emit('change', exactMatch)
          })
        }
      }
    },
    handleBlur(event) {
      // Emit load-info event when field loses focus
      if (this.modelValue && this.isSourceValid) {
        this.$emit('load-info', this.modelValue)
      }
    },
    handleEnter(event) {
      // Emit load-info event when Enter is pressed
      if (this.modelValue && this.isSourceValid) {
        this.$emit('load-info', this.modelValue)
      }
    },
    handleChange(event) {
      // Emit load-info event when value changes (e.g., selection from datalist)
      // This fires when user selects from datalist dropdown
      const inputValue = event.target.value
      if (inputValue && this.isSourceValid && inputValue === this.modelValue) {
        // Only emit if value matches current modelValue (to avoid duplicate calls)
        this.$emit('load-info', inputValue)
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

.form-input.invalid {
  border-color: var(--color-danger);
  box-shadow: 0 0 0 0.2rem rgba(244, 67, 54, 0.25);
}
</style>

