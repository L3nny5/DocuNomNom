import { useTranslation } from "react-i18next";

export function Empty({ message }: { message?: string }) {
  const { t } = useTranslation();
  return <div className="muted">{message ?? t("common.empty")}</div>;
}
