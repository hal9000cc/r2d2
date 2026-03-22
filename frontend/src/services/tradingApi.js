import axios from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8202'

export const tradingApi = {
  /**
   * Get all trading tasks with group metadata.
   * @returns {Promise<{tasks: Array, groups: Object}>}
   */
  async getTasks() {
    const response = await axios.get(`${API_BASE_URL}/api/v1/trading/tasks`)
    return response.data
  },

  /**
   * Delete a trading task.
   * @param {number} taskId
   */
  async deleteTask(taskId) {
    const response = await axios.delete(`${API_BASE_URL}/api/v1/trading/tasks/${taskId}`)
    return response.data
  },

  /**
   * Clone a backtesting task into a new trading task.
   * @param {number} backtestingTaskId - Source backtesting task ID
   * @returns {Promise<Object>} Created trading task
   */
  async cloneFromBacktesting(backtestingTaskId) {
    const response = await axios.post(
      `${API_BASE_URL}/api/v1/trading/tasks/clone/${backtestingTaskId}`
    )
    return response.data
  },

  /**
   * Update editable fields of a trading task.
   * @param {number} taskId
   * @param {{source?: string, symbol?: string, timeframe?: string}} data
   * @returns {Promise<Object>} Updated trading task
   */
  async updateTask(taskId, data) {
    const response = await axios.patch(`${API_BASE_URL}/api/v1/trading/tasks/${taskId}`, data)
    return response.data
  },

  /**
   * Start a live trading task.
   * Sets isRunning=True and generates a result_id.
   * @param {number} taskId
   * @returns {Promise<{success: boolean, task_id: number, result_id: string}>}
   */
  async startTask(taskId) {
    const response = await axios.post(`${API_BASE_URL}/api/v1/trading/tasks/${taskId}/start`)
    return response.data
  },

  /**
   * Stop a live trading task.
   * @param {number} taskId
   * @param {boolean} closeDealsOnStop - Whether to close open deals before stopping
   * @returns {Promise<{success: boolean, task_id: number, message: string}>}
   */
  async stopTask(taskId, closeDealsOnStop = false) {
    const response = await axios.post(
      `${API_BASE_URL}/api/v1/trading/tasks/${taskId}/stop`,
      { close_deals_on_stop: closeDealsOnStop }
    )
    return response.data
  },

  /**
   * Get live trading results (trades, deals, orders, stats, errors).
   * @param {number} taskId
   * @param {string} resultId - UUID of the trading run
   * @param {string|null} timeBegin - Optional ISO datetime string to filter from
   * @param {number} minErrorId - Minimum error id for incremental loading (0 = all)
   * @returns {Promise<{success: boolean, data: Object}>}
   */
  async getResults(taskId, resultId, timeBegin = null, minErrorId = 0) {
    const params = {}
    if (timeBegin) params.time_begin = timeBegin
    if (minErrorId > 0) params.min_error_id = minErrorId
    const response = await axios.get(
      `${API_BASE_URL}/api/v1/trading/tasks/${taskId}/results/${resultId}`,
      { params }
    )
    return response.data
  },

  /**
   * Get errors from the error registry for a live trading run.
   * @param {number} taskId
   * @param {string} resultId - UUID of the trading run
   * @param {number} minId - Minimum error id (0 = all)
   * @param {number|null} dealId - Optional deal id to filter errors by
   * @returns {Promise<{success: boolean, data: Array}>}
   */
  async getErrors(taskId, resultId, minId = 0, dealId = null) {
    const params = {}
    if (minId > 0) params.min_id = minId
    if (dealId !== null) params.deal_id = dealId
    const response = await axios.get(
      `${API_BASE_URL}/api/v1/trading/tasks/${taskId}/results/${resultId}/errors`,
      { params }
    )
    return response.data
  },

  /**
   * Get supervisor-level errors for a trading task.
   * @param {number} taskId
   * @returns {Promise<{success: boolean, data: Array}>}
   */
  async getSupervisorErrors(taskId) {
    const response = await axios.get(
      `${API_BASE_URL}/api/v1/trading/tasks/${taskId}/supervisor-errors`
    )
    return response.data
  },

  /**
   * Get supervisor errors from all trading tasks combined.
   * @returns {Promise<{success: boolean, data: Array}>}
   */
  async getAllSupervisorErrors() {
    const response = await axios.get(
      `${API_BASE_URL}/api/v1/trading/supervisor-errors`
    )
    return response.data
  },

  /**
   * Delete supervisor errors from all trading tasks.
   * @returns {Promise<{success: boolean, deleted_count: number}>}
   */
  async clearAllSupervisorErrors() {
    const response = await axios.delete(
      `${API_BASE_URL}/api/v1/trading/supervisor-errors`
    )
    return response.data
  },

  /**
   * Create a WebSocket connection for streaming task messages.
   * @param {number} taskId
   * @returns {WebSocket}
   */
  createMessagesWebSocket(taskId) {
    const wsBase = API_BASE_URL.replace(/^http/, 'ws')
    return new WebSocket(`${wsBase}/api/v1/trading/tasks/${taskId}/messages`)
  },

  /**
   * Create a WebSocket connection for streaming global supervisor messages.
   * @returns {WebSocket}
   */
  createSupervisorWebSocket() {
    const wsBase = API_BASE_URL.replace(/^http/, 'ws')
    return new WebSocket(`${wsBase}/api/v1/trading/supervisor/messages`)
  },
}
