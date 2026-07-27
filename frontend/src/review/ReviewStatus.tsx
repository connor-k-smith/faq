export function ReviewStatus({
  text,
  detail,
  pending = false,
}: {
  text: string;
  detail?: string;
  pending?: boolean;
}) {
  return (
    <main
      className="status-page"
      role={pending ? "status" : "alert"}
      aria-live="polite"
    >
      <a className="wordmark" href="/">
        FAQ
      </a>
      <p className="eyebrow">Live results</p>
      <h1>{text}</h1>
      {detail && <p className="lede">{detail}</p>}
      <a className="text-button status-link" href="/">
        Back to Projects
      </a>
    </main>
  );
}
