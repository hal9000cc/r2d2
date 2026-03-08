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
   * Get live trading results (trades, deals, orders, stats).
   * @param {number} taskId
   * @param {string} resultId - UUID of the trading run
   * @param {string|null} timeBegin - Optional ISO datetime string to filter from
   * @returns {Promise<{success: boolean, data: Object}>}
   */
  async getResults(taskId, resultId, timeBegin = null) {
    const params = {}
    if (timeBegin) params.time_begin = timeBegin
    const response = await axios.get(
      `${API_BASE_URL}/api/v1/trading/tasks/${taskId}/results/${resultId}`,
      { params }
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
}
