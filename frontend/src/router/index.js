import { createRouter, createWebHistory } from 'vue-router'
import TradingView from '../views/TradingView.vue'
import BacktestingView from '../views/BacktestingView.vue'
import SettingsView from '../views/SettingsView.vue'

const routes = [
  {
    path: '/',
    redirect: '/trading'
  },
  {
    path: '/trading',
    name: 'Trading',
    component: TradingView
  },
  {
    path: '/backtesting',
    name: 'Backtesting',
    component: BacktestingView
  },
  {
    path: '/settings',
    name: 'Settings',
    component: SettingsView
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router

