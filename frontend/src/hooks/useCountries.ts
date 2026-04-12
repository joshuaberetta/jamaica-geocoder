import { useEffect, useState } from 'react';
import { fetchCountries } from '../api/client';
import type { Country } from '../api/types';

export function useCountries() {
  const [countries, setCountries] = useState<Country[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchCountries()
      .then(setCountries)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  return { countries, loading };
}
