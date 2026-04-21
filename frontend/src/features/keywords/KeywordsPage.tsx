import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useCreateKeyword, useDeleteKeyword, useKeywords, useUpdateKeyword } from "../../api/hooks";
import type { Keyword } from "../../api/types";
import { Empty } from "../../components/ui/Empty";
import { ErrorBanner } from "../../components/ui/ErrorBanner";
import { Loading } from "../../components/ui/Loading";

export function KeywordsPage() {
  const { t } = useTranslation();
  const list = useKeywords();
  const create = useCreateKeyword();
  const update = useUpdateKeyword();
  const remove = useDeleteKeyword();

  const [term, setTerm] = useState("");
  const [locale, setLocale] = useState("en");
  const [weight, setWeight] = useState(1);

  const onAdd = (e: React.FormEvent) => {
    e.preventDefault();
    if (term.trim().length === 0) return;
    create.mutate(
      { term: term.trim(), locale, weight },
      {
        onSuccess: () => {
          setTerm("");
          setWeight(1);
        },
      },
    );
  };

  return (
    <section>
      <header className="page-header">
        <h2>{t("keywords.title")}</h2>
      </header>

      {(list.error || create.error || update.error || remove.error) && (
        <ErrorBanner error={list.error ?? create.error ?? update.error ?? remove.error} />
      )}

      <form className="card" onSubmit={onAdd} style={{ marginBottom: "1rem" }}>
        <div className="row" style={{ flexWrap: "wrap" }}>
          <input
            placeholder={t("keywords.addPlaceholder")}
            value={term}
            onChange={(e) => setTerm(e.target.value)}
            aria-label={t("keywords.addPlaceholder")}
          />
          <label className="row">
            <span className="muted">{t("keywords.locale")}:</span>
            <input value={locale} onChange={(e) => setLocale(e.target.value)} size={4} />
          </label>
          <label className="row">
            <span className="muted">{t("keywords.weight")}:</span>
            <input
              type="number"
              min={0}
              max={10}
              step={0.1}
              value={weight}
              onChange={(e) => setWeight(Number(e.target.value))}
              style={{ width: "5rem" }}
            />
          </label>
          <button
            type="submit"
            className="primary"
            disabled={create.isPending || term.trim().length === 0}
          >
            {t("common.add")}
          </button>
        </div>
      </form>

      {list.isLoading ? (
        <Loading />
      ) : !list.data || list.data.length === 0 ? (
        <Empty />
      ) : (
        <table>
          <thead>
            <tr>
              <th>{t("keywords.headers.term")}</th>
              <th>{t("keywords.headers.locale")}</th>
              <th>{t("keywords.headers.enabled")}</th>
              <th>{t("keywords.headers.weight")}</th>
              <th>{t("keywords.headers.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {list.data.map((kw) => (
              <KeywordRow
                key={kw.id}
                keyword={kw}
                onToggle={(next) =>
                  update.mutate({
                    id: kw.id,
                    body: {
                      term: kw.term,
                      locale: kw.locale,
                      enabled: next,
                      weight: kw.weight,
                    },
                  })
                }
                onDelete={() => {
                  if (window.confirm(t("keywords.deleteConfirm", { term: kw.term }))) {
                    remove.mutate(kw.id);
                  }
                }}
              />
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function KeywordRow({
  keyword,
  onToggle,
  onDelete,
}: {
  keyword: Keyword;
  onToggle: (next: boolean) => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  return (
    <tr>
      <td>{keyword.term}</td>
      <td>{keyword.locale}</td>
      <td>
        <input
          type="checkbox"
          checked={keyword.enabled}
          onChange={(e) => onToggle(e.target.checked)}
          aria-label={t("keywords.headers.enabled")}
        />
      </td>
      <td>{keyword.weight}</td>
      <td>
        <button className="danger" onClick={onDelete}>
          {t("common.delete")}
        </button>
      </td>
    </tr>
  );
}
