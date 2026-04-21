import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { useReviewList } from "../../api/hooks";
import type { ReviewItemStatus } from "../../api/types";
import { Empty } from "../../components/ui/Empty";
import { ErrorBanner } from "../../components/ui/ErrorBanner";
import { Loading } from "../../components/ui/Loading";

const STATUS_VALUES: ReviewItemStatus[] = ["open", "in_progress", "done"];

export function ReviewPage() {
  const { t } = useTranslation();
  const [filter, setFilter] = useState<ReviewItemStatus | undefined>(undefined);
  const review = useReviewList({ status: filter, pollMs: 6000 });

  return (
    <section>
      <header className="page-header">
        <h2>{t("review.title")}</h2>
        <div className="toolbar">
          <label className="row">
            <span className="muted">{t("review.filter")}:</span>
            <select
              value={filter ?? ""}
              onChange={(e) =>
                setFilter(e.target.value === "" ? undefined : (e.target.value as ReviewItemStatus))
              }
              aria-label={t("review.filter")}
            >
              <option value="">{t("review.all")}</option>
              {STATUS_VALUES.map((s) => (
                <option key={s} value={s}>
                  {t(`review.status.${s}`)}
                </option>
              ))}
            </select>
          </label>
        </div>
      </header>

      {review.error ? <ErrorBanner error={review.error} /> : null}

      {review.isLoading ? (
        <Loading />
      ) : !review.data || review.data.items.length === 0 ? (
        <Empty />
      ) : (
        <table>
          <thead>
            <tr>
              <th>{t("review.headers.id")}</th>
              <th>{t("review.headers.file")}</th>
              <th>{t("review.headers.pages")}</th>
              <th>{t("review.headers.confidence")}</th>
              <th>{t("review.headers.status")}</th>
              <th>{t("review.headers.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {review.data.items.map((item) => (
              <tr key={item.id}>
                <td>{item.id}</td>
                <td>{item.file_name}</td>
                <td>
                  {item.start_page}–{item.end_page} / {item.page_count}
                </td>
                <td>{item.confidence.toFixed(2)}</td>
                <td>
                  <span className={`status-badge review-${item.status}`}>
                    {t(`review.status.${item.status}`)}
                  </span>
                </td>
                <td>
                  <Link to={`/review/${item.id}`}>{t("review.actions.open")}</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
