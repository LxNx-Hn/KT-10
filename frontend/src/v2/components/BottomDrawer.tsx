import {
  useEffect,
  useRef,
  type ReactNode,
} from 'react';

export default function BottomDrawer({
  drawerId,
  title,
  onClose,
  children,
}: {
  drawerId: string;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const previousFocus =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const focusTimer = window.setTimeout(() => {
      panelRef.current
        ?.querySelector<HTMLElement>('[data-autofocus], button, input, select')
        ?.focus();
    }, 0);

    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== 'Tab' || !panelRef.current) return;
      const focusable = Array.from(
        panelRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => !element.hidden);
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleKey);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener('keydown', handleKey);
      previousFocus?.focus();
    };
  }, [onClose]);

  return (
    <div className="map-first__drawer-layer">
      <button
        type="button"
        className="map-first__drawer-backdrop"
        aria-label={`${title} 닫기`}
        onClick={onClose}
      />
      <div
        ref={panelRef}
        className="map-first__drawer-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${drawerId}-title`}
      >
        <div className="map-first__sheet-handle" aria-hidden="true">
          <span className="map-first__sheet-handle-bar" />
        </div>
        <header className="map-first__drawer-head">
          <h2 id={`${drawerId}-title`}>{title}</h2>
          <button
            type="button"
            className="map-first__drawer-close"
            data-autofocus
            aria-label={`${title} 닫기`}
            onClick={onClose}
          >
            ×
          </button>
        </header>
        <div className="map-first__drawer-body">{children}</div>
      </div>
    </div>
  );
}
