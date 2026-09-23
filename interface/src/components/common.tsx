import type { ReactNode } from "react";
export function Brand({ children }: { children?: ReactNode }) {
  return (
    <header className="brand">
      <div className="mark" aria-hidden="true">
        q.
      </div>
      <div>
        <strong>Questionnaire</strong>
        <span>Your words, ready to reuse.</span>
      </div>
      {children}
    </header>
  );
}
export function Notice({ children }: { children: ReactNode }) {
  return (
    <div className="notice" role="status">
      {children}
    </div>
  );
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="empty">
      <div className="empty-symbol" aria-hidden="true">
        ↗
      </div>
      <h2>{title}</h2>
      <p>{children}</p>
    </section>
  );
}
export function Unavailable({ children }: { children: ReactNode }) {
  return (
    <p className="muted">
      {children} This capability is awaiting an engine service.
    </p>
  );
}
