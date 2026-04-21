import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useConfig, useUpdateConfig } from "../../api/hooks";
import type { ConfigOverrides } from "../../api/types";
import { ErrorBanner } from "../../components/ui/ErrorBanner";
import { Loading } from "../../components/ui/Loading";

type FormState = {
  splitter_keyword_weight: string;
  splitter_layout_weight: string;
  splitter_page_number_weight: string;
  splitter_auto_export_threshold: string;
  splitter_min_pages_per_part: string;
  archive_after_export: "" | "true" | "false";
};

const EMPTY: FormState = {
  splitter_keyword_weight: "",
  splitter_layout_weight: "",
  splitter_page_number_weight: "",
  splitter_auto_export_threshold: "",
  splitter_min_pages_per_part: "",
  archive_after_export: "",
};

function overridesToForm(o: ConfigOverrides | null | undefined): FormState {
  if (!o) return { ...EMPTY };
  return {
    splitter_keyword_weight:
      o.splitter_keyword_weight != null ? String(o.splitter_keyword_weight) : "",
    splitter_layout_weight:
      o.splitter_layout_weight != null ? String(o.splitter_layout_weight) : "",
    splitter_page_number_weight:
      o.splitter_page_number_weight != null ? String(o.splitter_page_number_weight) : "",
    splitter_auto_export_threshold:
      o.splitter_auto_export_threshold != null ? String(o.splitter_auto_export_threshold) : "",
    splitter_min_pages_per_part:
      o.splitter_min_pages_per_part != null ? String(o.splitter_min_pages_per_part) : "",
    archive_after_export:
      o.archive_after_export == null ? "" : o.archive_after_export ? "true" : "false",
  };
}

function formToOverrides(form: FormState): ConfigOverrides {
  const out: ConfigOverrides = {};
  if (form.splitter_keyword_weight !== "")
    out.splitter_keyword_weight = Number(form.splitter_keyword_weight);
  if (form.splitter_layout_weight !== "")
    out.splitter_layout_weight = Number(form.splitter_layout_weight);
  if (form.splitter_page_number_weight !== "")
    out.splitter_page_number_weight = Number(form.splitter_page_number_weight);
  if (form.splitter_auto_export_threshold !== "")
    out.splitter_auto_export_threshold = Number(form.splitter_auto_export_threshold);
  if (form.splitter_min_pages_per_part !== "")
    out.splitter_min_pages_per_part = Number(form.splitter_min_pages_per_part);
  if (form.archive_after_export !== "")
    out.archive_after_export = form.archive_after_export === "true";
  return out;
}

export function ConfigPage() {
  const { t } = useTranslation();
  const config = useConfig();
  const update = useUpdateConfig();
  const [form, setForm] = useState<FormState>(EMPTY);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (config.data) {
      setForm(overridesToForm(config.data.overrides));
    }
  }, [config.data]);

  if (config.isLoading) return <Loading />;
  if (config.error) return <ErrorBanner error={config.error} />;
  if (!config.data) return null;

  const settings = config.data.settings;

  const onChange =
    (key: keyof FormState) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
      setForm((prev) => ({ ...prev, [key]: e.target.value }));
      setSaved(false);
    };

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    update.mutate(formToOverrides(form), { onSuccess: () => setSaved(true) });
  };

  const onReset = () => {
    setForm({ ...EMPTY });
    update.mutate({}, { onSuccess: () => setSaved(true) });
  };

  return (
    <section>
      <header className="page-header">
        <h2>{t("config.title")}</h2>
      </header>

      {update.error ? <ErrorBanner error={update.error} /> : null}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: "1rem",
        }}
      >
        <div className="card">
          <h3 style={{ marginTop: 0 }}>{t("config.effective")}</h3>
          <div className="form-grid">
            <label>{t("config.fields.ai_backend")}</label>
            <span>{settings.ai_backend}</span>
            <label>{t("config.fields.ai_mode")}</label>
            <span>{settings.ai_mode}</span>
            <label>{t("config.fields.ocr_backend")}</label>
            <span>{settings.ocr_backend}</span>
            <label>{t("config.fields.ocr_languages")}</label>
            <span>{settings.ocr_languages.join(", ")}</span>
            <label>{t("config.fields.splitter_keyword_weight")}</label>
            <span>{settings.splitter_keyword_weight}</span>
            <label>{t("config.fields.splitter_layout_weight")}</label>
            <span>{settings.splitter_layout_weight}</span>
            <label>{t("config.fields.splitter_page_number_weight")}</label>
            <span>{settings.splitter_page_number_weight}</span>
            <label>{t("config.fields.splitter_auto_export_threshold")}</label>
            <span>{settings.splitter_auto_export_threshold}</span>
            <label>{t("config.fields.splitter_min_pages_per_part")}</label>
            <span>{settings.splitter_min_pages_per_part}</span>
            <label>{t("config.fields.archive_after_export")}</label>
            <span>{settings.archive_after_export ? t("common.yes") : t("common.no")}</span>
          </div>
        </div>

        <form className="card" onSubmit={onSubmit}>
          <h3 style={{ marginTop: 0 }}>{t("config.overrides")}</h3>
          <p className="muted" style={{ marginTop: 0 }}>
            {t("config.overridesNote")}
          </p>
          <div className="form-grid">
            <label htmlFor="kw">{t("config.fields.splitter_keyword_weight")}</label>
            <input
              id="kw"
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={form.splitter_keyword_weight}
              onChange={onChange("splitter_keyword_weight")}
            />
            <label htmlFor="lw">{t("config.fields.splitter_layout_weight")}</label>
            <input
              id="lw"
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={form.splitter_layout_weight}
              onChange={onChange("splitter_layout_weight")}
            />
            <label htmlFor="pw">{t("config.fields.splitter_page_number_weight")}</label>
            <input
              id="pw"
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={form.splitter_page_number_weight}
              onChange={onChange("splitter_page_number_weight")}
            />
            <label htmlFor="th">{t("config.fields.splitter_auto_export_threshold")}</label>
            <input
              id="th"
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={form.splitter_auto_export_threshold}
              onChange={onChange("splitter_auto_export_threshold")}
            />
            <label htmlFor="mp">{t("config.fields.splitter_min_pages_per_part")}</label>
            <input
              id="mp"
              type="number"
              min={1}
              step={1}
              value={form.splitter_min_pages_per_part}
              onChange={onChange("splitter_min_pages_per_part")}
            />
            <label htmlFor="arch">{t("config.fields.archive_after_export")}</label>
            <select
              id="arch"
              value={form.archive_after_export}
              onChange={onChange("archive_after_export")}
            >
              <option value="">—</option>
              <option value="true">{t("common.yes")}</option>
              <option value="false">{t("common.no")}</option>
            </select>
          </div>
          <div className="row" style={{ marginTop: "1rem" }}>
            <button type="submit" className="primary" disabled={update.isPending}>
              {t("common.save")}
            </button>
            <button type="button" onClick={onReset} disabled={update.isPending}>
              {t("config.reset")}
            </button>
            {saved && <span className="muted">{t("config.saved")}</span>}
          </div>
        </form>
      </div>
    </section>
  );
}
