<template>
  <div ref="editorContainer" class="codemirror-editor-container"></div>
</template>

<script>
import { EditorView, lineNumbers, keymap } from '@codemirror/view'
import { EditorState } from '@codemirror/state'
import { indentUnit } from '@codemirror/language'
import { python } from '@codemirror/lang-python'
import { oneDark } from '@codemirror/theme-one-dark'
import { indentWithTab } from '@codemirror/commands'

export default {
  name: 'CodeMirrorEditor',
  props: {
    modelValue: {
      type: String,
      default: ''
    },
    language: {
      type: String,
      default: 'python'
    },
    disabled: {
      type: Boolean,
      default: false
    }
  },
  emits: ['update:modelValue'],
  data() {
    return {
      view: null
    }
  },
  mounted() {
    this.$nextTick(() => {
      this.initEditor()
    })
  },
  beforeUnmount() {
    if (this.view) {
      this.view.destroy()
    }
  },
  watch: {
    modelValue(newValue) {
      if (this.view) {
        const currentValue = this.view.state.doc.toString()
        if (currentValue !== newValue) {
          this.view.dispatch({
            changes: {
              from: 0,
              to: this.view.state.doc.length,
              insert: newValue || ''
            }
          })
        }
      }
    },
    disabled(newValue) {
      if (this.view) {
        // Update readOnly via setState
        const currentDoc = this.view.state.doc.toString()
        const newState = EditorState.create({
          doc: currentDoc,
          extensions: [
            lineNumbers(),
            python(),
            oneDark,
            EditorState.tabSize.of(4), // Set tab size to 4 spaces
            indentUnit.of('    '), // Set indent unit to 4 spaces (string, not number)
            keymap.of([indentWithTab]),
            EditorState.readOnly.of(newValue),
            EditorView.updateListener.of((update) => {
              if (update.docChanged && !newValue) {
                const value = update.state.doc.toString()
                this.$emit('update:modelValue', value)
              }
            })
          ]
        })
        this.view.setState(newState)
      }
    }
  },
  methods: {
    initEditor() {
      if (!this.$refs.editorContainer) {
        return
      }

      try {
        // Create editor state
        const extensions = [
          lineNumbers(),
          python(),
          oneDark,
          EditorState.tabSize.of(4), // Set tab size to 4 spaces
          indentUnit.of('    '), // Set indent unit to 4 spaces (string, not number)
          keymap.of([indentWithTab]), // Handle Tab for indentation
          EditorState.readOnly.of(this.disabled), // Disable editing
          EditorView.updateListener.of((update) => {
            if (update.docChanged && !this.disabled) {
              const value = update.state.doc.toString()
              this.$emit('update:modelValue', value)
            }
          })
        ]

        const state = EditorState.create({
          doc: this.modelValue || '',
          extensions
        })

        // Create view
        this.view = new EditorView({
          state,
          parent: this.$refs.editorContainer
        })
        
      } catch (error) {
        console.error('Failed to initialize CodeMirror Editor:', error)
        console.error('Error details:', error.message, error.stack)
      }
    }
  }
}
</script>

<style scoped>
.codemirror-editor-container {
  width: 100%;
  height: 100%;
  min-height: 200px;
  overflow: hidden;
  position: relative;
}

:deep(.cm-editor) {
  height: 100%;
  width: 100%;
  display: block;
}

:deep(.cm-editor.cm-readOnly) {
  opacity: 0.6;
  cursor: not-allowed;
}

:deep(.cm-scroller) {
  height: 100%;
  width: 100%;
  overflow: auto;
}

:deep(.cm-content) {
  min-height: 100%;
  padding: 8px;
}

:deep(.cm-gutters) {
  min-height: 100%;
}
</style>

