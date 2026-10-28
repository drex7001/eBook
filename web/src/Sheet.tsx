import { useEffect, useRef, useState, type ReactNode } from "react";

export default function Sheet({ onClose, leafy, label, children }: {
  onClose: () => void; leafy?: boolean; label: string; children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);close.current=onClose;
  const [mobile,setMobile]=useState(() => !window.matchMedia("(min-width: 768px)").matches);
  useEffect(() => {
    const previous=document.activeElement as HTMLElement|null;
    const media=window.matchMedia("(min-width: 768px)");
    const change=()=>setMobile(!media.matches);media.addEventListener("change",change);
    document.body.classList.add("inspector-open");
    ref.current?.focus({preventScroll:true});
    const k = (e: KeyboardEvent) => {
      if(e.key==="Escape"){e.preventDefault();close.current();}
      if(e.key==="Tab"&&!media.matches){
        const nodes=Array.from(ref.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href],[tabindex="0"]') || []);
        const first=nodes[0],last=nodes[nodes.length-1];
        if(e.shiftKey&&(document.activeElement===first||document.activeElement===ref.current)){e.preventDefault();last?.focus();}
        else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}
      }
    };
    window.addEventListener("keydown", k);
    return () => {window.removeEventListener("keydown",k);media.removeEventListener("change",change);document.body.classList.remove("inspector-open");previous?.focus({preventScroll:true});};
  }, []);
  return (
    <>
      <div className="backdrop" onClick={onClose} />
      <div ref={ref} tabIndex={-1} className={"sheet" + (leafy ? " leafy" : "")} role="dialog" aria-modal={mobile || undefined} aria-label={label}>
        <div className="handle" />
        <button className="sheet-close icon-btn" aria-label="Close panel" onClick={onClose}>×</button>
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
