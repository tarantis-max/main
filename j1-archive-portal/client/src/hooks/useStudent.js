import { useState, useEffect } from 'react';
import api from '../api/client';

export function useStudent(id, endpoint = '') {
  const [data, setData]     = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]   = useState(null);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setError(null);
    api.get(`/students/${id}${endpoint}`)
      .then(r => setData(r.data))
      .catch(err => setError(err.response?.data?.error || 'Failed to load data'))
      .finally(() => setLoading(false));
  }, [id, endpoint]);

  return { data, loading, error };
}
