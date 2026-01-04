<template>
  <div class="backtesting-nav-form">
    <SourceInput
      v-model="formData.source"
      input-id="backtesting-source"
      :required="true"
      :disabled="disabled"
      @valid="isSourceValid = $event"
      title="Exchange or data source (e.g., binance, bybit)"
    />
    <div class="symbol-input-wrapper">
      <SymbolInput
        v-model="formData.symbol"
        :source="formData.source"
        :is-source-valid="isSourceValid"
        input-id="backtesting-symbol"
        :required="true"
        :disabled="disabled"
        @load-info="handleSymbolLoadInfo"
      />
      <button
        class="info-btn"
        :disabled="!formData.symbol || disabled"
        @click="showSymbolInfo"
        title="Show symbol information"
      >
        <InformationCircleIcon class="info-icon" />
      </button>
    </div>
    <div class="form-group">
      <label for="timeframe">
        Timeframe
        <span class="required">*</span>
      </label>
      <input
        id="timeframe"
        v-model="timeframeString"
        type="text"
        class="form-input"
        :class="{ 'invalid': formData.timeframe && timeframes.length > 0 && !isTimeframeValid }"
        :list="timeframeDatalistId"
        placeholder="Type to search timeframe..."
        :disabled="disabled"
        :required="true"
        autocomplete="off"
        title="Trading timeframe (e.g., 1h, 1d, 5m)"
      />
      <datalist :id="timeframeDatalistId">
        <option v-for="tf in timeframes" :key="tf.name" :value="tf.name"></option>
      </datalist>
    </div>
    
    <!-- Separator between main and testing parameters -->
    <div class="form-separator"></div>
    
    <!-- Testing parameters group -->
    <div class="form-group">
      <label for="feeTaker">Fee Taker</label>
      <input
        id="feeTaker"
        v-model.number="formData.feeTaker"
        type="number"
        step="any"
        min="0"
        max="1"
        class="form-input no-spinner"
        :disabled="disabled"
        placeholder="0.001"
        title="Taker fee rate (applied to market orders, as fraction, e.g., 0.001 for 0.1%)"
      />
    </div>
    <div class="form-group">
      <label for="feeMaker">Fee Maker</label>
      <input
        id="feeMaker"
        v-model.number="formData.feeMaker"
        type="number"
        step="any"
        min="0"
        max="1"
        class="form-input no-spinner"
        :disabled="disabled"
        placeholder="0.001"
        title="Maker fee rate (applied to limit orders, as fraction, e.g., 0.001 for 0.1%)"
      />
    </div>
    <div class="form-group">
      <label for="priceStep">Price Step</label>
      <input
        id="priceStep"
        v-model.number="formData.priceStep"
        type="number"
        step="0.0001"
        min="0"
        class="form-input no-spinner"
        :disabled="disabled"
        placeholder="0.0"
        title="Minimum price step for the symbol (e.g., 0.1, 0.001)"
      />
    </div>
    <div class="form-group">
      <button
        type="button"
        class="refresh-btn"
        :disabled="!formData.symbol || !formData.source || disabled || isLoadingSymbolInfo"
        @click="refreshSymbolInfo"
        title="Update fees and price step from exchange (source)"
      >
        <ArrowPathIcon 
          :class="['refresh-icon', { 'spinning': isLoadingSymbolInfo }]"
        />
      </button>
    </div>
    
    <!-- Separator between testing parameters and dates -->
    <div class="form-separator"></div>
    
    <!-- Slippage parameter -->
    <div class="form-group">
      <label for="slippageInSteps">Slippage (in steps)</label>
      <input
        id="slippageInSteps"
        v-model.number="formData.slippageInSteps"
        type="number"
        step="0.1"
        min="0"
        class="form-input no-spinner"
        :disabled="disabled"
        placeholder="0.0"
        title="Slippage in price steps for backtesting (e.g., 1.0 means 1 step). Applied to market orders only during testing."
      />
    </div>
    
    <!-- Date parameters group -->
    <div class="form-group">
      <label for="dateFrom">Date From</label>
      <input
        id="dateFrom"
        v-model="formData.dateFrom"
        type="date"
        class="form-input"
        :disabled="disabled"
        title="Start date for backtesting period"
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
        title="End date for backtesting period"
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
    
    <!-- Symbol Info Modal -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="showSymbolInfoModal"
          class="modal-overlay"
          @click.self="closeSymbolInfo"
        >
          <div class="modal-content symbol-info-modal">
            <div class="modal-header">
              <h3>{{ formData.symbol || 'Symbol Information' }}</h3>
              <button class="close-btn" @click="closeSymbolInfo">
                <XMarkIcon class="icon" />
              </button>
            </div>
            
            <div class="modal-body">
              <div v-if="isLoadingSymbolInfo" class="loading-state">
                <p>Loading symbol information...</p>
              </div>
              
              <div v-else-if="symbolInfoError" class="error-message">
                {{ symbolInfoError }}
              </div>
              
              <div v-else-if="symbolInfo" class="symbol-info-content">
                <div class="info-row">
                  <span class="info-label">Symbol:</span>
                  <span class="info-value">{{ symbolInfo.symbol }}</span>
                </div>
                <div class="info-row">
                  <span class="info-label">Fee Taker:</span>
                  <span class="info-value">{{ symbolInfo.fee_taker !== null && symbolInfo.fee_taker !== undefined ? (symbolInfo.fee_taker * 100).toFixed(4) + '%' : 'N/A' }}</span>
                </div>
                <div class="info-row">
                  <span class="info-label">Fee Maker:</span>
                  <span class="info-value">{{ symbolInfo.fee_maker !== null && symbolInfo.fee_maker !== undefined ? (symbolInfo.fee_maker * 100).toFixed(4) + '%' : 'N/A' }}</span>
                </div>
                <div class="info-row">
                  <span class="info-label">Precision Amount:</span>
                  <span class="info-value">{{ symbolInfo.precision_amount !== null && symbolInfo.precision_amount !== undefined ? symbolInfo.precision_amount : 'N/A' }}</span>
                </div>
                <div class="info-row">
                  <span class="info-label">Precision Price:</span>
                  <span class="info-value">{{ symbolInfo.precision_price !== null && symbolInfo.precision_price !== undefined ? symbolInfo.precision_price : 'N/A' }}</span>
                </div>
                <div v-if="symbolInfo.precision_price !== null && symbolInfo.precision_price !== undefined" class="info-row">
                  <span class="info-label">Price Step:</span>
                  <span class="info-value">{{ symbolInfo.precision_price }}</span>
                </div>
              </div>
            </div>
            
            <div class="modal-footer">
              <button class="btn btn-primary" @click="closeSymbolInfo">Close</button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script>
import { inject, computed, Teleport, Transition } from 'vue'
import SourceInput from './SourceInput.vue'
import SymbolInput from './SymbolInput.vue'
import { PlayIcon, StopIcon, InformationCircleIcon, XMarkIcon, ArrowPathIcon } from '@heroicons/vue/24/outline'

export default {
  name: 'BacktestingNavForm',
  components: {
    SourceInput,
    SymbolInput,
    PlayIcon,
    StopIcon,
    InformationCircleIcon,
    XMarkIcon,
    ArrowPathIcon,
    Teleport,
    Transition
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
    },
    addMessage: {
      type: Function,
      default: null
    }
  },
  setup() {
    const timeframesComposable = inject('timeframes')
    
    // Create a computed that tracks the reactive timeframesList
    // timeframesList is now a ref (via toRef), so access .value
    const timeframesList = computed(() => {
      if (!timeframesComposable) {
        return []
      }
      // Access the ref value to ensure reactivity tracking
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
        timeframe: null, // Timeframe object
        dateFrom: '',
        dateTo: '',
        feeTaker: 0.0,
        feeMaker: 0.0,
        priceStep: 0.0,
        slippageInSteps: 1.0
      },
      isSourceValid: false,
      isLoadingSymbolInfo: false,
      showSymbolInfoModal: false,
      symbolInfo: null,
      symbolInfoError: null
    }
  },
  computed: {
    timeframeDatalistId() {
      return 'backtesting-timeframe-list'
    },
    timeframes() {
      // Use the reactive ref from setup
      return this.timeframesList
    },
    // Computed property for v-model binding with getter/setter
    timeframeString: {
      get() {
        return this.formData.timeframe ? this.formData.timeframe.name : ''
      },
      set(value) {
        // Find Timeframe object by string value
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
        // Emit change event when form data changes
        this.$emit('form-data-changed')
      },
      deep: true
    },
    'formData.source': {
      handler(newSource, oldSource) {
        // Reset symbol info when source changes
        if (newSource !== oldSource) {
          this.formData.feeTaker = 0.0
          this.formData.feeMaker = 0.0
          this.formData.priceStep = 0.0
        }
      }
    }
  },
  methods: {
    handleSymbolLoadInfo(symbol) {
      // Called when symbol input loses focus, Enter is pressed, or value is selected from datalist
      if (symbol && this.formData.source && this.isSourceValid) {
        this.loadSymbolInfo()
      }
    },
    handleAction() {
      if (this.isRunning) {
        this.$emit('stop')
      } else {
        this.$emit('start', { ...this.formData })
      }
    },
    async refreshSymbolInfo() {
      if (!this.formData.source || !this.formData.symbol || this.isLoadingSymbolInfo) {
        return
      }
      
      await this.loadSymbolInfo(true)
    },
    async loadSymbolInfo(showAlert = false) {
      if (!this.formData.source || !this.formData.symbol || this.isLoadingSymbolInfo) {
        return
      }
      
      this.isLoadingSymbolInfo = true
      try {
        const response = await fetch(
          `/api/v1/common/sources/${encodeURIComponent(this.formData.source)}/symbols/info?symbol=${encodeURIComponent(this.formData.symbol)}`
        )
        
        if (response.ok) {
          const responseData = await response.json()
          // Handle new response format with symbol_info and errors
          const symbolInfo = responseData.symbol_info || responseData
          
          // Add warnings to messages if any errors were returned
          if (responseData.errors && Array.isArray(responseData.errors) && responseData.errors.length > 0) {
            responseData.errors.forEach(errorMsg => {
              if (this.addMessage) {
                this.addMessage({
                  level: 'warning',
                  message: errorMsg
                })
              }
              if (showAlert) {
                alert(errorMsg)
              }
            })
          }
          
          // Fill fees - use user-specific fees if available, only update if value is present
          if (symbolInfo.fee_taker !== null && symbolInfo.fee_taker !== undefined) {
            this.formData.feeTaker = symbolInfo.fee_taker
          }
          if (symbolInfo.fee_maker !== null && symbolInfo.fee_maker !== undefined) {
            this.formData.feeMaker = symbolInfo.fee_maker
          }
          
          // Use precision_price as price_step
          if (symbolInfo.precision_price !== null && symbolInfo.precision_price !== undefined) {
            this.formData.priceStep = symbolInfo.precision_price
          }
        } else if (response.status === 404) {
          // Symbol not found
          const errorMsg = `Symbol '${this.formData.symbol}' not found for source '${this.formData.source}'`
          if (this.addMessage) {
            this.addMessage({
              level: 'error',
              message: errorMsg
            })
          }
          if (showAlert) {
            alert(errorMsg)
          }
        } else {
          // Other errors
          const errorMsg = `Failed to load symbol info: ${response.status} ${response.statusText}`
          if (this.addMessage) {
            this.addMessage({
              level: 'error',
              message: errorMsg
            })
          }
          if (showAlert) {
            alert(errorMsg)
          }
          console.warn(errorMsg)
        }
      } catch (error) {
        // Network or other errors - log but keep current values
        console.warn('Failed to load symbol info:', error)
      } finally {
        this.isLoadingSymbolInfo = false
      }
    },
    async showSymbolInfo() {
      if (!this.formData.source || !this.formData.symbol) {
        return
      }
      
      this.showSymbolInfoModal = true
      this.symbolInfo = null
      this.symbolInfoError = null
      
      try {
        const response = await fetch(
          `/api/v1/common/sources/${encodeURIComponent(this.formData.source)}/symbols/info?symbol=${encodeURIComponent(this.formData.symbol)}`
        )
        
        if (response.ok) {
          const responseData = await response.json()
          // Handle new response format with symbol_info and errors
          this.symbolInfo = responseData.symbol_info || responseData
          
          // Add warnings to messages if any errors were returned
          if (responseData.errors && Array.isArray(responseData.errors) && responseData.errors.length > 0) {
            responseData.errors.forEach(errorMsg => {
              if (this.addMessage) {
                this.addMessage({
                  level: 'warning',
                  message: errorMsg
                })
              }
            })
          }
        } else if (response.status === 404) {
          this.symbolInfoError = `Symbol '${this.formData.symbol}' not found for source '${this.formData.source}'`
        } else {
          this.symbolInfoError = `Failed to load symbol information: ${response.status} ${response.statusText}`
        }
      } catch (error) {
        this.symbolInfoError = `Failed to load symbol information: ${error.message}`
      }
    },
    closeSymbolInfo() {
      this.showSymbolInfoModal = false
      this.symbolInfo = null
      this.symbolInfoError = null
    }
  }
}
</script>

<style scoped>
.backtesting-nav-form {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--spacing-lg);
  height: auto;
  min-height: var(--navbar-height);
  align-content: center;
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

/* Hide spinner arrows for number inputs with no-spinner class */
.form-input.no-spinner::-webkit-inner-spin-button,
.form-input.no-spinner::-webkit-outer-spin-button {
  -webkit-appearance: none;
  appearance: none;
  margin: 0;
}

.form-input.no-spinner {
  -moz-appearance: textfield;
  appearance: textfield;
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

.form-separator {
  width: 2px;
  height: 3rem;
  background-color: var(--border-color-dark);
  margin: 0 var(--spacing-sm);
}

.symbol-input-wrapper {
  position: relative;
  display: flex;
  flex-direction: column;
}

.symbol-input-wrapper :deep(.form-group) {
  flex: 1;
}

.symbol-input-wrapper :deep(.form-input) {
  padding-right: 2.5rem;
}

.info-btn {
  position: absolute;
  right: 2px;
  top: calc(var(--spacing-xs) + 0.75rem + 2px);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: calc(100% - var(--spacing-xs) - 0.75rem - 4px);
  padding: 0;
  border: none;
  border-radius: 0 var(--radius-md) var(--radius-md) 0;
  background-color: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-base);
  box-sizing: border-box;
  z-index: 1;
}

.info-btn:hover:not(:disabled) {
  background-color: var(--bg-secondary);
  color: var(--text-primary);
}

.info-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.info-icon {
  width: 1.25rem;
  height: 1.25rem;
}

.refresh-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2.5rem;
  padding: 0;
  border: 1px solid var(--border-color-dark);
  border-radius: var(--radius-md);
  background-color: var(--bg-primary);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-base);
  box-sizing: border-box;
  margin-top: calc(var(--spacing-xs) + 0.75rem);
}

.refresh-btn:hover:not(:disabled) {
  background-color: var(--bg-secondary);
  color: var(--text-primary);
  border-color: var(--border-color-light);
}

.refresh-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.refresh-icon {
  width: 1.25rem;
  height: 1.25rem;
  transition: transform var(--transition-base);
}

.refresh-icon.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

/* Modal styles */
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
  background-color: var(--bg-primary);
  border-radius: var(--radius-lg);
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
  max-width: 500px;
  width: 90%;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
}

.symbol-info-modal {
  min-width: 400px;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--spacing-lg);
  border-bottom: 1px solid var(--border-color-dark);
}

.modal-header h3 {
  margin: 0;
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
}

.close-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: var(--radius-md);
  transition: all var(--transition-base);
}

.close-btn:hover {
  background-color: var(--bg-secondary);
  color: var(--text-primary);
}

.close-btn .icon {
  width: 1.25rem;
  height: 1.25rem;
}

.modal-body {
  padding: var(--spacing-lg);
  overflow-y: auto;
  flex: 1;
}

.loading-state,
.error-message {
  text-align: center;
  padding: var(--spacing-md);
  color: var(--text-secondary);
}

.error-message {
  color: var(--color-danger);
}

.symbol-info-content {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--spacing-sm) 0;
  border-bottom: 1px solid var(--border-color-dark);
}

.info-row:last-child {
  border-bottom: none;
}

.info-label {
  font-weight: var(--font-weight-medium);
  color: var(--text-secondary);
}

.info-value {
  color: var(--text-primary);
  font-family: monospace;
}

.modal-footer {
  padding: var(--spacing-lg);
  border-top: 1px solid var(--border-color-dark);
  display: flex;
  justify-content: flex-end;
  gap: var(--spacing-md);
}

.btn {
  padding: var(--spacing-sm) var(--spacing-lg);
  border: none;
  border-radius: var(--radius-md);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  transition: all var(--transition-base);
}

.btn-primary {
  background-color: var(--color-primary);
  color: var(--text-inverse);
}

.btn-primary:hover {
  background-color: var(--color-primary-hover);
}

/* Modal transition */
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.2s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-active .modal-content,
.modal-leave-active .modal-content {
  transition: transform 0.2s ease, opacity 0.2s ease;
}

.modal-enter-from .modal-content,
.modal-leave-to .modal-content {
  transform: scale(0.95);
  opacity: 0;
}
</style>

