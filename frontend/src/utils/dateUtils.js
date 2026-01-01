/**
 * Date/time utility functions
 */

/**
 * Convert Unix timestamp (seconds) to ISO string
 * @param {number} timestamp - Unix timestamp in seconds
 * @returns {string} ISO string
 */
export function unixToISO(timestamp) {
  return new Date(timestamp * 1000).toISOString()
}

/**
 * Convert ISO string to Unix timestamp (seconds)
 * @param {string} isoString - ISO string
 * @returns {number} Unix timestamp in seconds
 */
export function isoToUnix(isoString) {
  return Math.floor(new Date(isoString).getTime() / 1000)
}

