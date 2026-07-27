// src/hooks/useEventsData.js
import { useState, useEffect } from 'react';
import { fetchMissionLaunches, fetchSolarEvents } from '../services/apiServices';

export function useEventsData() {
  const [missionLaunches, setMissionLaunches] = useState([]);
  const [solarEvents, setSolarEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    const fetchData = async () => {
      try {
        const [launchesData, eventsData] = await Promise.all([
          fetchMissionLaunches(),
          fetchSolarEvents()
        ]);

        if (!cancelled) {
          setMissionLaunches(launchesData);
          setSolarEvents(eventsData);
        }
      } catch (err) {
        console.error('Error fetching event data:', err);
        if (!cancelled) setError(err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    fetchData();

    return () => {
      cancelled = true;
    };
  }, []);

  return { missionLaunches, solarEvents, loading, error };
}