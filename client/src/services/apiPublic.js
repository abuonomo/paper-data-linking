import axios from 'axios'
import { BASE_URL } from './apiEndpoints'

export async function fetchPublicValidatedUsages(bibcode, includeUnvalidated = false) {
  const url = `${BASE_URL}/builder/public/papers/${encodeURIComponent(bibcode)}/validated-usages/`
  const params = includeUnvalidated ? { include_unvalidated: 'true' } : {}
  const resp = await axios.get(url, { 
    headers: { Accept: 'application/json' },
    params 
  })
  return resp.data
}

export async function fetchPublicPaperPDF(bibcode) {
  const url = `${BASE_URL}/builder/public/papers/${encodeURIComponent(bibcode)}/pdf/`
  const resp = await axios.get(url, {
    headers: { Accept: 'application/json' },
  })
  return resp.data
}

export async function fetchPublicValidatedPapers(includeUnvalidated = false, page = 1, pageSize = 20, filters = {}) {
  const url = `${BASE_URL}/builder/public/papers/validated/`
  const params = { 
    include: '1', // Always include ADS metadata
    page: page,
    page_size: pageSize
  }
  
  if (includeUnvalidated) {
    params.include_unvalidated = 'true'
  }
  
  // Add filter parameters
  if (filters.missions && filters.missions.length > 0) {
    params.missions = filters.missions
  }
  
  if (filters.instruments && filters.instruments.length > 0) {
    params.instruments = filters.instruments
  }
  
  if (filters.start_date) {
    params.start_date = filters.start_date
  }
  
  if (filters.end_date) {
    params.end_date = filters.end_date
  }

  if (filters.validation_status && filters.validation_status.length > 0) {
    params.validation_status = filters.validation_status
  }

  // Curated tag sets (link-driven, e.g. /public/papers?tags=hssi)
  if (filters.tags && filters.tags.length > 0) {
    params.tags = filters.tags
  }

  // Text search (bibcode or title)
  if (filters.query && String(filters.query).trim()) {
    params.q = String(filters.query).trim()
  }
  
  console.log('API request params:', params); // Debug log
  
  const resp = await axios.get(url, { 
    headers: { Accept: 'application/json' },
    params,
    paramsSerializer: {
      indexes: null // This ensures arrays are serialized as param[]=value1&param[]=value2
    }
  })
  return resp.data
}

export async function fetchSimilarPapers(bibcode, includeUnvalidated = false) {
  const url = `${BASE_URL}/builder/public/papers/${encodeURIComponent(bibcode)}/similar/`
  const params = includeUnvalidated ? { include_unvalidated: 'true' } : {}
  const resp = await axios.get(url, { headers: { Accept: 'application/json' }, params })
  return resp.data
}

export async function fetchPublicInstrumentMentions(bibcode, matchLevels = []) {
  let url = `${BASE_URL}/builder/public/papers/${encodeURIComponent(bibcode)}/instrument-mentions/`
  const params = {}
  if (matchLevels.length > 0) {
    params.match_level = matchLevels.join(',')
  }
  const resp = await axios.get(url, { headers: { Accept: 'application/json' }, params })
  return resp.data
}

export async function fetchPublicPapersFilterOptions(includeUnvalidated = false) {
  const url = `${BASE_URL}/builder/public/papers/filter-options/`
  const params = {}
  if (includeUnvalidated) {
    params.include_unvalidated = 'true'
  }
  const resp = await axios.get(url, { 
    headers: { Accept: 'application/json' },
    params 
  })
  return resp.data
}
