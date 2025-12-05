<template>
  <nav class="navbar">
    <div class="navbar-left">
      <div class="navbar-brand" @click="toggleMenu" :class="{ active: isMenuOpen }">
        R2D2
      </div>
      <div v-if="isMenuOpen" class="dropdown-menu" @click.stop>
        <router-link
          to="/trading"
          class="dropdown-menu-item"
          :class="{ active: $route.name === 'Trading' }"
          @click="closeMenu"
        >
          Trading
        </router-link>
        <router-link
          to="/backtesting"
          class="dropdown-menu-item"
          :class="{ active: $route.name === 'Backtesting' }"
          @click="closeMenu"
        >
          Backtesting
        </router-link>
      </div>
    </div>
    <div id="navbar-content-slot" class="navbar-right">
      <slot name="navbar-content"></slot>
    </div>
  </nav>
</template>

<script>
export default {
  name: 'NavBar',
  data() {
    return {
      isMenuOpen: false
    }
  },
  methods: {
    toggleMenu() {
      this.isMenuOpen = !this.isMenuOpen
    },
    closeMenu() {
      this.isMenuOpen = false
    },
    handleClickOutside(event) {
      if (!this.$el.contains(event.target)) {
        this.closeMenu()
      }
    }
  },
  watch: {
    $route() {
      // Close menu when route changes
      this.closeMenu()
    }
  },
  mounted() {
    // Close menu when clicking outside
    document.addEventListener('click', this.handleClickOutside)
  },
  beforeUnmount() {
    document.removeEventListener('click', this.handleClickOutside)
  }
}
</script>

<style scoped>
.navbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  height: var(--navbar-height);
  padding: 0 var(--spacing-xl);
  background-color: var(--bg-primary);
  border-bottom: 1px solid var(--border-color);
  box-shadow: var(--shadow-md);
  z-index: 100;
}

.navbar-left {
  display: flex;
  align-items: center;
  position: relative;
}

.navbar-brand {
  font-size: var(--font-size-2xl);
  font-weight: var(--font-weight-bold);
  color: var(--text-primary);
  cursor: pointer;
  user-select: none;
  padding: var(--spacing-sm);
  border-radius: var(--radius-md);
  transition: all var(--transition-base);
  position: relative;
}

.navbar-brand:hover {
  background-color: var(--bg-tertiary);
}

.navbar-brand.active {
  background-color: var(--color-primary-light);
  color: var(--color-primary);
}

.dropdown-menu {
  position: absolute;
  top: 100%;
  left: 0;
  margin-top: var(--spacing-sm);
  background-color: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  min-width: 150px;
  z-index: var(--z-dropdown);
  overflow: hidden;
}

.dropdown-menu-item {
  display: block;
  padding: var(--spacing-md) var(--spacing-lg);
  text-decoration: none;
  color: var(--text-secondary);
  font-weight: var(--font-weight-medium);
  transition: all var(--transition-base);
  border-bottom: 1px solid var(--bg-tertiary);
}

.dropdown-menu-item:last-child {
  border-bottom: none;
}

.dropdown-menu-item:hover {
  background-color: var(--bg-secondary);
  color: var(--text-primary);
}

.dropdown-menu-item.active {
  background-color: var(--color-primary-light);
  color: var(--color-primary);
}

.navbar-right {
  display: flex;
  align-items: center;
  flex: 1;
  gap: var(--spacing-lg);
}
</style>

