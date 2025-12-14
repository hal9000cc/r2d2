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
      const error = await response.json().catch(() => ({ detail: response.statusText }))
      throw new Error(error.detail || error.message || `HTTP error! status: ${response.status}`)
    }

    return await response.json()
  } catch (error) {
    throw error
  }
}

export const strategiesApi = {
  // Get list of available timeframes
  async getTimeframes() {
    return request('/api/v1/common/timeframes')
  },

  // Get list of available sources
  async getSources() {
    return request('/api/v1/common/sources')
  },

  // Get list of symbols for a specific source
  async getSourceSymbols(source) {
    return request(`/api/v1/common/sources/${source}/symbols`)
  },

  // Load strategy by name
  async loadStrategy(name) {
    return request(`/api/v1/strategies/load/${name}`)
  },

  // Save strategy
  async saveStrategy(name, text) {
    return request('/api/v1/strategies/save', {
      method: 'POST',
      body: JSON.stringify({ name, text })
    })
  },

  // Create new strategy
  async createStrategy(name, filePath = null) {
    let url = `/api/v1/strategies/new?name=${encodeURIComponent(name)}`
    if (filePath) {
      url += `&file_path=${encodeURIComponent(filePath)}`
    }
    return request(url, {
      method: 'POST'
    })
  },

  // Get strategies directory path
  async getStrategiesDirectory() {
    return request('/api/v1/strategies/directory')
  },

  // List files and directories
  async listFiles(path = null, mask = null) {
    const params = new URLSearchParams()
    if (path) params.append('path', path)
    if (mask) params.append('mask', mask)
    const query = params.toString()
    return request(`/api/v1/strategies/files/list${query ? '?' + query : ''}`)
  }
}
