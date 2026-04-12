import { useEffect, useState } from 'react';
import { fetchAvailableLevels } from '../api/client';

export function useAvailableLevels(iso2: string | null) {
  const [levels, setLevels] = useState<number[]>([]);

  useEffect(() => {
    setLevels([]);
    if (!iso2) return;
    fetchAvailableLevels(iso2)
      .then((data) => setLevels((data.levels ?? []).filter((l) => l > 0)))
      .catch(() => setLevels([]));
  }, [iso2]);

  return levels;
}
