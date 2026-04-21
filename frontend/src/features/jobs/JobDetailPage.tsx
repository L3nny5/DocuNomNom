import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";
import { useJob } from "../../api/hooks";
import { ErrorBanner } from "../../components/ui/ErrorBanner";
import { Loading } from "../../components/ui/Loading";

export function JobDetailPage() {
  const { t } = useTranslation();
  const params = useParams<{ id: string }>();
  const id = params.id ? Number(params.id) : null;
  const job = useJob(id, { pollMs: 4000 });

  return (
    <section>
      <header className="page-header">
        <h2>
          <Link to="/jobs">{t("nav.jobs")}</Link> <span className="muted">/ #{id}</span>
        </h2>
      </header>

      {job.error ? <ErrorBanner error={job.error} /> : null}

      {job.isLoading || !job.data ? (
        <Loading />
      ) : (
        <div style={{ display: "flex", gap: "1rem", flexDirection: "column" }}>
          <div className="card">
            <div className="form-grid">
              <label>{t("jobs.headers.file")}</label>
              <span>{job.data.file_name}</span>
              <label>{t("jobs.headers.status")}</label>
              <span className={`status-badge status-${job.data.status}`}>
                {t(`jobs.status.${job.data.status}`)}
              </span>
              <label>{t("jobs.headers.attempt")}</label>
              <span>{job.data.attempt}</span>
              <label>{t("jobs.headers.mode")}</label>
              <span>{job.data.mode}</span>
              <label>{t("jobs.detail.runKey")}</label>
              <code style={{ fontSize: "0.8rem" }}>{job.data.run_key}</code>
              {job.data.error_code && (
                <>
                  <label>{t("jobs.detail.error")}</label>
                  <span style={{ color: "var(--danger)" }}>
                    {job.data.error_code}: {job.data.error_msg}
                  </span>
                </>
              )}
            </div>
          </div>

          <div className="card">
            <h3 style={{ marginTop: 0 }}>{t("jobs.detail.events")}</h3>
            {job.data.events.length === 0 ? (
              <div className="muted">{t("jobs.detail.noEvents")}</div>
            ) : (
              <ul className="events">
                {job.data.events.map((ev) => (
                  <li key={ev.id}>
                    <span className="muted">{ev.ts}</span> — <strong>{ev.type}</strong>
                    {Object.keys(ev.payload).length > 0 && (
                      <pre
                        style={{
                          margin: "0.2rem 0 0 0",
                          fontSize: "0.75rem",
                          color: "var(--muted)",
                        }}
                      >
                        {JSON.stringify(ev.payload)}
                      </pre>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
