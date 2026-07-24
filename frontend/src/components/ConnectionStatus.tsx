import { useEffect, useState } from 'react';

export default function ConnectionStatus() {
  const [online, setOnline] = useState(() => navigator.onLine);

  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    window.addEventListener('online', update);
    window.addEventListener('offline', update);
    return () => {
      window.removeEventListener('online', update);
      window.removeEventListener('offline', update);
    };
  }, []);

  return (
    <span
      className={`connection ${online ? 'connection--online' : 'connection--offline'}`}
      role="status"
      aria-label={online ? '기기 네트워크 연결됨' : '기기 네트워크 연결 끊김'}
      title="기기의 네트워크 연결 상태이며 외부 데이터 서버 상태와는 다를 수 있습니다."
    >
      <span aria-hidden="true" />
      {online ? '네트워크' : '오프라인'}
    </span>
  );
}
