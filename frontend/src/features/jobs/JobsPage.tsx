import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { useJobsList, useReprocessJob, useRescan, useRetryJob } from "../../api/hooks";
import type { JobStatus } from "../../api/types";
import { Empty } from "../../components/ui/Empty";
import { ErrorBanner } from "../../components/ui/ErrorBanner";
import { Loading } from "../../components/ui/Loading";

const STATUS_VALUES: JobStatus[] = [
  "pending",
  "processing",
  "review_required",
  "completed",
  "failed",
  "cancelled",
];

export function JobsPage() {
  const { t } = useTranslation();
  const [filter, setFilter] = useState<JobStatus | undefined>(undefined);
  const jobs = useJobsList({ status: filter, limit: 100, pollMs: 4000 });
  const rescan = useRescan();
  const retry = useRetryJob();
  const reprocess = useReprocessJob();
  const [rescanResult, setRescanResult] = useState<number | null>(null);

  return (
    <section>
      <header className="page-header">
        <h2>{t("jobs.title")}</h2>
        <div className="toolbar">
          <label className="row">
            <span className="muted">{t("jobs.filter")}:</span>
            <select
              value={filter ?? ""}
              onChange={(e) =>
                setFilter(e.target.value === "" ? undefined : (e.target.value as JobStatus))
              }
              aria-label={t("jobs.filter")}
            >
              <option value="">{t("jobs.all")}</option>
              {STATUS_VALUES.map((s) => (
                <option key={s} value={s}>
                  {t(`jobs.status.${s}`)}
                </option>
              ))}
            </select>
          </label>
          <button
            className="primary"
            disabled={rescan.isPending}
            onClick={() =>
              rescan.mutate(undefined, {
                onSuccess: (res) => setRescanResult(res.enqueued),
              })
            }
          >
            {t("jobs.rescan")}
          </button>
        </div>
      </header>

      {rescanResult !== null && (
        <div className="card" style={{ marginBottom: "1rem" }}>
          {t("jobs.rescanned", { count: rescanResult })}
        </div>
      )}
      {jobs.error ? <ErrorBanner error={jobs.error} /> : null}
      {retry.error ? <ErrorBanner error={retry.error} /> : null}
      {reprocess.error ? <ErrorBanner error={reprocess.error} /> : null}

      {jobs.isLoading ? (
        <Loading />
      ) : !jobs.data || jobs.data.items.length === 0 ? (
        <Empty />
      ) : (
        <table>
          <thead>
            <tr>
              <th>{t("jobs.headers.id")}</th>
              <th>{t("jobs.headers.file")}</th>
              <th>{t("jobs.headers.status")}</th>
              <th>{t("jobs.headers.attempt")}</th>
              <th>{t("jobs.headers.mode")}</th>
              <th>{t("jobs.headers.updated")}</th>
              <th>{t("jobs.headers.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {jobs.data.items.map((job) => (
              <tr key={job.id}>
                <td>{job.id}</td>
                <td>{job.file_name}</td>
                <td>
                  <span className={`status-badge status-${job.status}`}>
                    {t(`jobs.status.${job.status}`)}
                  </span>
                </td>
                <td>{job.attempt}</td>
                <td>{job.mode}</td>
                <td className="muted">{job.updated_at ?? job.created_at}</td>
                <td className="row">
                  <Link to={`/jobs/${job.id}`}>{t("jobs.actions.view")}</Link>
                  {job.status === "failed" && (
                    <button onClick={() => retry.mutate(job.id)} disabled={retry.isPending}>
                      {t("jobs.actions.retry")}
                    </button>
                  )}
                  <button onClick={() => reprocess.mutate(job.id)} disabled={reprocess.isPending}>
                    {t("jobs.actions.reprocess")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
