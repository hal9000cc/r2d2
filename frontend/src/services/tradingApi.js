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
   * Clone a backtesting task into a new trading task.
   * @param {number} backtestingTaskId - Source backtesting task ID
   * @returns {Promise<Object>} Created trading task
   */
  /**
   * Delete a trading task.
   * @param {number} taskId
   */
  async deleteTask(taskId) {
    const response = await axios.delete(`${API_BASE_URL}/api/v1/trading/tasks/${taskId}`)
    return response.data
  },

  async cloneFromBacktesting(backtestingTaskId) {
    const response = await axios.post(
      `${API_BASE_URL}/api/v1/trading/tasks/clone/${backtestingTaskId}`
    )
    return response.data
  }
}

