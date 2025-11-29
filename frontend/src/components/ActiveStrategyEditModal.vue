<template>
  <Teleport to="body">
    <Transition name="modal">
      <div 
        v-if="isOpen" 
        class="modal-overlay"
      >
        <div class="modal-content">
          <div class="modal-header">
            <h3>{{ isNew ? 'Add Active Strategy' : 'Edit Active Strategy' }}</h3>
            <button class="close-btn" @click="handleCancel">
              <XMarkIcon class="icon" />
            </button>
          </div>
          
          <div class="modal-body">
            <div class="form-group">
              <label>Active Strategy ID</label>
              <input 
                type="text" 
                :value="formData.active_strategy_id" 
                disabled
                class="form-input disabled"
              />
            </div>
            
            <div class="form-group">
              <label>Strategy ID <span class="required">*</span></label>
              <input 
                type="text" 
                v-model="formData.strategy_id"
                class="form-input"
                required
              />
            </div>
            
            <div class="form-group">
              <label>Name <span class="required">*</span></label>
              <input 
                type="text" 
                v-model="formData.name"
                class="form-input"
                required
              />
            </div>
            
            <div class="form-group">
              <label>Source <span class="required">*</span></label>
              <input 
                type="text"
                v-model="formData.source"
                class="form-input"
                :class="{ 'invalid': formData.source && !isSourceValid }"
                list="sources-list"
                placeholder="Type to search source..."
                required
                autocomplete="off"
                @focus="isSourceInputFocused = true"
                @blur="isSourceInputFocused = false"
                @input="handleSourceInput"
              />
              <datalist id="sources-list">
                <option v-for="source in sources" :key="source" :value="source"></option>
              </datalist>
            </div>
            
            <div class="form-group">
              <label>Symbol <span class="required">*</span></label>
              <input 
                type="text"
                v-model="formData.symbol"
                class="form-input"
                :class="{ 'invalid': formData.symbol && !isSymbolValid }"
                list="symbols-list"
                placeholder="Type to search symbol..."
                :disabled="!isSourceValid"
                required
                autocomplete="off"
                @input="handleSymbolInput"
              />
              <datalist id="symbols-list">
                <option v-for="symbol in getSymbolsForSource(formData.source)" :key="symbol" :value="symbol"></option>
              </datalist>
            </div>
            
            <div class="form-group">
              <label>Timeframe <span class="required">*</span></label>
              <select 
                v-model="formData.timeframe"
                class="form-input form-select"
                required
              >
                <option value="">Select timeframe</option>
                <option v-for="tf in timeframes" :key="tf" :value="tf">{{ tf }}</option>
              </select>
            </div>
            
            <div class="form-group">
              <label>Date Start <span class="required">*</span></label>
              <input 
                type="datetime-local" 
                v-model="formData.dateStart"
                class="form-input"
                required
              />
            </div>
            
            <div class="form-group">
              <label>Date End</label>
              <input 
                :type="formData.isTrading ? 'text' : 'datetime-local'"
                v-model="formData.dateEnd"
                class="form-input"
                :disabled="formData.isTrading"
                :placeholder="formData.isTrading ? '' : undefined"
              />
            </div>
            
            <div class="form-group checkbox-group">
              <div class="checkbox-container">
                <label class="checkbox-label">
                  <input 
                    type="checkbox" 
                    v-model="formData.isRunning"
                    class="checkbox"
                  />
                  <span class="checkbox-text">Start</span>
                </label>
                <label class="checkbox-label">
                  <input 
                    type="checkbox" 
                    v-model="formData.isTrading"
                    class="checkbox"
                  />
                  <span class="checkbox-text">Real Trading</span>
                </label>
              </div>
            </div>
          </div>
          
          <div class="modal-footer">
            <button class="btn btn-cancel" @click="handleCancel">Cancel</button>
            <button class="btn btn-ok" @click="handleOk">OK</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script>
import { XMarkIcon } from '@heroicons/vue/24/outline'
import { activeStrategiesApi } from '../services/activeStrategiesApi'

export default {
  name: 'ActiveStrategyEditModal',
  props: {
    isOpen: {
      type: Boolean,
      default: false
    },
    strategy: {
      type: Object,
      default: null
    },
    isNew: {
      type: Boolean,
      default: false
    },
    timeframes: {
      type: Array,
      default: () => []
    },
    sources: {
      type: Array,
      default: () => []
    }
  },
  emits: ['close', 'save'],
  components: {
    XMarkIcon
  },
  data() {
    return {
      formData: {
        active_strategy_id: null,
        strategy_id: '',
        name: '',
        source: '',
        symbol: '',
        timeframe: '',
        isRunning: false,
        isTrading: false,
        dateStart: '',
        dateEnd: ''
      },
      savedDateEnd: '', // Store dateEnd when Real Trading is enabled
      isSourceInputFocused: false, // Track if source input is focused
      symbolsCache: {} // Cache symbols by source: { source: [symbols] }
    }
  },
  computed: {
    filteredSources() {
      if (!this.formData.source) {
        return this.sources
      }
      const searchText = this.formData.source.toLowerCase()
      return this.sources.filter(source => 
        source.toLowerCase().startsWith(searchText)
      )
    },
    isSourceValid() {
      // Source is valid only if it exists in the sources list
      return this.formData.source && this.sources.includes(this.formData.source)
    },
    isSymbolValid() {
      // Symbol is valid only if:
      // 1. Source is valid
      // 2. Symbol exists in the list for selected source
      if (!this.isSourceValid || !this.formData.symbol) {
        return false
      }
      const symbols = this.getSymbolsForSource(this.formData.source)
      // If symbols are not loaded yet, consider it valid (will be validated on submit)
      if (symbols.length === 0) {
        return true
      }
      return symbols.includes(this.formData.symbol)
    }
  },
  mounted() {
    // Add ESC key handler
    document.addEventListener('keydown', this.handleKeyDown)
  },
  beforeUnmount() {
    // Remove ESC key handler
    document.removeEventListener('keydown', this.handleKeyDown)
  },
  watch: {
    strategy: {
      handler(newStrategy) {
        if (newStrategy) {
          const dateEnd = this.formatDateTimeLocal(newStrategy.dateEnd)
          this.formData = {
            active_strategy_id: newStrategy.active_strategy_id,
            strategy_id: newStrategy.strategy_id || '',
            name: newStrategy.name || '',
            source: newStrategy.source || '',
            symbol: newStrategy.symbol || '',
            timeframe: newStrategy.timeframe || '',
            isRunning: newStrategy.isRunning || false,
            isTrading: newStrategy.isTrading || false,
            dateStart: this.formatDateTimeLocal(newStrategy.dateStart),
            dateEnd: newStrategy.isTrading ? '' : dateEnd
          }
          // Save dateEnd if Real Trading is enabled
          if (newStrategy.isTrading && dateEnd) {
            this.savedDateEnd = dateEnd
          } else {
            this.savedDateEnd = ''
          }
        }
      },
      immediate: true,
      deep: true
    },
    'formData.isTrading': {
      handler(isTrading) {
        if (isTrading) {
          // Save and hide dateEnd when Real Trading is enabled
          this.savedDateEnd = this.formData.dateEnd
          this.formData.dateEnd = ''
        } else {
          // Restore dateEnd when Real Trading is disabled
          if (this.savedDateEnd) {
            this.formData.dateEnd = this.savedDateEnd
            this.savedDateEnd = ''
          }
        }
      }
    },
    'formData.source': {
      handler(newSource, oldSource) {
        // Clear symbol when source changes
        if (newSource !== oldSource) {
          this.formData.symbol = ''
        }
        // Load symbols only if source is a valid source from the list
        // This prevents requests when user is typing
        if (newSource && this.sources.includes(newSource) && !this.symbolsCache[newSource]) {
          this.loadSymbolsForSource(newSource)
        }
      }
    }
  },
  methods: {
    formatDateTimeLocal(isoString) {
      if (!isoString) return ''
      const date = new Date(isoString)
      const year = date.getFullYear()
      const month = String(date.getMonth() + 1).padStart(2, '0')
      const day = String(date.getDate()).padStart(2, '0')
      const hours = String(date.getHours()).padStart(2, '0')
      const minutes = String(date.getMinutes()).padStart(2, '0')
      return `${year}-${month}-${day}T${hours}:${minutes}`
    },
    formatToISO(dateTimeLocal) {
      if (!dateTimeLocal) return null
      return new Date(dateTimeLocal).toISOString()
    },
    validate() {
      if (!this.formData.strategy_id.trim()) {
        alert('Strategy ID is required')
        return false
      }
      if (!this.formData.name.trim()) {
        alert('Name is required')
        return false
      }
      if (!this.formData.source.trim()) {
        alert('Source is required')
        return false
      }
      // Validate that source exists in the list
      if (!this.sources.includes(this.formData.source)) {
        alert(`Source "${this.formData.source}" is not valid. Please select from the list.`)
        return false
      }
      if (!this.formData.symbol.trim()) {
        alert('Symbol is required')
        return false
      }
      // Validate that symbol exists in the list for selected source
      if (this.formData.source) {
        const symbols = this.getSymbolsForSource(this.formData.source)
        if (symbols.length > 0 && !symbols.includes(this.formData.symbol)) {
          alert(`Symbol "${this.formData.symbol}" is not valid for source "${this.formData.source}". Please select from the list.`)
          return false
        }
      }
      if (!this.formData.timeframe.trim()) {
        alert('Timeframe is required')
        return false
      }
      if (!this.formData.dateStart) {
        alert('Date Start is required')
        return false
      }
      if (this.formData.dateEnd && new Date(this.formData.dateStart) >= new Date(this.formData.dateEnd)) {
        alert('Date End must be after Date Start')
        return false
      }
      return true
    },
    handleOk() {
      if (!this.validate()) {
        return
      }
      
      const data = {
        ...this.formData,
        dateStart: this.formatToISO(this.formData.dateStart),
        dateEnd: this.formatToISO(this.formData.dateEnd)
      }
      
      this.$emit('save', data)
    },
    handleCancel() {
      this.$emit('close')
    },
    handleKeyDown(event) {
      // Close modal on ESC key
      if (event.key === 'Escape' && this.isOpen) {
        this.handleCancel()
      }
    },
    handleSourceInput(event) {
      const inputValue = event.target.value
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
          this.formData.source = matchingSources[0]
        })
      }
    },
    async loadSymbolsForSource(source) {
      if (!source || this.symbolsCache[source]) {
        return
      }
      
      try {
        const symbols = await activeStrategiesApi.getSourceSymbols(source)
        this.symbolsCache[source] = symbols
      } catch (error) {
        console.error(`Failed to load symbols for source ${source}:`, error)
        this.symbolsCache[source] = []
      }
    },
    getSymbolsForSource(source) {
      return this.symbolsCache[source] || []
    },
    handleSymbolInput(event) {
      const inputValue = event.target.value
      if (!inputValue || !this.formData.source) {
        return
      }
      
      const symbols = this.getSymbolsForSource(this.formData.source)
      if (symbols.length === 0) {
        return
      }
      
      // Filter symbols that start with input value (case insensitive)
      const searchText = inputValue.toLowerCase()
      const matchingSymbols = symbols.filter(symbol => 
        symbol.toLowerCase().startsWith(searchText)
      )
      
      // Auto-select if only one matching symbol remains
      if (matchingSymbols.length === 1) {
        this.$nextTick(() => {
          this.formData.symbol = matchingSymbols[0]
        })
      }
    }
  }
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-content {
  background: white;
  border-radius: 8px;
  width: 90%;
  max-width: 500px;
  max-height: 90vh;
  overflow-y: auto;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px;
  border-bottom: 1px solid #e0e0e0;
}

.modal-header h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #333;
}

.close-btn {
  background: none;
  border: none;
  cursor: pointer;
  padding: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #666;
  transition: color 0.2s;
}

.close-btn:hover {
  color: #333;
}

.close-btn .icon {
  width: 20px;
  height: 20px;
}

.modal-body {
  padding: 20px;
}

.form-group {
  margin-bottom: 16px;
}

.form-group > label:not(.checkbox-label) {
  display: block;
  margin-bottom: 6px;
  font-size: 14px;
  font-weight: 500;
  color: #333;
}

.required {
  color: #f44336;
}

.form-input {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 14px;
  transition: border-color 0.2s;
}

.form-input:focus {
  outline: none;
  border-color: #2196f3;
}

.form-select {
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%23333' d='M6 9L1 4h10z'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 12px center;
  padding-right: 36px;
}

.form-input.disabled,
.form-input:disabled {
  background-color: #f5f5f5;
  color: #999;
  cursor: not-allowed;
}

.form-input.no-placeholder::placeholder {
  color: transparent;
}

.form-input.no-placeholder::-webkit-input-placeholder {
  color: transparent;
}

.form-input.no-placeholder::-moz-placeholder {
  color: transparent;
}

.form-input.no-placeholder:-ms-input-placeholder {
  color: transparent;
}

.form-input.invalid {
  border-color: #dc3545;
  box-shadow: 0 0 0 0.2rem rgba(220, 53, 69, 0.25);
}

.checkbox-group {
  margin-top: 8px;
  display: flex;
  justify-content: flex-end;
  align-items: flex-end;
}

.checkbox-container {
  display: flex;
  justify-content: flex-end;
  gap: 24px;
  align-items: flex-end;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-weight: normal;
  margin-bottom: 0;
  user-select: none;
}

.checkbox {
  width: 18px;
  height: 18px;
  min-width: 18px;
  max-width: 18px;
  cursor: pointer;
  margin: 0;
  padding: 0;
  flex-shrink: 0;
}

.checkbox-text {
  display: block;
  line-height: 1.5;
  font-size: 14px;
  white-space: nowrap;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 20px;
  border-top: 1px solid #e0e0e0;
}

.btn {
  padding: 8px 16px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-cancel {
  background-color: #ffffff;
  color: #666;
}

.btn-cancel:hover {
  background-color: #f5f5f5;
  border-color: #bbb;
}

.btn-ok {
  background-color: #2196f3;
  color: white;
  border-color: #2196f3;
}

.btn-ok:hover {
  background-color: #1976d2;
  border-color: #1976d2;
}

/* Transition animations */
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.3s;
}

.modal-enter-active .modal-content,
.modal-leave-active .modal-content {
  transition: transform 0.3s, opacity 0.3s;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-from .modal-content,
.modal-leave-to .modal-content {
  transform: scale(0.9);
  opacity: 0;
}
</style>

