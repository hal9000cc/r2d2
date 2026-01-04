<template>
  <div 
    ref="tableContainer"
    class="data-table-container"
    @click="handleContainerClick"
  >
    <div v-if="data.length === 0" class="empty-state">
      <p>{{ emptyMessage }}</p>
    </div>
    <table v-else class="data-table">
      <thead>
        <tr>
          <th 
            v-for="column in columns" 
            :key="column.key" 
            :style="column.width ? { width: column.width } : {}"
            :class="getHeaderClass(column)"
          >
            {{ column.label }}
          </th>
        </tr>
      </thead>
      <tbody>
        <tr 
          v-for="(row, index) in data" 
          :key="getRowKey(row, index)"
          :ref="el => setRowRef(el, index)"
          :class="getRowClass(row, index)"
          @click.stop="handleRowClick(row, index)"
        >
          <td v-for="column in columns" :key="column.key" :class="getCellClass(column, row)">
            {{ formatCell(row[column.key], column, row) }}
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script>
export default {
  name: 'DataTable',
  props: {
    columns: {
      type: Array,
      required: true,
      // Array of { key: string, label: string, width?: string, format?: function, class?: string|function }
    },
    data: {
      type: Array,
      required: true
    },
    rowKey: {
      type: String,
      default: 'id'
    },
    emptyMessage: {
      type: String,
      default: 'No data available'
    },
    rowClass: {
      type: [String, Function],
      default: null
      // Function that receives (row) and returns class string, or static class string
    },
    onRowSelected: {
      type: Function,
      default: null
      // Function that receives (rowKey) when a row is selected
    },
    enabled: {
      type: Boolean,
      default: true
      // Whether keyboard navigation is enabled (for active tab only)
    }
  },
  data() {
    return {
      selectedRowKey: null,
      rowRefs: []
    }
  },
  watch: {
    data() {
      // Reset selection when data changes
      this.selectedRowKey = null
      this.rowRefs = []
    },
    enabled(newValue) {
      // If disabled, clear selection
      if (!newValue) {
        this.selectedRowKey = null
      }
    }
  },
  methods: {
    getRowKey(row, index) {
      return row[this.rowKey] || index
    },
    formatCell(value, column, row) {
      if (column.format && typeof column.format === 'function') {
        // Pass row as second parameter for computed columns
        return column.format(value, row)
      }
      
      // Default formatting
      if (value === null || value === undefined || value === '') {
        return '—'
      }
      
      return value
    },
    getCellClass(column, row) {
      if (column.class) {
        if (typeof column.class === 'function') {
          return column.class(row)
        }
        return column.class
      }
      return ''
    },
    getHeaderClass(column) {
      // Apply alignment class to header if column has one
      // For alignment classes (align-right, align-center), apply to header too
      if (column.class) {
        if (typeof column.class === 'string') {
          // If it's a string class (like 'align-right'), apply it to header
          if (column.class === 'align-right' || column.class === 'align-center') {
            return column.class
          }
        }
        // For function-based classes, we can't determine alignment, so return empty
        // But we can check if there's a headerClass property
      }
      // Check if column has explicit headerClass
      if (column.headerClass) {
        return column.headerClass
      }
      return ''
    },
    getRowClass(row, index) {
      const classes = []
      
      // Add custom row class
      if (this.rowClass) {
        if (typeof this.rowClass === 'function') {
          const customClass = this.rowClass(row)
          if (customClass) {
            classes.push(customClass)
          }
        } else {
          classes.push(this.rowClass)
        }
      }
      
      // Add selected class
      const rowKey = this.getRowKey(row, index)
      if (this.selectedRowKey === rowKey) {
        classes.push('row-selected')
      }
      
      return classes.join(' ')
    },
    setRowRef(el, index) {
      if (el) {
        this.rowRefs[index] = el
      }
    },
    handleRowClick(row, index) {
      if (!this.enabled) return
      
      const rowKey = this.getRowKey(row, index)
      this.selectRow(rowKey)
    },
    handleContainerClick(event) {
      // If clicking on container but not on a row, deselect
      if (event.target === this.$refs.tableContainer || event.target.closest('thead')) {
        if (this.enabled) {
          this.selectedRowKey = null
        }
      }
    },
    handleKeyDown(event) {
      // This method is kept for backward compatibility but navigation
      // is now handled at the window level in BacktestingView
      // Only handle Escape here if container has focus
      if (!this.enabled) return
      
      // Ignore if focus is in input or textarea
      if (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA') {
        return
      }
      
      // Handle Escape to deselect
      if (event.key === 'Escape') {
        event.preventDefault()
        this.deselect()
        return
      }
    },
    selectRow(rowKey) {
      if (this.selectedRowKey === rowKey) return
      
      this.selectedRowKey = rowKey
      
      // Scroll to selected row
      this.$nextTick(() => {
        this.scrollToSelectedRow()
      })
      
      // Call callback
      if (this.onRowSelected && typeof this.onRowSelected === 'function') {
        this.onRowSelected(rowKey)
      }
    },
    scrollToSelectedRow() {
      if (this.selectedRowKey === null) return
      
      const index = this.data.findIndex((row, idx) => this.getRowKey(row, idx) === this.selectedRowKey)
      if (index === -1) return
      
      const rowElement = this.rowRefs[index]
      if (!rowElement) return
      
      const container = this.$refs.tableContainer
      if (!container) return
      
      // Get thead element to calculate header height
      const thead = container.querySelector('thead')
      const headerHeight = thead ? thead.offsetHeight : 0
      
      // For first row, always scroll to top
      if (index === 0) {
        container.scrollTo({
          top: 0,
          behavior: 'auto'
        })
        return
      }
      
      // Get positions relative to container
      const containerRect = container.getBoundingClientRect()
      const rowRect = rowElement.getBoundingClientRect()
      
      // Calculate visible area (accounting for sticky header)
      const visibleTop = containerRect.top + headerHeight
      const visibleBottom = containerRect.bottom
      
      // Check if row is visible in the viewport (considering header)
      const isAbove = rowRect.top < visibleTop
      const isBelow = rowRect.bottom > visibleBottom
      
      if (isAbove) {
        // Row is above visible area - scroll up
        // Calculate target scroll position to place row at top of visible area (below header)
        const rowOffsetTop = rowElement.offsetTop
        const targetScrollTop = rowOffsetTop - headerHeight
        
        container.scrollTo({
          top: targetScrollTop,
          behavior: 'auto'
        })
      } else if (isBelow) {
        // Row is below visible area - scroll down
        // Calculate target scroll position to place row at bottom of visible area
        const rowOffsetTop = rowElement.offsetTop
        const rowHeight = rowElement.offsetHeight
        const containerHeight = container.clientHeight
        const targetScrollTop = rowOffsetTop - containerHeight + rowHeight
        
        container.scrollTo({
          top: targetScrollTop,
          behavior: 'auto'
        })
      }
      // If row is already visible, do nothing
    },
    // Public methods for external navigation
    navigateUp() {
      if (!this.enabled || this.data.length === 0) return
      
      let currentIndex = -1
      if (this.selectedRowKey !== null) {
        currentIndex = this.data.findIndex((row, index) => this.getRowKey(row, index) === this.selectedRowKey)
      }
      
      let newIndex = currentIndex === -1 ? this.data.length - 1 : Math.max(0, currentIndex - 1)
      
      if (newIndex >= 0 && newIndex < this.data.length) {
        const row = this.data[newIndex]
        const rowKey = this.getRowKey(row, newIndex)
        this.selectRow(rowKey)
      }
    },
    navigateDown() {
      if (!this.enabled || this.data.length === 0) return
      
      let currentIndex = -1
      if (this.selectedRowKey !== null) {
        currentIndex = this.data.findIndex((row, index) => this.getRowKey(row, index) === this.selectedRowKey)
      }
      
      let newIndex = currentIndex === -1 ? 0 : Math.min(this.data.length - 1, currentIndex + 1)
      
      if (newIndex >= 0 && newIndex < this.data.length) {
        const row = this.data[newIndex]
        const rowKey = this.getRowKey(row, newIndex)
        this.selectRow(rowKey)
      }
    },
    navigatePageUp() {
      if (!this.enabled || this.data.length === 0) return
      
      let currentIndex = -1
      if (this.selectedRowKey !== null) {
        currentIndex = this.data.findIndex((row, index) => this.getRowKey(row, index) === this.selectedRowKey)
      }
      
      let newIndex = currentIndex === -1 ? this.data.length - 1 : currentIndex
      
      const container = this.$refs.tableContainer
      if (container) {
        const rowHeight = 30
        const visibleRows = Math.floor(container.clientHeight / rowHeight)
        newIndex = Math.max(0, newIndex - visibleRows + 1)
      } else {
        newIndex = Math.max(0, newIndex - 10)
      }
      
      if (newIndex >= 0 && newIndex < this.data.length) {
        const row = this.data[newIndex]
        const rowKey = this.getRowKey(row, newIndex)
        this.selectRow(rowKey)
      }
    },
    navigatePageDown() {
      if (!this.enabled || this.data.length === 0) return
      
      let currentIndex = -1
      if (this.selectedRowKey !== null) {
        currentIndex = this.data.findIndex((row, index) => this.getRowKey(row, index) === this.selectedRowKey)
      }
      
      let newIndex = currentIndex === -1 ? 0 : currentIndex
      
      const container = this.$refs.tableContainer
      if (container) {
        const rowHeight = 30
        const visibleRows = Math.floor(container.clientHeight / rowHeight)
        newIndex = Math.min(this.data.length - 1, newIndex + visibleRows - 1)
      } else {
        newIndex = Math.min(this.data.length - 1, newIndex + 10)
      }
      
      if (newIndex >= 0 && newIndex < this.data.length) {
        const row = this.data[newIndex]
        const rowKey = this.getRowKey(row, newIndex)
        this.selectRow(rowKey)
      }
    },
    navigateHome() {
      if (!this.enabled || this.data.length === 0) return
      
      const row = this.data[0]
      const rowKey = this.getRowKey(row, 0)
      this.selectRow(rowKey)
    },
    navigateEnd() {
      if (!this.enabled || this.data.length === 0) return
      
      const lastIndex = this.data.length - 1
      const row = this.data[lastIndex]
      const rowKey = this.getRowKey(row, lastIndex)
      this.selectRow(rowKey)
    },
    deselect() {
      if (!this.enabled) return
      this.selectedRowKey = null
    }
  }
}
</script>

<style scoped>
.data-table-container {
  width: 100%;
  height: 100%;
  overflow: auto;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-muted);
  font-size: var(--font-size-sm);
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-xs);
}

.data-table thead {
  position: sticky;
  top: 0;
  background-color: var(--bg-secondary);
  z-index: 1;
}

.data-table th {
  padding: var(--spacing-xs) var(--spacing-sm);
  text-align: left;
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  border-bottom: 1px solid var(--border-color);
  white-space: nowrap;
}

.data-table td {
  padding: var(--spacing-xs) var(--spacing-sm);
  border-bottom: 1px solid var(--border-color);
  color: var(--text-primary);
}

.data-table tbody tr:hover {
  background-color: var(--bg-secondary);
}

/* Cell alignment classes */
.data-table td.align-right,
.data-table th.align-right {
  text-align: right;
}

.data-table td.align-center,
.data-table th.align-center {
  text-align: center;
}

/* Side-specific styling */
.data-table td.side-buy {
  color: var(--color-success);
  font-weight: var(--font-weight-medium);
}

.data-table td.side-sell {
  color: var(--color-danger);
  font-weight: var(--font-weight-medium);
}

/* Status-specific styling */
.data-table td.status-closed {
  color: var(--color-success);
}

.data-table td.status-open {
  color: var(--color-info);
}

/* Row background coloring */
.data-table tbody tr.row-buy {
  background-color: var(--color-success-lighter);
}

.data-table tbody tr.row-sell {
  background-color: var(--color-danger-lighter);
}

.data-table tbody tr.row-type-long {
  background-color: var(--color-success-lighter);
}

.data-table tbody tr.row-type-short {
  background-color: var(--color-danger-lighter);
}

.data-table tbody tr.row-inactive {
  background-color: var(--bg-tertiary);
  opacity: 0.6;
}

/* Override hover for colored rows to maintain visibility */
.data-table tbody tr.row-buy:hover,
.data-table tbody tr.row-sell:hover,
.data-table tbody tr.row-type-long:hover,
.data-table tbody tr.row-type-short:hover {
  background-color: var(--bg-hover);
  opacity: 0.8;
}

.data-table tbody tr.row-inactive:hover {
  background-color: var(--bg-hover);
  opacity: 0.7;
}

/* Selected row styling */
.data-table tbody tr.row-selected {
  background-color: var(--color-primary, #007bff) !important;
  color: var(--color-on-primary, #ffffff) !important;
}

.data-table tbody tr.row-selected:hover {
  background-color: var(--color-primary-dark, #0056b3) !important;
}

/* Override colored row styles when selected */
.data-table tbody tr.row-selected.row-buy,
.data-table tbody tr.row-selected.row-sell,
.data-table tbody tr.row-selected.row-type-long,
.data-table tbody tr.row-selected.row-type-short,
.data-table tbody tr.row-selected.row-inactive {
  background-color: var(--color-primary, #007bff) !important;
  color: var(--color-on-primary, #ffffff) !important;
}

/* Make container focusable for keyboard navigation */
.data-table-container:focus {
  outline: none;
}
</style>

