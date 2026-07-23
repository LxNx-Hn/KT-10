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
    <span className={`connection ${online ? 'connection--online' : 'connection--offline'}`} role="status">
      <span aria-hidden="true" />
      {online ? '온라인' : '오프라인'}
    </span>
  );
}
