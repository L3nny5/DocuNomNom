import { useTranslation } from "react-i18next";
import type { ApiError } from "../../api/types";

export function ErrorBanner({ error }: { error: unknown }) {
  const { t } = useTranslation();
  const apiError = error as Partial<ApiError> | undefined;
  const msg = apiError?.message ?? (error instanceof Error ? error.message : t("common.error"));
  return (
    <div className="error-banner" role="alert">
      {msg}
    </div>
  );
}
