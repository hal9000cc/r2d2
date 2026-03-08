import axios from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8202'

export const settingsApi = {
  /**
   * Load current application configuration.
   * Sensitive values (passwords, API keys) are returned masked.
   * @returns {Promise<Object>} Structured config object
   */
  async getSettings() {
    const response = await axios.get(`${API_BASE_URL}/api/v1/settings`)
    return response.data
  },

  /**
   * Save application configuration.
   * Send the same structure returned by getSettings().
   * Masked values that the user did not change are preserved server-side.
   * @param {Object} config - Full config object
   * @returns {Promise<{success: boolean, changed_keys: string[], actions_taken: string[], warnings: string[]}>}
   */
  async saveSettings(config) {
    const response = await axios.put(`${API_BASE_URL}/api/v1/settings`, config)
    return response.data
  },
}
