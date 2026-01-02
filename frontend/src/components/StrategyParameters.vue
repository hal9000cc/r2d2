<template>
  <div class="strategy-parameters">
    <div class="parameters-header">
      <h3>Strategy Parameters</h3>
      <button 
        class="btn-update"
        @click="handleUpdate"
        :disabled="!strategyName || strategyName === null || strategyName === ''"
        title="Update parameters list from strategy"
      >
        Update
      </button>
    </div>
    <div class="parameters-content">
      <div v-if="!strategyName" class="empty-state">
        <p>No strategy selected</p>
      </div>
      <div v-else-if="!parametersDescription || Object.keys(parametersDescription).length === 0" class="empty-state">
        <p>No parameters available</p>
      </div>
      <table v-else class="parameters-table">
        <thead>
          <tr>
            <th>Parameter</th>
            <th>Value</th>
            <th>Description</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(paramDesc, paramName) in parametersDescription" :key="paramName">
            <td class="param-name">{{ paramName }}</td>
            <td class="param-value">
              <input
                :value="getInputValue(paramName, paramDesc.type)"
                @input="handleValueInput(paramName, $event)"
                :type="getInputType(paramDesc.type)"
                :placeholder="getPlaceholder(paramDesc.type)"
                @blur="handleValueBlur(paramName, paramDesc.type)"
                class="param-input"
              />
            </td>
            <td class="param-description">{{ paramDesc.description }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script>
export default {
  name: 'StrategyParameters',
  props: {
    parametersDescription: {
      type: Object,
      default: null
    },
    strategyName: {
      type: String,
      default: null
    },
    initialParameters: {
      type: Object,
      default: null
    }
  },
  emits: ['update-parameters', 'parameters-changed'],
  data() {
    return {
      parameterValues: {}
    }
  },
  watch: {
    strategyName(newName, oldName) {
      // Load saved values when strategy changes
      if (newName !== oldName) {
        this.loadParameterValues()
      }
    },
    initialParameters: {
      handler(newParams, oldParams) {
        // Load parameters from task when they change
        // Check if parameters actually changed (by comparing JSON strings)
        const newParamsStr = newParams ? JSON.stringify(newParams) : 'null'
        const oldParamsStr = oldParams ? JSON.stringify(oldParams) : 'null'
        
        if (newParamsStr !== oldParamsStr) {
          if (newParams && Object.keys(newParams).length > 0) {
            // Only update if parametersDescription is loaded, otherwise wait
            if (this.parametersDescription && Object.keys(this.parametersDescription).length > 0) {
              this.parameterValues = { ...newParams }
              this.updateParameterValues()
            } else {
              // Store parameters temporarily, will be applied when description loads
              this.parameterValues = { ...newParams }
            }
          } else if (newParams === null || (newParams && Object.keys(newParams).length === 0)) {
            // If parameters are null or empty, clear values but keep defaults from description
            this.parameterValues = {}
            if (this.parametersDescription && Object.keys(this.parametersDescription).length > 0) {
              this.updateParameterValues()
            }
          }
        }
      },
      deep: true,
      immediate: true
    },
    parametersDescription: {
      handler(newDesc, oldDesc) {
        // Update parameter values when description changes
        if (newDesc && (!oldDesc || JSON.stringify(newDesc) !== JSON.stringify(oldDesc))) {
          // If we have initialParameters, use them instead of defaults
          if (this.initialParameters && Object.keys(this.initialParameters).length > 0) {
            this.parameterValues = { ...this.initialParameters }
          }
          this.updateParameterValues()
        }
      },
      deep: true,
      immediate: true
    }
  },
  mounted() {
    this.loadParameterValues()
  },
  methods: {
    getStorageKey() {
      if (!this.strategyName) return null
      return `backtesting-params-${this.strategyName}`
    },
    loadParameterValues() {
      const storageKey = this.getStorageKey()
      if (!storageKey) {
        this.parameterValues = {}
        return
      }
      
      // First, try to use initialParameters if provided (from task)
      if (this.initialParameters && Object.keys(this.initialParameters).length > 0) {
        this.parameterValues = { ...this.initialParameters }
        // Update parameter values based on current description
        this.updateParameterValues()
        return
      }
      
      try {
        const saved = localStorage.getItem(storageKey)
        if (saved) {
          const loaded = JSON.parse(saved)
          // Normalize: convert null and undefined, but keep all valid values including 0
          const normalized = {}
          for (const key in loaded) {
            const value = loaded[key]
            if (value === null || value === undefined) {
              // Will be set to default in updateParameterValues
              normalized[key] = null
            } else {
              normalized[key] = value
            }
          }
          this.parameterValues = normalized
        } else {
          this.parameterValues = {}
        }
      } catch (error) {
        console.error('Failed to load parameter values:', error)
        this.parameterValues = {}
      }
      
      // Update parameter values based on current description
      this.updateParameterValues()
    },
    saveParameterValues() {
      const storageKey = this.getStorageKey()
      if (!storageKey) return
      
      try {
        localStorage.setItem(storageKey, JSON.stringify(this.parameterValues))
      } catch (error) {
        console.error('Failed to save parameter values:', error)
      }
    },
    updateParameterValues() {
      if (!this.parametersDescription) {
        // Don't clear values if description is not loaded yet - preserve current values
        return
      }
      
      // Create a copy of current values
      const newValues = { ...this.parameterValues }
      
      // Add missing parameters (use default value from description)
      for (const paramName in this.parametersDescription) {
        if (!(paramName in newValues)) {
          // Use default value from parameter description
          const paramDesc = this.parametersDescription[paramName]
          const defaultValue = paramDesc.default_value !== undefined ? paramDesc.default_value : ''
          newValues[paramName] = this.convertValueToType(defaultValue, paramDesc.type)
        } else {
          // Normalize: treat null or undefined, but keep existing valid values
          const value = newValues[paramName]
          if (value === null || value === undefined) {
            const paramDesc = this.parametersDescription[paramName]
            const defaultValue = paramDesc.default_value !== undefined ? paramDesc.default_value : ''
            newValues[paramName] = this.convertValueToType(defaultValue, paramDesc.type)
          }
        }
      }
      
      // Remove parameters that are no longer in description
      for (const paramName in newValues) {
        if (!(paramName in this.parametersDescription)) {
          delete newValues[paramName]
        }
      }
      
      this.parameterValues = newValues
      this.saveParameterValues()
    },
    handleUpdate() {
      // Emit event to parent to update parameters description
      this.$emit('update-parameters')
    },
    getInputType(paramType) {
      // Return appropriate input type based on parameter type
      const typeLower = paramType.toLowerCase()
      if (typeLower === 'int' || typeLower === 'integer') {
        return 'number'
      } else if (typeLower === 'float' || typeLower === 'double') {
        return 'number'
      } else if (typeLower === 'bool' || typeLower === 'boolean') {
        return 'checkbox'
      }
      return 'text'
    },
    getPlaceholder(paramType) {
      // No placeholder needed - values are always defined
      return ''
    },
    convertValueToType(value, paramType) {
      // Convert value to appropriate type for storage
      if (value === null || value === undefined || value === '') {
        // Get default value from description
        return value
      }
      
      const typeLower = paramType.toLowerCase()
      if (typeLower === 'int' || typeLower === 'integer') {
        const parsed = parseInt(value, 10)
        return isNaN(parsed) ? value : parsed
      } else if (typeLower === 'float' || typeLower === 'double') {
        const parsed = parseFloat(value)
        return isNaN(parsed) ? value : parsed
      } else if (typeLower === 'bool' || typeLower === 'boolean') {
        return Boolean(value)
      }
      return String(value)
    },
    getInputValue(paramName, paramType) {
      const value = this.parameterValues[paramName]
      // Always return a value - never undefined
      if (value === null || value === undefined || value === '') {
        // Get default value from description
        const paramDesc = this.parametersDescription[paramName]
        if (paramDesc && paramDesc.default_value !== undefined) {
          return String(paramDesc.default_value)
        }
        return ''
      }
      // For number types, ensure we return a string representation
      const typeLower = paramType.toLowerCase()
      if (typeLower === 'int' || typeLower === 'integer' || typeLower === 'float' || typeLower === 'double') {
        return String(value)
      }
      return String(value)
    },
    handleValueInput(paramName, event) {
      // Update value immediately for v-model-like behavior
      const value = event.target.value
      this.parameterValues[paramName] = value
      // Emit change event for auto-save
      this.$emit('parameters-changed')
    },
    handleValueBlur(paramName, paramType) {
      // Validate and convert value based on type
      const value = this.parameterValues[paramName]
      const paramDesc = this.parametersDescription[paramName]
      
      // If empty, use default value
      if (value === '' || value === null || value === undefined) {
        const defaultValue = paramDesc && paramDesc.default_value !== undefined ? paramDesc.default_value : ''
        this.parameterValues[paramName] = this.convertValueToType(defaultValue, paramType)
        this.saveParameterValues()
        return
      }
      
      const typeLower = paramType.toLowerCase()
      let convertedValue = value
      
      try {
        if (typeLower === 'int' || typeLower === 'integer') {
          const parsed = parseInt(value, 10)
          if (isNaN(parsed) || String(parsed) === 'NaN') {
            // Use default value if parsing fails
            const defaultValue = paramDesc && paramDesc.default_value !== undefined ? paramDesc.default_value : 0
            convertedValue = this.convertValueToType(defaultValue, paramType)
          } else {
            convertedValue = parsed
          }
        } else if (typeLower === 'float' || typeLower === 'double') {
          const parsed = parseFloat(value)
          if (isNaN(parsed) || String(parsed) === 'NaN') {
            // Use default value if parsing fails
            const defaultValue = paramDesc && paramDesc.default_value !== undefined ? paramDesc.default_value : 0.0
            convertedValue = this.convertValueToType(defaultValue, paramType)
          } else {
            convertedValue = parsed
          }
        } else if (typeLower === 'bool' || typeLower === 'boolean') {
          // For boolean, keep as is (checkbox handles it)
          convertedValue = Boolean(value)
        } else {
          // For string, keep as is
          convertedValue = String(value)
        }
      } catch (error) {
        console.error(`Failed to convert value for ${paramName}:`, error)
        // Use default value on error
        const defaultValue = paramDesc && paramDesc.default_value !== undefined ? paramDesc.default_value : ''
        convertedValue = this.convertValueToType(defaultValue, paramType)
      }
      
      this.parameterValues[paramName] = convertedValue
      this.saveParameterValues()
      // Emit change event for auto-save
      this.$emit('parameters-changed')
    }
  }
}
</script>

<style scoped>
.strategy-parameters {
  width: 100%;
  height: 100%;
  padding: var(--spacing-sm);
  background-color: var(--bg-primary);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  min-height: 150px;
}

.parameters-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--spacing-sm);
  flex-shrink: 0;
}

.parameters-header h3 {
  margin: 0;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
}

.btn-update {
  padding: var(--spacing-xs) var(--spacing-sm);
  font-size: var(--font-size-xs);
  background-color: var(--color-primary);
  color: var(--text-on-primary);
  border: none;
  border-radius: var(--border-radius);
  cursor: pointer;
  transition: background-color 0.2s;
}

.btn-update:hover:not(:disabled) {
  background-color: var(--color-primary-dark);
}

.btn-update:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.parameters-content {
  flex: 1;
  overflow: auto;
  width: 100%;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-muted);
  font-size: var(--font-size-sm);
}

.parameters-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-xs);
}

.parameters-table thead {
  position: sticky;
  top: 0;
  background-color: var(--bg-secondary);
  z-index: 1;
}

.parameters-table th {
  padding: var(--spacing-xs) var(--spacing-sm);
  text-align: left;
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  border-bottom: 1px solid var(--border-color);
}

.parameters-table td {
  padding: var(--spacing-xs) var(--spacing-sm);
  border-bottom: 1px solid var(--border-color);
  color: var(--text-primary);
}

.parameters-table tbody tr:hover {
  background-color: var(--bg-secondary);
}

.param-name {
  font-weight: var(--font-weight-medium);
  min-width: 120px;
}

.param-value {
  min-width: 100px;
}

.param-input {
  width: 100%;
  padding: var(--spacing-xs);
  font-size: var(--font-size-xs);
  background-color: var(--bg-primary);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--border-radius);
  box-sizing: border-box;
}

.param-input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}

.param-input::placeholder {
  color: var(--text-tertiary);
}

.param-description {
  color: var(--text-secondary);
  font-size: 11px;
}
</style>
