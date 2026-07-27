// src/hooks/useUsageByMission.js
import { useState, useEffect } from 'react';
import { fetchUsageByMission } from '../services/apiServices';

export function useUsageByMission() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    fetchUsageByMission()
      .then((resp) => {
        if (!cancelled) setData(resp);
      })
      .catch((err) => {
        console.error(err);
        if (!cancelled) setError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return { data, loading, error };
}
