// src/utils/dateUtils.js
// Centralized date formatting utilities that always display UTC times

/**
 * Format an ISO datetime string to display in UTC timezone
 * @param {string} isoString - ISO 8601 datetime string
 * @param {object} options - Formatting options
 * @returns {string} Formatted date string with UTC indicator
 */
export const formatDateTimeUTC = (isoString, options = {}) => {
  if (!isoString) return 'N/A';
  
  const date = new Date(isoString);
  
  const defaultOptions = {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'UTC',
    timeZoneName: 'short'
  };
  
  const formatOptions = { ...defaultOptions, ...options };
  
  return date.toLocaleString('en-US', formatOptions);
};

/**
 * Format an ISO datetime string to display date only in UTC
 * @param {string} isoString - ISO 8601 datetime string
 * @returns {string} Formatted date string
 */
export const formatDateUTC = (isoString) => {
  if (!isoString) return 'N/A';
  
  const date = new Date(isoString);
  
  return date.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC'
  });
};

/**
 * Format an ISO datetime string to a compact UTC format
 * @param {string} isoString - ISO 8601 datetime string
 * @returns {string} Compact formatted date string with UTC suffix
 */
export const formatDateTimeCompactUTC = (isoString) => {
  if (!isoString) return 'N/A';
  
  const date = new Date(isoString);
  
  // Format as "YYYY-MM-DD HH:mm UTC"
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, '0');
  const day = String(date.getUTCDate()).padStart(2, '0');
  const hours = String(date.getUTCHours()).padStart(2, '0');
  const minutes = String(date.getUTCMinutes()).padStart(2, '0');
  
  return `${year}-${month}-${day} ${hours}:${minutes} UTC`;
};

/**
 * Format an ISO datetime string to ISO format with UTC indicator
 * @param {string} isoString - ISO 8601 datetime string
 * @returns {string} ISO format with Z suffix or UTC indicator
 */
export const formatISOUTC = (isoString) => {
  if (!isoString) return 'N/A';
  
  const date = new Date(isoString);
  return date.toISOString();
};

/**
 * Check if a datetime string represents a valid date
 * @param {string} isoString - ISO 8601 datetime string
 * @returns {boolean} True if valid date
 */
export const isValidDate = (isoString) => {
  if (!isoString) return false;
  const date = new Date(isoString);
  return !isNaN(date.getTime());
};

/**
 * Get the current UTC timestamp as ISO string
 * @returns {string} Current UTC timestamp
 */
export const getCurrentUTC = () => {
  return new Date().toISOString();
};