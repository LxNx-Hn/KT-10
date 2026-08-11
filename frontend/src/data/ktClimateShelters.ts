import csvRaw from '@/data/ktClimateSheltersBusan.csv?raw';
import { parseRfc4180Csv } from '@/utils/parseRfc4180Csv';

/** 부산광역시 우리동네 기후쉼터(KT) — frontend 전용 정적 지도 데이터 */
export type ClimateShelter = {
  id: string;
  name: string;
  address: string;
  lat: number;
  lng: number;
};

/** 동일 좌표의 쉼터를 하나의 marker로 묶은 그룹 */
export type ClimateShelterMarkerGroup = {
  key: string;
  lat: number;
  lng: number;
  shelters: ClimateShelter[];
};

const EXPECTED_HEADERS = ['연번', '쉼터명', '상세주소', '경도', '위도'] as const;

/** 부산시 기후쉼터 좌표 정상 범위(대략) */
const BUSAN_LAT = { min: 34.7, max: 35.5 } as const;
const BUSAN_LNG = { min: 128.7, max: 129.4 } as const;

function coordKey(lat: number, lng: number): string {
  return `${lat.toFixed(7)},${lng.toFixed(7)}`;
}

export function parseKtClimateSheltersCsv(raw: string): ClimateShelter[] {
  const table = parseRfc4180Csv(raw);
  if (table.length === 0) return [];

  const [header, ...body] = table;
  const normalizedHeader = header.map((cell) => cell.trim());
  for (let i = 0; i < EXPECTED_HEADERS.length; i += 1) {
    if (normalizedHeader[i] !== EXPECTED_HEADERS[i]) {
      throw new Error(
        `CSV header mismatch at ${i}: expected ${EXPECTED_HEADERS[i]}, got ${normalizedHeader[i] ?? ''}`,
      );
    }
  }

  const shelters: ClimateShelter[] = [];
  for (const cells of body) {
    const id = (cells[0] ?? '').trim();
    const name = (cells[1] ?? '').trim();
    const address = (cells[2] ?? '').trim();
    const lng = Number((cells[3] ?? '').trim());
    const lat = Number((cells[4] ?? '').trim());

    if (!id || !name || !address) continue;
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) continue;
    if (lat < BUSAN_LAT.min || lat > BUSAN_LAT.max) continue;
    if (lng < BUSAN_LNG.min || lng > BUSAN_LNG.max) continue;

    shelters.push({ id, name, address, lat, lng });
  }

  return shelters;
}

export function groupClimateSheltersByCoord(
  shelters: ClimateShelter[],
): ClimateShelterMarkerGroup[] {
  const map = new Map<string, ClimateShelterMarkerGroup>();
  for (const shelter of shelters) {
    const key = coordKey(shelter.lat, shelter.lng);
    const existing = map.get(key);
    if (existing) {
      existing.shelters.push(shelter);
      continue;
    }
    map.set(key, {
      key,
      lat: shelter.lat,
      lng: shelter.lng,
      shelters: [shelter],
    });
  }
  return Array.from(map.values());
}

export const KT_CLIMATE_SHELTERS: ClimateShelter[] =
  parseKtClimateSheltersCsv(csvRaw);

export const KT_CLIMATE_SHELTER_GROUPS: ClimateShelterMarkerGroup[] =
  groupClimateSheltersByCoord(KT_CLIMATE_SHELTERS);

export const KT_CLIMATE_SHELTER_SOURCE_LABEL =
  '부산광역시 우리동네 기후쉼터 · KT';

export function hasKtClimateShelterData(): boolean {
  return KT_CLIMATE_SHELTER_GROUPS.length > 0;
}
