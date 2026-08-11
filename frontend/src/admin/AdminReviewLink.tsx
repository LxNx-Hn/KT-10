import { useEffect, useState } from 'react';
import { resolveCurrentAuth } from '@/auth/api';

/** 관리자 여부는 서버 응답으로 확인하며, 링크 비노출은 보안 경계로 사용하지 않는다. */
export default function AdminReviewLink() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    let active = true;
    void resolveCurrentAuth().then((auth) => {
      if (active) {
        setVisible(auth.status === 'authenticated' && auth.user.isAdmin);
      }
    });
    return () => {
      active = false;
    };
  }, []);

  if (!visible) return null;
  return (
    <a className="map-first__admin-link" href="/admin/reviews">
      사용자 리뷰 검토
    </a>
  );
}
