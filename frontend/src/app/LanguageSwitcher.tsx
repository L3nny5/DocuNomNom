import { useTranslation } from "react-i18next";
import { supportedLocales, type LocaleKey } from "../i18n";

export function LanguageSwitcher() {
  const { i18n, t } = useTranslation();
  const current = (i18n.resolvedLanguage ?? i18n.language ?? "en").slice(0, 2) as LocaleKey;
  return (
    <label className="row" style={{ fontSize: "0.85rem" }}>
      <span className="muted">{t("language.label")}:</span>
      <select
        value={current}
        onChange={(e) => {
          void i18n.changeLanguage(e.target.value);
        }}
        aria-label={t("language.label")}
      >
        {supportedLocales.map((code) => (
          <option key={code} value={code}>
            {t(`language.${code}`)}
          </option>
        ))}
      </select>
    </label>
  );
}
