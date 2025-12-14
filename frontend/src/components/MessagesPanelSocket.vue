<template>
  <MessagesPanel :messages="messages" />
</template>

<script>
import MessagesPanel from './MessagesPanel.vue'

export default {
  name: 'MessagesPanelSocket',
  components: {
    MessagesPanel
  },
  data() {
    return {
      messages: []
    }
  }
}
</script>
