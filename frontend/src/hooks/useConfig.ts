import { useCallback, useEffect, useState } from 'react'

import { api } from '../services/api'
import type { ConfigResponse, HealthResponse } from '../types/api'

/** Loads runtime configuration and health for the provider indicator and status banner. */
export function useConfig() {
  const [config, setConfig] = useState<ConfigResponse | null>(null)
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    // Settled rather than all: a database outage must not hide the provider information,
    // and vice versa.
    const [configResult, healthResult] = await Promise.allSettled([api.config(), api.health()])
    if (configResult.status === 'fulfilled') setConfig(configResult.value)
    if (healthResult.status === 'fulfilled') setHealth(healthResult.value)
    setLoading(false)
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  return { config, health, loading, refresh }
}
