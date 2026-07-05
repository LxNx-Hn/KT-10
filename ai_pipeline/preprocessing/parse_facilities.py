"""스마트버스쉘터 부대시설 텍스트 파싱 모듈."""


def parse_facilities(text: str) -> dict:
    """
    '냉난방기, 공기청정기, 온열의자' 형태의 자유 텍스트를
    불리언 피처 딕셔너리로 변환한다.

    Parameters
    ----------
    text : str
        부대시설 컬럼 원본 텍스트.

    Returns
    -------
    dict
        피처명 → bool 딕셔너리.
    """
    text = str(text)
    return {
        "has_ac":           "냉난방" in text or "냉방" in text,
        "has_air_purifier": "공기청정" in text,
        "has_heated_seat":  "온열의자" in text or "냉온열의자" in text,
        "has_charger":      "충전기" in text,
        "has_wifi":         "와이파이" in text,
        "has_kiosk":        "키오스크" in text,
        "has_auto_door":    "자동문" in text,
    }
