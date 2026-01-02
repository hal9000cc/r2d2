import { createRouter, createWebHistory } from 'vue-router'
import TradingView from '../views/TradingView.vue'
import BacktestingView from '../views/BacktestingView.vue'

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
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router

