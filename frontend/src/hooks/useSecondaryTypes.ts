import { useEffect, useState } from 'react';
import { fetchSecondaryTypes } from '../api/client';

/**
 * Distinct secondary (non-administrative) boundary types available for a
 * country, e.g. ['health'] for the DRC. Empty when the country has none.
 */
export function useSecondaryTypes(iso2: string | null) {
  const [types, setTypes] = useState<string[]>([]);

  useEffect(() => {
    setTypes([]);
    if (!iso2) return;
    fetchSecondaryTypes(iso2)
      .then((data) => setTypes(data.types ?? []))
      .catch(() => setTypes([]));
  }, [iso2]);

  return types;
}
