import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";
import { useFinalizeReview, usePutMarkers, useReviewItem } from "../../api/hooks";
import type { MarkerInput, ReviewMarker } from "../../api/types";
import { ErrorBanner } from "../../components/ui/ErrorBanner";
import { Loading } from "../../components/ui/Loading";

interface MarkerEditorProps {
  itemId: number;
  startPage: number;
  endPage: number;
  initialMarkers: ReviewMarker[];
}

function MarkerEditor({ itemId, startPage, endPage, initialMarkers }: MarkerEditorProps) {
  const { t } = useTranslation();
  const put = usePutMarkers(itemId);
  const [pages, setPages] = useState<number[]>(() =>
    initialMarkers.filter((m) => m.kind === "start").map((m) => m.page_no),
  );
  const [pageInput, setPageInput] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Reset when the item id changes (different item navigated to).
  useEffect(() => {
    setPages(initialMarkers.filter((m) => m.kind === "start").map((m) => m.page_no));
  }, [itemId, initialMarkers]);

  const sortedPages = useMemo(() => [...new Set(pages)].sort((a, b) => a - b), [pages]);

  const handleAdd = () => {
    setError(null);
    const n = Number(pageInput);
    if (!Number.isInteger(n) || n < startPage || n > endPage) {
      setError(t("review.detail.invalidPage", { start: startPage, end: endPage }));
      return;
    }
    if (n === startPage) {
      // Implicit start; no need to store explicitly.
      setPageInput("");
      return;
    }
    if (sortedPages.includes(n)) {
      setPageInput("");
      return;
    }
    setPages([...sortedPages, n]);
    setPageInput("");
  };

  const handleRemove = (page: number) => {
    setPages(sortedPages.filter((p) => p !== page));
  };

  const handleSave = () => {
    const payload: MarkerInput[] = sortedPages.map((p) => ({ page_no: p, kind: "start" }));
    put.mutate(payload);
  };

  return (
    <div className="card" style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
      <h3 style={{ margin: 0 }}>{t("review.detail.markers")}</h3>
      <p className="muted" style={{ margin: 0, fontSize: "0.85rem" }}>
        {t("review.detail.markersHint", { start: startPage, end: endPage })}
      </p>
      <ul
        style={{
          listStyle: "none",
          padding: 0,
          margin: 0,
          display: "flex",
          flexWrap: "wrap",
          gap: "0.4rem",
        }}
      >
        <li>
          <span className="status-badge" title={t("review.detail.implicitStart") ?? ""}>
            {t("review.detail.firstPageImplicit", { page: startPage })}
          </span>
        </li>
        {sortedPages.map((p) => (
          <li key={p} className="row" style={{ gap: "0.25rem" }}>
            <span className="status-badge review-marker">
              {t("review.detail.pageLabel", { page: p })}
            </span>
            <button
              type="button"
              aria-label={t("review.detail.removeMarker", { page: p }) ?? undefined}
              onClick={() => handleRemove(p)}
              style={{ padding: "0.1rem 0.4rem", fontSize: "0.8rem" }}
            >
              ×
            </button>
          </li>
        ))}
      </ul>
      <div className="row" style={{ gap: "0.4rem" }}>
        <input
          type="number"
          min={startPage}
          max={endPage}
          value={pageInput}
          onChange={(e) => setPageInput(e.target.value)}
          placeholder={t("review.detail.pagePlaceholder") ?? undefined}
          aria-label={t("review.detail.pagePlaceholder") ?? undefined}
          style={{ width: "120px" }}
        />
        <button type="button" onClick={handleAdd}>
          {t("review.detail.addMarker")}
        </button>
        <button type="button" className="primary" onClick={handleSave} disabled={put.isPending}>
          {t("review.detail.saveMarkers")}
        </button>
      </div>
      {error ? <div className="error-banner">{error}</div> : null}
      {put.error ? <ErrorBanner error={put.error} /> : null}
      {put.isSuccess ? <div className="muted">{t("review.detail.markersSaved")}</div> : null}
    </div>
  );
}

export function ReviewDetailPage() {
  const { t } = useTranslation();
  const params = useParams<{ id: string }>();
  const id = params.id ? Number(params.id) : null;
  const detail = useReviewItem(id);
  const finalize = useFinalizeReview(id ?? 0);

  return (
    <section>
      <header className="page-header">
        <h2>
          <Link to="/review">{t("nav.review")}</Link> <span className="muted">/ #{id}</span>
        </h2>
      </header>

      {detail.error ? <ErrorBanner error={detail.error} /> : null}
      {finalize.error ? <ErrorBanner error={finalize.error} /> : null}
      {finalize.isSuccess ? (
        <div className="card" style={{ marginBottom: "1rem" }}>
          {t("review.detail.finalizedSummary", {
            count: finalize.data?.derived_count ?? 0,
            status: finalize.data?.job_status ?? "",
          })}
        </div>
      ) : null}

      {detail.isLoading || !detail.data ? (
        <Loading />
      ) : (
        <div className="review-grid">
          <div className="review-pdf card" style={{ padding: 0, overflow: "hidden" }}>
            <iframe
              title={t("review.detail.pdfTitle") ?? "PDF"}
              src={detail.data.pdf_url}
              style={{ width: "100%", height: "75vh", border: 0 }}
            />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
            <div className="card">
              <div className="form-grid">
                <label>{t("review.detail.file")}</label>
                <span>{detail.data.item.file_name}</span>
                <label>{t("review.detail.pageRange")}</label>
                <span>
                  {detail.data.item.start_page}–{detail.data.item.end_page} /{" "}
                  {detail.data.item.page_count}
                </span>
                <label>{t("review.detail.status")}</label>
                <span className={`status-badge review-${detail.data.item.status}`}>
                  {t(`review.status.${detail.data.item.status}`)}
                </span>
                <label>{t("review.detail.confidence")}</label>
                <span>{detail.data.item.confidence.toFixed(2)}</span>
              </div>
            </div>

            <div className="card">
              <h3 style={{ marginTop: 0 }}>{t("review.detail.proposals")}</h3>
              {detail.data.proposals.length === 0 ? (
                <div className="muted">{t("review.detail.noProposals")}</div>
              ) : (
                <ul style={{ paddingLeft: "1.2rem", margin: 0 }}>
                  {detail.data.proposals.map((p) => (
                    <li key={p.id}>
                      <strong>
                        {p.start_page}–{p.end_page}
                      </strong>{" "}
                      <span className="muted">
                        ({p.source}, {p.reason_code}, {p.confidence.toFixed(2)})
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {id !== null ? (
              <MarkerEditor
                itemId={id}
                startPage={detail.data.item.start_page}
                endPage={detail.data.item.end_page}
                initialMarkers={detail.data.markers}
              />
            ) : null}

            <div className="card">
              <button
                type="button"
                className="primary"
                disabled={finalize.isPending || detail.data.item.status === "done"}
                onClick={() => finalize.mutate()}
              >
                {t("review.detail.finalize")}
              </button>
              {detail.data.item.status === "done" ? (
                <p className="muted" style={{ marginBottom: 0 }}>
                  {t("review.detail.alreadyFinalized")}
                </p>
              ) : null}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
