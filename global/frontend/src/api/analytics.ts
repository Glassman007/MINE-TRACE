import { useQuery } from '@tanstack/react-query'
import { apiGet } from './http'
import type { AnalyticsBucketsResponse, AnalyticsSummaryResponse, AnalyticsTrendResponse } from './generated/types'

export const analyticsKeys = { summary: ['analytics','summary'] as const, byStatus: ['analytics','incidents','by-status'] as const, bySite: ['analytics','incidents','by-site'] as const, trend: ['analytics','incidents','trend'] as const }
export const getAnalyticsSummary = () => apiGet<AnalyticsSummaryResponse>('/api/v1/analytics/summary')
export const getIncidentsByStatus = () => apiGet<AnalyticsBucketsResponse>('/api/v1/analytics/incidents/by-status')
export const getIncidentsBySite = () => apiGet<AnalyticsBucketsResponse>('/api/v1/analytics/incidents/by-site')
export const getIncidentTrend = () => apiGet<AnalyticsTrendResponse>('/api/v1/analytics/incidents/trend')
export const useAnalyticsSummary = () => useQuery({ queryKey: analyticsKeys.summary, queryFn: getAnalyticsSummary })
export const useIncidentsByStatus = () => useQuery({ queryKey: analyticsKeys.byStatus, queryFn: getIncidentsByStatus })
export const useIncidentsBySite = () => useQuery({ queryKey: analyticsKeys.bySite, queryFn: getIncidentsBySite })
export const useIncidentTrend = () => useQuery({ queryKey: analyticsKeys.trend, queryFn: getIncidentTrend })
