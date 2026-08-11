import { describe, expect, it } from 'vitest';
import {
  groupClimateSheltersByCoord,
  KT_CLIMATE_SHELTER_GROUPS,
  KT_CLIMATE_SHELTERS,
  parseKtClimateSheltersCsv,
} from './ktClimateShelters';
import csvRaw from '@/data/ktClimateSheltersBusan.csv?raw';

describe('KT climate shelter CSV adapter', () => {
  it('정적 import 데이터가 135건이며 그룹도 모두 보존한다', () => {
    expect(KT_CLIMATE_SHELTERS).toHaveLength(135);
    const groupedCount = KT_CLIMATE_SHELTER_GROUPS.reduce(
      (sum, group) => sum + group.shelters.length,
      0,
    );
    expect(groupedCount).toBe(135);
    expect(KT_CLIMATE_SHELTER_GROUPS.length).toBe(134);
  });

  it('raw CSV와 adapter 결과가 동일하고 quoted 주소를 유지한다', () => {
    const parsed = parseKtClimateSheltersCsv(csvRaw);
    expect(parsed).toHaveLength(135);
    expect(parsed).toEqual(KT_CLIMATE_SHELTERS);

    const quoted = parsed.find((item) => item.address.includes(','));
    expect(quoted?.address).toContain(',');
    expect(quoted?.name).toBeTruthy();
  });

  it('동일 좌표 2건은 삭제하지 않고 한 marker group으로 묶는다', () => {
    const group = KT_CLIMATE_SHELTER_GROUPS.find(
      (item) => item.shelters.length > 1,
    );
    expect(group).toBeTruthy();
    expect(group!.shelters).toHaveLength(2);
    expect(group!.shelters.map((item) => item.name).sort()).toEqual([
      'KT (주)엘에스컴퍼니 덕천역점',
      'KT 씨엘 젊음의거리점',
    ]);
  });

  it('invalid 좌표·빈 이름은 제외한다', () => {
    const raw = [
      '연번,쉼터명,상세주소,경도,위도',
      '1,정상,남구 지게골로 24,129.0691,35.1355',
      '2,,주소없음,129.1,35.1',
      '3,이름만,,129.1,35.1',
      '4,좌표오류,주소,abc,35.1',
      '5,범위밖,주소,120.0,40.0',
    ].join('\n');
    const parsed = parseKtClimateSheltersCsv(raw);
    expect(parsed).toHaveLength(1);
    expect(parsed[0]?.name).toBe('정상');
    expect(groupClimateSheltersByCoord(parsed)).toHaveLength(1);
  });
});
