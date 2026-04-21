import i18n from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next } from "react-i18next";
import en from "./locales/en.json";
import de from "./locales/de.json";

export const locales = { en, de } as const;
export type LocaleKey = keyof typeof locales;
export const defaultLocale: LocaleKey = "en";
export const supportedLocales: LocaleKey[] = ["en", "de"];

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      de: { translation: de },
    },
    fallbackLng: defaultLocale,
    supportedLngs: supportedLocales,
    interpolation: { escapeValue: false },
    detection: {
      order: ["localStorage", "navigator"],
      caches: ["localStorage"],
      lookupLocalStorage: "docunomnom.lang",
    },
  });

export default i18n;
