import { useEffect, type ReactNode } from "react";

export default function Sheet({ onClose, leafy, label, children }: {
  onClose: () => void; leafy?: boolean; label: string; children: ReactNode;
}) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <>
      <div className="backdrop" onClick={onClose} />
      <div className={"sheet" + (leafy ? " leafy" : "")} role="dialog" aria-label={label}>
        <div className="handle" />
        {children}
      </div>
    </>
  );
}

export function Toast({ msg, onDone }: { msg: string; onDone: () => void }) {
  useEffect(() => {
    const t = setTimeout(onDone, 3200);
    return () => clearTimeout(t);
  }, [msg, onDone]);
  return <div className="toast" role="status">{msg}</div>;
}
