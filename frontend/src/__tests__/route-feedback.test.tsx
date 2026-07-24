// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react';
import RouteFeedback from '@/components/RouteFeedback';
import { demoCandidates } from '@/data/routes';
import { WEATHER_SCENARIOS } from '@/data/weather';
import { recommendRoutes } from '@/scoring/engine';
import { useAppStore } from '@/store/appStore';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('실제 경로 이용 후기', () => {
  it('선택형 직접 관측 3개를 camelCase 1~5 값으로 전송한다', async () => {
    const recommendations = recommendRoutes(
      demoCandidates(),
      WEATHER_SCENARIOS.normal,
      'general',
    );
    const selected = {
      ...recommendations[0],
      score: {
        ...recommendations[0].score,
        feedbackToken: 'signed-feedback-token-for-ui-contract',
      },
    };
    useAppStore.setState({
      recommendations: [selected, ...recommendations.slice(1)],
      selectedRouteId: selected.route.id,
    });

    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        status: 201,
        ok: true,
        json: async () => ({ id: 'impression-1' }),
      } as Response)
      .mockResolvedValueOnce({
        status: 201,
        ok: true,
        json: async () => ({ id: 'review-1' }),
      } as Response);
    vi.stubGlobal('fetch', fetchMock);

    const { getByLabelText, getByRole } = render(<RouteFeedback />);
    fireEvent.change(getByLabelText('가장 불편했던 요소'), {
      target: { value: 'crowding' },
    });
    fireEvent.change(getByLabelText('혼잡으로 인한 이용 불편'), {
      target: { value: '4' },
    });
    fireEvent.change(getByLabelText('환승 안내·정보 이용 불편'), {
      target: { value: '3' },
    });
    fireEvent.change(getByLabelText('교통약자 시설 이용 불편'), {
      target: { value: '2' },
    });
    fireEvent.click(getByRole('button', { name: '이용 가능했어요' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const request = fetchMock.mock.calls[1]?.[1] as RequestInit;
    const payload = JSON.parse(String(request.body)) as Record<string, unknown>;
    expect(payload).toMatchObject({
      issueType: 'crowding',
      crowdingDifficulty: 4,
      transferInformationDifficulty: 3,
      accessibilityFacilityDifficulty: 2,
      trainingConsent: false,
    });
  });
});
