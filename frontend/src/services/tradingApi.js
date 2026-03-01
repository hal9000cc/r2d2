import axios from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8202'

export const tradingApi = {
  /**
   * Clone a backtesting task into a new trading task
   * @param {number} backtestingTaskId - Source backtesting task ID
   * @returns {Promise<Object>} Created trading task
   */
  async cloneFromBacktesting(backtestingTaskId) {
    const response = await axios.post(
      `${API_BASE_URL}/api/v1/trading/tasks/clone/${backtestingTaskId}`
    )
    return response.data
  }
}

