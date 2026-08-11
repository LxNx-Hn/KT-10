import { describe, expect, it } from 'vitest';
import { parseRfc4180Csv } from './parseRfc4180Csv';

describe('parseRfc4180Csv', () => {
  it('BOM과 quoted comma를 포함한 행을 파싱한다', () => {
    const raw = '\uFEFFa,b\n1,"hello, world",3\n';
    expect(parseRfc4180Csv(raw)).toEqual([
      ['a', 'b'],
      ['1', 'hello, world', '3'],
    ]);
  });

  it('"" 이스케이프를 하나의 따옴표로 복원한다', () => {
    expect(parseRfc4180Csv('x\n"a""b"\n')).toEqual([['x'], ['a"b']]);
  });
});
