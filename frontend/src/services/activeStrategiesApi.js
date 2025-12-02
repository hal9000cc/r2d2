const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8202'

async function request(url, options = {}) {
  try {
    const response = await fetch(`${API_BASE_URL}${url}`, {
      headers: {
        'Content-Type': 'application/json',
        ...options.headers
      },
      ...options
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({ message: response.statusText }))
      throw new Error(error.message || `HTTP error! status: ${response.status}`)
    }

    return await response.json()
  } catch (error) {
    throw error
  }
}

export const activeStrategiesApi = {
  // Get list of active strategies
  async getActiveStrategies() {
    return request('/api/v1/strategies')
  },

  // Get single active strategy by ID
  async getActiveStrategy(id) {
    return request(`/api/v1/strategies/${id}`)
  },

  // Delete active strategy
  async deleteStrategy(id) {
    return request(`/api/v1/strategies/${id}`, {
      method: 'DELETE'
    })
  },

  // Start strategy
  async startStrategy(id) {
    return request(`/api/v1/strategies/${id}/start`, {
      method: 'POST'
    })
  },

  // Stop strategy
  async stopStrategy(id) {
    return request(`/api/v1/strategies/${id}/stop`, {
      method: 'POST'
    })
  },

  // Toggle trading
  async toggleTrading(id) {
    return request(`/api/v1/strategies/${id}/toggle-trading`, {
      method: 'POST'
    })
  },

  // Update strategy (for future use)
  async updateStrategy(id, data) {
    return request(`/api/v1/strategies/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data)
    })
  },

  // Get list of available timeframes
  async getTimeframes() {
    return request('/api/v1/strategies/timeframes')
  },

  // Get list of available sources
  async getSources() {
    return request('/api/v1/strategies/sources')
  },

  // Get list of symbols for a specific source
  async getSourceSymbols(source) {
    return request(`/api/v1/strategies/sources/${source}/symbols`)
  },

  // Get list of available strategies
  async getStrategies() {
    return request('/api/v1/strategies/strategies')
  },

  // Get messages for a strategy
  async getMessages(strategyId) {
    return request(`/api/v1/strategies/${strategyId}/messages`)
  }
}

