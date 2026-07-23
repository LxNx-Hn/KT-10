/**
 * 음성 챗봇 의도(intent) 타입 (요구사항 §6·§8).
 */
import type { ProfileId } from '@/types';

export type VoiceChatStatus = 'idle' | 'listening' | 'thinking' | 'speaking' | 'error';

export type VoiceIntent =
  | 'SEARCH_DESTINATION'
  | 'SET_PROFILE'
  | 'SET_LOW_FLOOR_BUS_PRIORITY'
  | 'SET_WEATHER_AVOIDANCE'
  | 'SET_TRIP_CONDITION'
  | 'EXPLAIN_ROUTE'
  | 'SELECT_ROUTE'
  | 'REPEAT_GUIDE'
  | 'UNKNOWN';

export type WeatherAvoidanceMode = 'heat' | 'rain' | 'cold' | 'dust' | 'general';
export type TripCondition =
  | 'carryLuggage'
  | 'stroller'
  | 'shadePriority'
  | 'minimizeTransfers';

export type VoiceChatMessage = {
  id: string;
  role: 'user' | 'assistant' | 'system';
  text: string;
  createdAt: string;
  intent?: VoiceIntent;
};

/** 파싱된 단일 명령(payload 포함) */
export type ParsedCommand =
  | { intent: 'SEARCH_DESTINATION'; destination: string; origin?: string }
  | { intent: 'SET_PROFILE'; profile: ProfileId }
  | { intent: 'SET_LOW_FLOOR_BUS_PRIORITY' }
  | { intent: 'SET_WEATHER_AVOIDANCE'; weatherMode: WeatherAvoidanceMode }
  | { intent: 'SET_TRIP_CONDITION'; condition: TripCondition }
  | { intent: 'EXPLAIN_ROUTE'; routeIndex: number }
  | { intent: 'SELECT_ROUTE'; routeIndex: number }
  | { intent: 'REPEAT_GUIDE' }
  | { intent: 'UNKNOWN'; text: string };

/** 파싱 결과: 명령 목록 + 부가 수식어(계단 회피/승강기 우선) */
export interface VoiceParse {
  commands: ParsedCommand[];
  /** "계단 없는/계단 회피" → 계단 회피 모드 */
  avoidStairs: boolean;
  /** "승강기 우선/엘리베이터" → 승강기 우선(계단 회피와 동일 가중 적용) */
  elevatorPriority: boolean;
}
