# Alert System Documentation

## Overview

A global alert/toast notification system for displaying temporary messages to users.

## Components

- **`useAlert.js`** - Composable for managing alerts
- **`AlertContainer.vue`** - UI component for displaying alerts
- **`AppLayout.vue`** - Includes AlertContainer globally

## Usage

### Import and Initialize

```javascript
import { useAlert } from '@/composables/useAlert'

const { showAlert, success, error, warning, info } = useAlert()
```

### Show Alerts

#### Using shortcuts (recommended)
```javascript
// Success (auto-dismiss in 3s)
success('Strategy saved successfully')

// Error (auto-dismiss in 5s)
error('Failed to load chart data')

// Warning (auto-dismiss in 4s)
warning('Connection unstable')

// Info (auto-dismiss in 3s)
info('Loading data...')
```

#### Using generic method
```javascript
// Custom duration
showAlert('success', 'Operation completed', 2000)

// No auto-dismiss (duration = 0)
showAlert('error', 'Critical error', 0)
```

### Alert Types

- `success` - Green, for successful operations
- `error` - Red, for errors and failures
- `warning` - Orange, for warnings
- `info` - Blue, for informational messages

### Methods

- `showAlert(type, message, duration)` - Show an alert
- `removeAlert(id)` - Remove specific alert by ID
- `clearAllAlerts()` - Clear all alerts
- `success(message, duration)` - Shortcut for success alert
- `error(message, duration)` - Shortcut for error alert
- `warning(message, duration)` - Shortcut for warning alert
- `info(message, duration)` - Shortcut for info alert

## Features

- Auto-dismiss with configurable duration
- Click to dismiss
- Stacking multiple alerts
- Smooth animations
- Responsive design
- Icon for each alert type
- Close button

## Example

```javascript
<script setup>
import { useAlert } from '@/composables/useAlert'

const { error, success } = useAlert()

function handleSave() {
  try {
    // Save logic...
    success('Data saved successfully')
  } catch (err) {
    error('Failed to save data: ' + err.message)
  }
}
</script>
```

