<template>
  <div class="data-table-container">
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
          :class="getRowClass(row)"
        >
          <td v-for="column in columns" :key="column.key" :class="getCellClass(column, row)">
            {{ formatCell(row[column.key], column) }}
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
    }
  },
  methods: {
    getRowKey(row, index) {
      return row[this.rowKey] || index
    },
    formatCell(value, column) {
      if (column.format && typeof column.format === 'function') {
        return column.format(value)
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
    getRowClass(row) {
      if (this.rowClass) {
        if (typeof this.rowClass === 'function') {
          return this.rowClass(row)
        }
        return this.rowClass
      }
      return ''
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

/* Override hover for colored rows to maintain visibility */
.data-table tbody tr.row-buy:hover,
.data-table tbody tr.row-sell:hover,
.data-table tbody tr.row-type-long:hover,
.data-table tbody tr.row-type-short:hover {
  background-color: var(--bg-hover);
  opacity: 0.8;
}
</style>

