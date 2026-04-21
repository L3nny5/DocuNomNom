import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useHistory, useReopenHistory } from "../../api/hooks";
import { Empty } from "../../components/ui/Empty";
import { ErrorBanner } from "../../components/ui/ErrorBanner";
import { Loading } from "../../components/ui/Loading";

export function HistoryPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const history = useHistory({ limit: 100 });
  const reopen = useReopenHistory();

  return (
    <section>
      <header className="page-header">
        <h2>{t("history.title")}</h2>
      </header>

      {history.error ? <ErrorBanner error={history.error} /> : null}
      {reopen.error ? <ErrorBanner error={reopen.error} /> : null}

      {history.isLoading ? (
        <Loading />
      ) : !history.data || history.data.items.length === 0 ? (
        <Empty />
      ) : (
        <table>
          <thead>
            <tr>
              <th>{t("history.headers.id")}</th>
              <th>{t("history.headers.file")}</th>
              <th>{t("history.headers.output")}</th>
              <th>{t("history.headers.decision")}</th>
              <th>{t("history.headers.confidence")}</th>
              <th>{t("history.headers.exported")}</th>
              <th>{t("history.headers.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {history.data.items.map((entry) => (
              <tr key={entry.part_id}>
                <td>{entry.part_id}</td>
                <td>{entry.file_name}</td>
                <td>{entry.output_name ?? "—"}</td>
                <td>{entry.decision}</td>
                <td>{entry.confidence.toFixed(2)}</td>
                <td className="muted">{entry.exported_at ?? "—"}</td>
                <td>
                  <button
                    type="button"
                    onClick={() =>
                      reopen.mutate(entry.part_id, {
                        onSuccess: (res) => navigate(`/review/${res.review_item_id}`),
                      })
                    }
                    disabled={reopen.isPending}
                  >
                    {t("history.actions.reopen")}
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
