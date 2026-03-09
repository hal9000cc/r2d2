<template>
  <div class="errors-panel">
    <div v-if="errors.length === 0" class="empty-state">
      No errors recorded
    </div>
    <div v-else class="errors-table-wrapper">
      <table class="errors-table">
        <thead>
          <tr>
            <th class="col-id">ID</th>
            <th class="col-level">Level</th>
            <th class="col-category">Category</th>
            <th class="col-time">Timestamp</th>
            <th class="col-broker-time">Broker Time</th>
            <th class="col-message">Message</th>
            <th class="col-ref">Deal</th>
            <th class="col-ref">Order</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="error in errors"
            :key="error.id"
            :class="rowClass(error)"
          >
            <td class="col-id">{{ error.id }}</td>
            <td class="col-level">
              <span :class="levelBadgeClass(error.level)">{{ error.level }}</span>
            </td>
            <td class="col-category">{{ error.category }}</td>
            <td class="col-time">{{ formatTime(error.timestamp) }}</td>
            <td class="col-broker-time">{{ formatTime(error.broker_time) }}</td>
            <td class="col-message">{{ error.message }}</td>
            <td class="col-ref">{{ error.deal_id ?? '—' }}</td>
            <td class="col-ref">{{ error.order_id ?? '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script>
export default {
  name: 'ErrorsPanel',
  props: {
    errors: {
      type: Array,
      default: () => []
    }
  },
  methods: {
    formatTime(value) {
      if (!value) return '—'
      try {
        const date = new Date(value)
        if (isNaN(date.getTime())) return value
        return date.toISOString().replace('T', ' ').substring(0, 19)
      } catch {
        return value
      }
    },
    rowClass(error) {
      if (error.level === 'critical') return 'row-critical'
      if (error.level === 'error') return 'row-error'
      return ''
    },
    levelBadgeClass(level) {
      if (level === 'critical') return 'badge badge-critical'
      if (level === 'error') return 'badge badge-error'
      return 'badge'
    }
  }
}
</script>

<style scoped>
.errors-panel {
  width: 100%;
  height: 100%;
  overflow: auto;
  background-color: var(--bg-primary);
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 60px;
  color: var(--text-muted);
  font-size: var(--font-size-sm);
}

.errors-table-wrapper {
  width: 100%;
  height: 100%;
  overflow: auto;
}

.errors-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-xs);
  table-layout: fixed;
}

.errors-table th {
  position: sticky;
  top: 0;
  background-color: var(--bg-secondary);
  color: var(--text-secondary);
  font-weight: var(--font-weight-semibold);
  padding: var(--spacing-xs) var(--spacing-sm);
  text-align: left;
  border-bottom: 1px solid var(--border-color);
  white-space: nowrap;
  z-index: 1;
}

.errors-table td {
  padding: var(--spacing-xs) var(--spacing-sm);
  border-bottom: 1px solid var(--border-color-light, var(--border-color));
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Column widths */
.col-id     { width: 48px; text-align: right; }
.col-level  { width: 72px; }
.col-category { width: 110px; }
.col-time   { width: 140px; }
.col-broker-time { width: 140px; }
.col-message { width: auto; white-space: normal; word-break: break-word; }
.col-ref    { width: 60px; text-align: right; }

/* Row coloring */
.row-error td {
  background-color: rgba(239, 68, 68, 0.08);
}

.row-critical td {
  background-color: rgba(239, 68, 68, 0.2);
}

.row-error:hover td {
  background-color: rgba(239, 68, 68, 0.14);
}

.row-critical:hover td {
  background-color: rgba(239, 68, 68, 0.28);
}

/* Level badges */
.badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: var(--font-weight-semibold);
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.badge-error {
  background-color: rgba(239, 68, 68, 0.15);
  color: #ef4444;
  border: 1px solid rgba(239, 68, 68, 0.3);
}

.badge-critical {
  background-color: rgba(239, 68, 68, 0.3);
  color: #dc2626;
  border: 1px solid rgba(239, 68, 68, 0.5);
}
</style>
