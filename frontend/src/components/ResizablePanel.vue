<template>
  <div 
    class="resizable-panel"
    :class="{ 'is-resizing': isResizing }"
    :style="panelStyle"
  >
    <div 
      v-if="resizable"
      class="resize-handle"
      :class="[`resize-handle-${direction}`, `resize-handle-${effectiveHandleSide}`]"
      @mousedown="startResize"
    ></div>
    <div class="resizable-panel-content">
      <slot></slot>
    </div>
  </div>
</template>

<script>
export default {
  name: 'ResizablePanel',
  props: {
    direction: {
      type: String,
      default: 'horizontal', // 'horizontal' or 'vertical'
      validator: (value) => ['horizontal', 'vertical'].includes(value)
    },
    minSize: {
      type: Number,
      default: 100
    },
    maxSize: {
      type: Number,
      default: null
    },
    defaultSize: {
      type: Number,
      default: null
    },
    resizable: {
      type: Boolean,
      default: true
    },
    storageKey: {
      type: String,
      default: null
    },
    handleSide: {
      type: String,
      default: null, // 'left', 'right' for horizontal; 'top', 'bottom' for vertical
      validator: (value) => !value || ['left', 'right', 'top', 'bottom'].includes(value)
    }
  },
  data() {
    return {
      size: this.defaultSize || null,
      isResizing: false,
      startPos: 0,
      startSize: 0
    }
  },
  computed: {
    effectiveHandleSide() {
      if (this.handleSide) return this.handleSide
      // Default: right for horizontal, bottom for vertical
      return this.direction === 'horizontal' ? 'right' : 'bottom'
    },
    panelStyle() {
      if (!this.size) return {}
      
      if (this.direction === 'horizontal') {
        return {
          width: `${this.size}px`
        }
      } else {
        return {
          height: `${this.size}px`
        }
      }
    }
  },
  mounted() {
    // Load size from localStorage if storageKey is provided
    if (this.storageKey) {
      const savedSize = localStorage.getItem(this.storageKey)
      if (savedSize) {
        this.size = parseInt(savedSize, 10)
      } else if (this.defaultSize) {
        this.size = this.defaultSize
      }
    } else if (this.defaultSize) {
      this.size = this.defaultSize
    }
    
    // Add global event listeners
    document.addEventListener('mousemove', this.handleResize)
    document.addEventListener('mouseup', this.stopResize)
  },
  beforeUnmount() {
    // Remove global event listeners
    document.removeEventListener('mousemove', this.handleResize)
    document.removeEventListener('mouseup', this.stopResize)
  },
  methods: {
    startResize(e) {
      if (!this.resizable) return
      
      this.isResizing = true
      this.startPos = this.direction === 'horizontal' ? e.clientX : e.clientY
      this.startSize = this.size || 0
      
      e.preventDefault()
      document.body.style.cursor = this.direction === 'horizontal' ? 'col-resize' : 'row-resize'
      document.body.style.userSelect = 'none'
    },
    handleResize(e) {
      if (!this.isResizing) return
      
      const currentPos = this.direction === 'horizontal' ? e.clientX : e.clientY
      let delta = currentPos - this.startPos
      
      // If handle is on left or top, reverse the delta
      if (this.effectiveHandleSide === 'left' || this.effectiveHandleSide === 'top') {
        delta = -delta
      }
      
      let newSize = this.startSize + delta
      
      // Apply min/max constraints
      if (newSize < this.minSize) {
        newSize = this.minSize
      }
      if (this.maxSize !== null && newSize > this.maxSize) {
        newSize = this.maxSize
      }
      
      this.size = newSize
      
      // Save to localStorage if storageKey is provided
      if (this.storageKey) {
        localStorage.setItem(this.storageKey, newSize.toString())
      }
      
      this.$emit('resize', newSize)
    },
    stopResize() {
      if (!this.isResizing) return
      
      this.isResizing = false
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
  }
}
</script>

<style scoped>
.resizable-panel {
  position: relative;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  flex-shrink: 0;
}

.resizable-panel.is-resizing {
  user-select: none;
}

.resize-handle {
  position: absolute;
  z-index: 10;
  background-color: var(--border-color);
  opacity: 0.3;
  transition: background-color var(--transition-base), opacity var(--transition-base);
}

.resize-handle:hover {
  background-color: rgba(37, 99, 235, 0.3);
  opacity: 1;
}

.resize-handle-horizontal {
  top: 0;
  width: 8px;
  height: 100%;
  cursor: col-resize;
}

.resize-handle-horizontal.resize-handle-right {
  right: -4px;
}

.resize-handle-horizontal.resize-handle-left {
  left: -4px;
}

.resize-handle-vertical {
  left: 0;
  width: 100%;
  height: 8px;
  cursor: row-resize;
}

.resize-handle-vertical.resize-handle-bottom {
  bottom: -4px;
}

.resize-handle-vertical.resize-handle-top {
  top: -4px;
}

.resizable-panel-content {
  flex: 1;
  overflow: auto;
  width: 100%;
  height: 100%;
}
</style>

