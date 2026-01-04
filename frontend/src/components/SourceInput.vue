<template>
  <div class="form-group">
    <label :for="inputId">
      Source
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
      :disabled="disabled"
      autocomplete="off"
      :title="title || 'Exchange or data source (e.g., binance, bybit)'"
      @input="handleInput"
      @focus="isFocused = true"
      @blur="isFocused = false"
    />
    <datalist :id="datalistId">
      <option v-for="source in sources" :key="source" :value="source"></option>
    </datalist>
  </div>
</template>

<script>
import { strategiesApi } from '../services/strategiesApi'

export default {
  name: 'SourceInput',
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
      default: 'Type to search source...'
    },
    inputId: {
      type: String,
      default: 'source-input'
    },
    disabled: {
      type: Boolean,
      default: false
    },
    title: {
      type: String,
      default: 'Exchange or data source (e.g., binance, bybit)'
    }
  },
  emits: ['update:modelValue', 'change', 'valid'],
  data() {
    return {
      sources: [],
      isFocused: false
    }
  },
  computed: {
    datalistId() {
      return `${this.inputId}-list`
    },
    isValid() {
      return this.modelValue && this.sources.includes(this.modelValue)
    }
  },
  watch: {
    isValid(newVal) {
      this.$emit('valid', newVal)
    }
  },
  mounted() {
    this.loadSources()
  },
  methods: {
    async loadSources() {
      try {
        this.sources = await strategiesApi.getSources()
      } catch (error) {
        console.error('Failed to load sources:', error)
        this.sources = []
      }
    },
    handleInput(event) {
      const inputValue = event.target.value
      this.$emit('update:modelValue', inputValue)
      this.$emit('change', inputValue)
      
      if (!inputValue) {
        return
      }
      
      // Filter sources that start with input value (case insensitive)
      const searchText = inputValue.toLowerCase()
      const matchingSources = this.sources.filter(source => 
        source.toLowerCase().startsWith(searchText)
      )
      
      // Auto-select if only one matching source remains
      if (matchingSources.length === 1) {
        this.$nextTick(() => {
          this.$emit('update:modelValue', matchingSources[0])
          this.$emit('change', matchingSources[0])
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


.form-input.invalid {
  border-color: var(--color-danger);
  box-shadow: 0 0 0 0.2rem rgba(244, 67, 54, 0.25);
}
</style>

