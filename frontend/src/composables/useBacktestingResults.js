import { ref, computed } from 'vue'

/**
 * Composable for managing backtesting results (trades, deals, and orders)
 * 
 * @returns {Object} Results state and methods
 */
export function useBacktestingResults() {
  // Result ID for current backtesting run
  const resultId = ref(null)
  
  // Time of last results update (ISO string)
  const resultsRelevanceTime = ref(null)
  
  // Trades Map (trades never change once added)
  const trades = ref(new Map())
  
  // Deals Map (deals can be updated)
  const deals = ref(new Map())
  
  // Orders Map (orders can be updated)
  const orders = ref(new Map())
  
  // Index: trades by deal_id for fast lookup
  const tradesByDealId = ref(new Map())
  
  // Statistics (updated on each progress event)
  const stats = ref(null)
  
  /**
   * Clear all results data
   */
  function clearResults() {
    resultId.value = null
    resultsRelevanceTime.value = null
    trades.value = new Map()
    deals.value = new Map()
    orders.value = new Map()
    tradesByDealId.value = new Map()
    stats.value = null
  }
  
  /**
   * Set result ID for current backtesting run
   * @param {string} id - Result ID (UUID)
   */
  function setResultId(id) {
    resultId.value = id
  }
  
  /**
   * Set results relevance time
   * @param {string} time - ISO timestamp
   */
  function setRelevanceTime(time) {
    resultsRelevanceTime.value = time
  }
  
  /**
   * Add new trades (avoid duplicates by trade_id)
   * @param {Array} newTrades - Array of trade objects
   * @returns {Array} Array of actually added trades (after filtering duplicates)
   */
  function addTrades(newTrades) {
    if (!newTrades || newTrades.length === 0) {
      return []
    }
    
    // Filter out duplicates and add unique trades to Map
    const uniqueTrades = []
    newTrades.forEach(trade => {
      const tradeIdStr = String(trade.trade_id)
      if (!trades.value.has(tradeIdStr)) {
        trades.value.set(tradeIdStr, trade)
        uniqueTrades.push(trade)
      }
    })
    
    // Update tradesByDealId index
    if (uniqueTrades.length > 0) {
      uniqueTrades.forEach(trade => {
        const dealId = trade.deal_id
        if (!tradesByDealId.value.has(dealId)) {
          tradesByDealId.value.set(dealId, new Set())
        }
        tradesByDealId.value.get(dealId).add(trade)
      })
      
      // Trigger reactivity by creating new Maps
      trades.value = new Map(trades.value)
      tradesByDealId.value = new Map(tradesByDealId.value)
    }
    
    return uniqueTrades
  }
  
  /**
   * Update deals (add new or update existing by deal_id)
   * @param {Array} newDeals - Array of deal objects
   */
  function updateDeals(newDeals) {
    if (!newDeals || newDeals.length === 0) {
      return
    }
    
    // Update or add each deal in the Map
    newDeals.forEach(deal => {
      deals.value.set(deal.deal_id, deal)
    })
    
    // Trigger reactivity by creating a new Map
    deals.value = new Map(deals.value)
  }
  
  /**
   * Update statistics
   * @param {Object} newStats - Statistics object
   */
  function updateStats(newStats) {
    if (!newStats) {
      return
    }
    
    stats.value = { ...newStats }
  }
  
  /**
   * Get trades within a date range
   * @param {string} fromISO - Start date (ISO string)
   * @param {string} toISO - End date (ISO string)
   * @returns {Array} Filtered trades
   */
  function getTradesByDateRange(fromISO, toISO) {
    const allTrades = Array.from(trades.value.values())
    
    if (!fromISO || !toISO) {
      return allTrades
    }
    
    const fromTime = new Date(fromISO).getTime()
    const toTime = new Date(toISO).getTime()
    
    return allTrades.filter(trade => {
      const tradeTime = new Date(trade.time).getTime()
      return tradeTime >= fromTime && tradeTime <= toTime
    })
  }
  
  /**
   * Get deals by their IDs (useful for getting deals related to trades in a date range)
   * @param {Array<string>} dealIds - Array of deal IDs
   * @returns {Array} Deals array
   */
  function getDealsByIds(dealIds) {
    if (!dealIds || dealIds.length === 0) {
      return []
    }
    
    return dealIds
      .map(dealId => deals.value.get(dealId))
      .filter(deal => deal !== undefined)
  }
  
  /**
   * Get all deals as array
   * @returns {Array} All deals
   */
  function getAllDeals() {
    return Array.from(deals.value.values())
  }
  
  /**
   * Get trades for a specific deal
   * @param {string} dealId - Deal ID
   * @returns {Array} Trades for this deal, sorted by time
   */
  function getTradesForDeal(dealId) {
    const dealTradesSet = tradesByDealId.value.get(dealId)
    if (!dealTradesSet || dealTradesSet.size === 0) {
      return []
    }
    // Convert Set to Array and sort by time (ascending)
    const dealTrades = Array.from(dealTradesSet)
    return dealTrades.sort((a, b) => {
      const timeA = new Date(a.time).getTime()
      const timeB = new Date(b.time).getTime()
      return timeA - timeB
    })
  }
  
  /**
   * Get trade by ID
   * @param {string|number} tradeId - Trade ID
   * @returns {Object|null} Trade object or null if not found
   */
  function getTradeById(tradeId) {
    if (!tradeId) {
      return null
    }
    // Convert tradeId to string for comparison (trade_id might be string or number)
    const tradeIdStr = String(tradeId)
    return trades.value.get(tradeIdStr) || null
  }
  
  /**
   * Get all trades as array
   * @returns {Array} All trades
   */
  function getAllTrades() {
    return Array.from(trades.value.values())
  }
  
  /**
   * Update orders (add new or update existing by order_id)
   * @param {Array} newOrders - Array of order objects
   */
  function updateOrders(newOrders) {
    if (!newOrders || newOrders.length === 0) {
      return
    }
    
    // Update or add each order in the Map
    newOrders.forEach(order => {
      const orderIdStr = String(order.order_id)
      orders.value.set(orderIdStr, order)
    })
    
    // Trigger reactivity by creating a new Map
    orders.value = new Map(orders.value)
  }
  
  /**
   * Get all orders as array
   * @returns {Array} All orders
   */
  function getAllOrders() {
    return Array.from(orders.value.values())
  }
  
  /**
   * Get orders within a date range (by modify_time)
   * @param {string} fromISO - Start date (ISO string)
   * @param {string} toISO - End date (ISO string)
   * @returns {Array} Filtered orders
   */
  function getOrdersByDateRange(fromISO, toISO) {
    const allOrders = Array.from(orders.value.values())
    
    if (!fromISO || !toISO) {
      return allOrders
    }
    
    const fromTime = new Date(fromISO).getTime()
    const toTime = new Date(toISO).getTime()
    
    return allOrders.filter(order => {
      const modifyTime = new Date(order.modify_time).getTime()
      return modifyTime >= fromTime && modifyTime <= toTime
    })
  }
  
  /**
   * Get order by ID
   * @param {string|number} orderId - Order ID
   * @returns {Object|null} Order object or null if not found
   */
  function getOrderById(orderId) {
    if (!orderId) {
      return null
    }
    const orderIdStr = String(orderId)
    return orders.value.get(orderIdStr) || null
  }
  
  // Computed properties
  const tradesCount = computed(() => trades.value.size)
  const dealsCount = computed(() => deals.value.size)
  const ordersCount = computed(() => orders.value.size)
  const allTrades = computed(() => Array.from(trades.value.values()))
  
  return {
    // State
    resultId,
    resultsRelevanceTime,
    trades,
    deals,
    orders,
    tradesByDealId,
    stats,
    
    // Computed
    tradesCount,
    dealsCount,
    ordersCount,
    allTrades,
    
    // Methods
    clearResults,
    setResultId,
    setRelevanceTime,
    addTrades,
    updateDeals,
    updateOrders,
    updateStats,
    getTradesByDateRange,
    getDealsByIds,
    getAllDeals,
    getTradesForDeal,
    getTradeById,
    getAllTrades,
    getAllOrders,
    getOrdersByDateRange,
    getOrderById
  }
}

