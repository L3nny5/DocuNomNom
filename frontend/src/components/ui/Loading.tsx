import { useTranslation } from "react-i18next";

export function Loading() {
  const { t } = useTranslation();
  return (
    <div className="muted" role="status">
      {t("common.loading")}
    </div>
  );
}
