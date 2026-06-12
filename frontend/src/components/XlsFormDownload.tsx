import { Button, Tooltip } from '@mantine/core';

interface Props {
  country: string | null;
}

/**
 * Downloads a pre-generated KoboCollect XLSForm with cascading admin-boundary
 * select_one questions for the selected country. The server sets a
 * Content-Disposition header, so a plain anchor triggers the download.
 */
export function XlsFormDownload({ country }: Props) {
  const button = (
    <Button
      component="a"
      href={country ? `/xlsform?country=${country}` : undefined}
      disabled={!country}
      variant="default"
    >
      Download XLSForm
    </Button>
  );

  if (country) return button;

  return (
    <Tooltip label="Select a country first" withArrow>
      <span>{button}</span>
    </Tooltip>
  );
}
