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
            
            <StrategyInput
              v-model="formData.strategy_id"
              input-id="modal-strategy"
              :required="true"
              @valid="isStrategyIdValid = $event"
            />
            
            <SourceInput
              v-model="formData.source"
              input-id="modal-source"
              :required="true"
              @valid="isSourceValid = $event"
            />
            
            <SymbolInput
              v-model="formData.symbol"
              :source="formData.source"
              :is-source-valid="isSourceValid"
              input-id="modal-symbol"
              :required="true"
              @valid="isSymbolValid = $event"
            />
            
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
import SourceInput from './SourceInput.vue'
import SymbolInput from './SymbolInput.vue'
import StrategyInput from './StrategyInput.vue'

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
    },
    strategies: {
      type: Array,
      default: () => []
    }
  },
  emits: ['close', 'save'],
  components: {
    XMarkIcon,
    SourceInput,
    SymbolInput,
    StrategyInput
  },
  data() {
    return {
      formData: {
        active_strategy_id: null,
        strategy_id: '',
        source: '',
        symbol: '',
        timeframe: '',
        isRunning: false,
        isTrading: false,
        dateStart: '',
        dateEnd: ''
      },
      savedDateEnd: '', // Store dateEnd when Real Trading is enabled
      isSourceValid: false,
      isSymbolValid: false,
      isStrategyIdValid: false
    }
  },
  computed: {
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
      // Validate that strategy_id exists in the list
      if (!this.strategies.includes(this.formData.strategy_id)) {
        alert(`Strategy ID "${this.formData.strategy_id}" is not valid. Please select from the list.`)
        return false
      }
      if (!this.formData.source.trim()) {
        alert('Source is required')
        return false
      }
      // Validate that source is valid
      if (!this.isSourceValid) {
        alert(`Source "${this.formData.source}" is not valid. Please select from the list.`)
        return false
      }
      if (!this.formData.symbol.trim()) {
        alert('Symbol is required')
        return false
      }
      // Validate that symbol is valid
      if (!this.isSymbolValid) {
        alert(`Symbol "${this.formData.symbol}" is not valid for source "${this.formData.source}". Please select from the list.`)
        return false
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
  z-index: var(--z-modal);
}

.modal-content {
  background: var(--bg-primary);
  border-radius: var(--radius-lg);
  width: 90%;
  max-width: 500px;
  max-height: 90vh;
  overflow-y: auto;
  box-shadow: var(--shadow-md);
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--spacing-xl);
  border-bottom: 1px solid var(--border-color-light);
}

.modal-header h3 {
  margin: 0;
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
}

.close-btn {
  background: none;
  border: none;
  cursor: pointer;
  padding: var(--spacing-xs);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-tertiary);
  transition: color var(--transition-base);
}

.close-btn:hover {
  color: var(--text-primary);
}

.close-btn .icon {
  width: 20px;
  height: 20px;
}

.modal-body {
  padding: var(--spacing-xl);
}

.form-group {
  margin-bottom: var(--spacing-lg);
}

.form-group > label:not(.checkbox-label) {
  display: block;
  margin-bottom: var(--spacing-sm);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--text-primary);
}

.required {
  color: var(--color-danger);
}

.form-input {
  width: 100%;
  padding: var(--spacing-sm) var(--spacing-md);
  border: 1px solid var(--border-color-dark);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-sm);
  transition: border-color var(--transition-base);
}

.form-input:focus {
  outline: none;
  border-color: var(--color-info);
}

.form-select {
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%23333' d='M6 9L1 4h10z'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right var(--spacing-md) center;
  padding-right: 36px;
}

.form-input.disabled,
.form-input:disabled {
  background-color: var(--bg-tertiary);
  color: var(--text-muted);
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
  border-color: var(--color-danger);
  box-shadow: 0 0 0 0.2rem rgba(244, 67, 54, 0.25);
}

.checkbox-group {
  margin-top: var(--spacing-sm);
  display: flex;
  justify-content: flex-end;
  align-items: flex-end;
}

.checkbox-container {
  display: flex;
  justify-content: flex-end;
  gap: var(--spacing-xl);
  align-items: flex-end;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  cursor: pointer;
  font-weight: var(--font-weight-normal);
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
  font-size: var(--font-size-sm);
  white-space: nowrap;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: var(--spacing-md);
  padding: var(--spacing-xl);
  border-top: 1px solid var(--border-color-light);
}

.btn {
  padding: var(--spacing-sm) var(--spacing-lg);
  border: 1px solid var(--border-color-dark);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  transition: all var(--transition-base);
}

.btn-cancel {
  background-color: var(--bg-primary);
  color: var(--text-tertiary);
}

.btn-cancel:hover {
  background-color: var(--bg-hover);
  border-color: var(--border-color);
}

.btn-ok {
  background-color: var(--color-info);
  color: var(--text-inverse);
  border-color: var(--color-info);
}

.btn-ok:hover {
  background-color: var(--color-info-hover);
  border-color: var(--color-info-hover);
}

/* Transition animations */
.modal-enter-active,
.modal-leave-active {
  transition: opacity var(--transition-slow);
}

.modal-enter-active .modal-content,
.modal-leave-active .modal-content {
  transition: transform var(--transition-slow), opacity var(--transition-slow);
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

