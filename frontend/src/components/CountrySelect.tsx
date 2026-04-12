import { Select, Skeleton } from '@mantine/core';
import { useSearchParams } from 'react-router-dom';
import { useEffect } from 'react';
import { useCountries } from '../hooks/useCountries';
import type { Country } from '../api/types';

interface Props {
  value: string | null;
  onChange: (country: Country | null) => void;
}

export function CountrySelect({ value, onChange }: Props) {
  const { countries, loading } = useCountries();
  const [searchParams] = useSearchParams();

  // Sync URL ?country= param on first load
  useEffect(() => {
    if (!countries.length) return;
    const param = (searchParams.get('country') ?? '').toUpperCase();
    const match = countries.find((c) => c.code.toUpperCase() === param) ?? countries[0];
    onChange(match ?? null);
  }, [countries]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) return <Skeleton height={42} />;

  const data = countries.map((c) => ({ value: c.code, label: c.name }));

  return (
    <Select
      label="Select Country"
      placeholder="Choose a country…"
      data={data}
      value={value}
      onChange={(code) => {
        const found = countries.find((c) => c.code === code) ?? null;
        onChange(found);
      }}
      searchable
      styles={{ root: { maxWidth: '100%' } }}
    />
  );
}
