import axios from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8202'

export const backtestingApi = {
  /**
   * Get list of all backtesting tasks
   */
  async getTasks() {
    const response = await axios.get(`${API_BASE_URL}/api/v1/backtesting/tasks`)
    return response.data
  },

  /**
   * Get single backtesting task by ID
   * If id is 0, returns empty task with new ID
   */
  async getTask(id) {
    const response = await axios.get(`${API_BASE_URL}/api/v1/backtesting/tasks/${id}`)
    return response.data
  },

  /**
   * Create new backtesting task
   */
  async createTask(taskData) {
    const response = await axios.post(`${API_BASE_URL}/api/v1/backtesting/tasks`, taskData)
    return response.data
  },

  /**
   * Update backtesting task
   */
  async updateTask(id, taskData) {
    const response = await axios.put(`${API_BASE_URL}/api/v1/backtesting/tasks/${id}`, taskData)
    return response.data
  },

  /**
   * Delete backtesting task
   */
  async deleteTask(id) {
    const response = await axios.delete(`${API_BASE_URL}/api/v1/backtesting/tasks/${id}`)
    return response.data
  },

  /**
   * Start backtesting for a task
   */
  async startBacktest(taskId) {
    const response = await axios.post(`${API_BASE_URL}/api/v1/backtesting/tasks/${taskId}/start`)
    return response.data
  },

  /**
   * Stop backtesting for a task
   */
  async stopBacktest(taskId) {
    const response = await axios.post(`${API_BASE_URL}/api/v1/backtesting/tasks/${taskId}/stop`)
    return response.data
  }
}
