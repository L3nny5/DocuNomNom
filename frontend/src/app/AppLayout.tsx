import { useTranslation } from "react-i18next";
import { NavLink, Outlet } from "react-router-dom";
import { LanguageSwitcher } from "./LanguageSwitcher";

const linkClass = ({ isActive }: { isActive: boolean }) => (isActive ? "active" : undefined);

export function AppLayout() {
  const { t } = useTranslation();
  return (
    <div className="app">
      <aside className="sidebar">
        <div>
          <h1>{t("app.title")}</h1>
          <div className="tagline">{t("app.tagline")}</div>
        </div>
        <nav>
          <NavLink to="/jobs" className={linkClass}>
            {t("nav.jobs")}
          </NavLink>
          <NavLink to="/review" className={linkClass}>
            {t("nav.review")}
          </NavLink>
          <NavLink to="/history" className={linkClass}>
            {t("nav.history")}
          </NavLink>
          <NavLink to="/config" className={linkClass}>
            {t("nav.config")}
          </NavLink>
          <NavLink to="/keywords" className={linkClass}>
            {t("nav.keywords")}
          </NavLink>
        </nav>
        <div className="lang-select">
          <LanguageSwitcher />
        </div>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
