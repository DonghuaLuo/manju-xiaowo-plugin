import { afterAll, describe, expect, it } from "vitest";

import i18n, {
  I18N_NAMESPACES,
  SUPPORTED_LANGUAGES,
  normalizeHostLanguage,
} from "./index";

const HOST_LANGUAGE_SET = [
  "zh",
  "zh-TW",
  "en",
  "ja",
  "ko",
  "fr",
  "de",
  "es",
  "ru",
  "vi",
] as const;

const ADDED_LANGUAGE_SET = [
  "zh-TW",
  "ja",
  "ko",
  "fr",
  "de",
  "es",
  "ru",
] as const;

const LOCALIZED_SAMPLES = [
  { ns: "common", key: "settings" },
  { ns: "dashboard", key: "projects" },
  { ns: "assets", key: "library_title" },
  { ns: "templates", key: "default_hint" },
] as const;

describe("manju i18n language support", () => {
  afterAll(async () => {
    await i18n.changeLanguage("zh");
  });

  it("matches the host/plugin language set", () => {
    expect(SUPPORTED_LANGUAGES).toEqual(HOST_LANGUAGE_SET);
  });

  it("normalizes host language codes", () => {
    expect(normalizeHostLanguage("zh_CN")).toBe("zh");
    expect(normalizeHostLanguage("zh-CN")).toBe("zh");
    expect(normalizeHostLanguage("zh_TW")).toBe("zh-TW");
    expect(normalizeHostLanguage("zh-Hant")).toBe("zh-TW");
    expect(normalizeHostLanguage("ja_JP")).toBe("ja");
    expect(normalizeHostLanguage("ko-KR")).toBe("ko");
    expect(normalizeHostLanguage("fr_CA")).toBe("fr");
    expect(normalizeHostLanguage("de_DE")).toBe("de");
    expect(normalizeHostLanguage("es-MX")).toBe("es");
    expect(normalizeHostLanguage("ru_RU")).toBe("ru");
    expect(normalizeHostLanguage("vi_VN")).toBe("vi");
    expect(normalizeHostLanguage("pt_BR")).toBe("zh");
  });

  it("loads every namespace for every supported language", async () => {
    for (const lang of SUPPORTED_LANGUAGES) {
      await i18n.changeLanguage(lang);
      await i18n.loadNamespaces([...I18N_NAMESPACES]);

      expect(i18n.exists("settings", { ns: "common" })).toBe(true);
      expect(i18n.exists("projects", { ns: "dashboard" })).toBe(true);
      expect(i18n.exists("library_title", { ns: "assets" })).toBe(true);
      expect(i18n.exists("category.live", { ns: "templates" })).toBe(true);
    }
  });

  it("uses localized resources instead of aliasing new packs to English or Simplified Chinese", async () => {
    await i18n.changeLanguage("en");
    await i18n.loadNamespaces([...I18N_NAMESPACES]);
    const englishSamples = new Map(
      LOCALIZED_SAMPLES.map(({ ns, key }) => [`${ns}:${key}`, i18n.t(key, { ns })]),
    );

    await i18n.changeLanguage("zh");
    await i18n.loadNamespaces([...I18N_NAMESPACES]);
    const simplifiedSamples = new Map(
      LOCALIZED_SAMPLES.map(({ ns, key }) => [`${ns}:${key}`, i18n.t(key, { ns })]),
    );

    for (const lang of ADDED_LANGUAGE_SET) {
      await i18n.changeLanguage(lang);
      await i18n.loadNamespaces([...I18N_NAMESPACES]);

      for (const { ns, key } of LOCALIZED_SAMPLES) {
        const sampleKey = `${ns}:${key}`;
        const translated = i18n.t(key, { ns });

        expect(translated).not.toBe(key);
        expect(translated).not.toBe(englishSamples.get(sampleKey));
        if (lang === "zh-TW") {
          expect(translated).not.toBe(simplifiedSamples.get(sampleKey));
        }
      }
    }
  });
});
