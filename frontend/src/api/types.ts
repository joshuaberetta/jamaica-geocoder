export interface Country {
  code: string;
  iso3: string;
  name: string;
  key: string;
  max_adm_level: number;
  map_center: { lat: number; lon: number; zoom: number };
}

export interface PcodeResult {
  success: boolean;
  latitude?: number;
  longitude?: number;
  confidence?: string;
  country?: string;
  adm0_pcode?: string;
  adm0_name?: string;
  adm1_pcode?: string;
  adm1_name?: string;
  adm2_pcode?: string;
  adm2_name?: string;
  adm3_pcode?: string;
  adm3_name?: string;
  adm4_pcode?: string;
  adm4_name?: string;
  // Secondary (non-administrative) boundaries, e.g. DRC health zones
  health_zone_name?: string;
  health_zone_dhis2?: string;
  health_zone_id?: string;
  address?: string;
  error?: string;
}

export interface AvailableLevels {
  iso2: string;
  levels: number[];
}

export interface SecondaryTypes {
  iso2: string;
  types: string[];
}

export interface BatchStats {
  total: number;
  successful: number;
  failed: number;
  skipped: number;
}

export interface BatchResult {
  success: boolean;
  stats: BatchStats;
  file_data: string; // base64
  filename: string;
  mimetype: string;
  error?: string;
}
