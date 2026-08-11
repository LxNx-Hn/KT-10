/**
 * RFC4180-lite CSV 파서.
 * quoted 필드(쉼표·개행·따옴표 이스케이프)를 지원한다.
 * 대형 CSV 라이브러리 없이 5-column 정적 데이터용으로만 사용한다.
 */

export function parseRfc4180Csv(raw: string): string[][] {
  const text = raw.replace(/^\uFEFF/, '');
  const rows: string[][] = [];
  let row: string[] = [];
  let field = '';
  let i = 0;
  let inQuotes = false;

  const pushField = () => {
    row.push(field);
    field = '';
  };
  const pushRow = () => {
    // 완전히 빈 trailing 줄은 무시
    if (row.length === 1 && row[0] === '' && field === '') {
      row = [];
      return;
    }
    pushField();
    rows.push(row);
    row = [];
  };

  while (i < text.length) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i += 2;
          continue;
        }
        inQuotes = false;
        i += 1;
        continue;
      }
      field += ch;
      i += 1;
      continue;
    }

    if (ch === '"') {
      inQuotes = true;
      i += 1;
      continue;
    }
    if (ch === ',') {
      pushField();
      i += 1;
      continue;
    }
    if (ch === '\n') {
      pushRow();
      i += 1;
      continue;
    }
    if (ch === '\r') {
      if (text[i + 1] === '\n') i += 1;
      pushRow();
      i += 1;
      continue;
    }
    field += ch;
    i += 1;
  }

  if (inQuotes) {
    throw new Error('CSV: unclosed quoted field');
  }
  if (field.length > 0 || row.length > 0) {
    pushRow();
  }

  return rows.filter((entry) => entry.some((value) => value.trim() !== ''));
}
