import { ref, computed } from 'vue'

/**
 * Composable for managing backtesting results (trades and deals)
 * 
 * @returns {Object} Results state and methods
 */
export function useBacktestingResults() {
  // Result ID for current backtesting run
  const resultId = ref(null)
  
  // Time of last results update (ISO string)
  const resultsRelevanceTime = ref(null)
  
  // Trades array (trades never change once added)
  const trades = ref([])
  
  // Deals Map (deals can be updated)
  const deals = ref(new Map())
  
  /**
   * Clear all results data
   */
  function clearResults() {
    resultId.value = null
    resultsRelevanceTime.value = null
    trades.value = []
    deals.value = new Map()
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
   */
  function addTrades(newTrades) {
    if (!newTrades || newTrades.length === 0) {
      return
    }
    
    // Create a Set of existing trade IDs for fast lookup
    const existingTradeIds = new Set(trades.value.map(t => t.trade_id))
    
    // Filter out duplicates
    const uniqueTrades = newTrades.filter(trade => !existingTradeIds.has(trade.trade_id))
    
    // Add unique trades
    if (uniqueTrades.length > 0) {
      trades.value = [...trades.value, ...uniqueTrades]
    }
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
   * Get trades within a date range
   * @param {string} fromISO - Start date (ISO string)
   * @param {string} toISO - End date (ISO string)
   * @returns {Array} Filtered trades
   */
  function getTradesByDateRange(fromISO, toISO) {
    if (!fromISO || !toISO) {
      return trades.value
    }
    
    const fromTime = new Date(fromISO).getTime()
    const toTime = new Date(toISO).getTime()
    
    return trades.value.filter(trade => {
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
  
  // Computed properties
  const tradesCount = computed(() => trades.value.length)
  const dealsCount = computed(() => deals.value.size)
  
  return {
    // State
    resultId,
    resultsRelevanceTime,
    trades,
    deals,
    
    // Computed
    tradesCount,
    dealsCount,
    
    // Methods
    clearResults,
    setResultId,
    setRelevanceTime,
    addTrades,
    updateDeals,
    getTradesByDateRange,
    getDealsByIds,
    getAllDeals
  }
}

