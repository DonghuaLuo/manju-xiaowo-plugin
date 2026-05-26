import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import resourcesToBackend from 'i18next-resources-to-backend';
import { PluginSDK } from 'xiaowo-sdk';
import { BRAND } from '@/branding';

export { useTranslation } from 'react-i18next';

// 按需加载 i18n namespace（issue #489）：
// Vite import.meta.glob 在编译期为每个 (lang, ns) 文件生成独立 chunk；运行时由
// i18next 异步 load。资源仍是 .ts（保留 satisfies Record schema 锁），不是 JSON。
const loaders = import.meta.glob<{ default: Record<string, unknown> }>(
  './{de,en,es,fr,ja,ko,ru,vi,zh,zh-TW}/*.ts',
);

function pathFor(lang: string, ns: string): string {
  return `./${lang}/${ns}.ts`;
}

export const SUPPORTED_LANGUAGES = [
  'zh',
  'zh-TW',
  'en',
  'ja',
  'ko',
  'fr',
  'de',
  'es',
  'ru',
  'vi',
] as const;
export type SupportedLanguage = typeof SUPPORTED_LANGUAGES[number];

const DEFAULT_LANGUAGE: SupportedLanguage = 'zh';

const HOST_LANGUAGE_MAP: Record<string, SupportedLanguage> = {
  zh: 'zh',
  'zh-cn': 'zh',
  'zh-hans': 'zh',
  'zh-tw': 'zh-TW',
  'zh-hant': 'zh-TW',
  'zh-hk': 'zh-TW',
  'zh-mo': 'zh-TW',
  en: 'en',
  'en-us': 'en',
  'en-gb': 'en',
  ja: 'ja',
  'ja-jp': 'ja',
  ko: 'ko',
  'ko-kr': 'ko',
  fr: 'fr',
  'fr-fr': 'fr',
  de: 'de',
  'de-de': 'de',
  es: 'es',
  'es-es': 'es',
  ru: 'ru',
  'ru-ru': 'ru',
  vi: 'vi',
  'vi-vn': 'vi',
};

export const I18N_NAMESPACES = [
  'common',
  'dashboard',
  'errors',
  'templates',
  'assets',
] as const;

// Replace every [[brand]] placeholder in a loaded namespace with the current
// brand name. Done inside the resourcesToBackend loader so it composes with
// on-demand chunk loading (issue #489). We use [[...]] rather than i18next's
// native {{...}} so the value is not treated as a runtime variable (which
// would force every t() call site to pass { brand }).
function applyBrandPlaceholders(value: unknown): unknown {
  if (typeof value === 'string') {
    // Function replacer avoids `$`-sequences in BRAND.name (e.g. "Product$1")
    // being interpreted as String.prototype.replace patterns.
    return value.replace(/\[\[\s*brand\s*\]\]/g, () => BRAND.name);
  }
  if (Array.isArray(value)) {
    return value.map(applyBrandPlaceholders);
  }
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = applyBrandPlaceholders(v);
    }
    return out;
  }
  return value;
}

export function normalizeHostLanguage(language?: string | null): SupportedLanguage {
  if (!language) return DEFAULT_LANGUAGE;
  const normalized = language.trim().replace(/_/g, '-').toLowerCase();
  if (!normalized) return DEFAULT_LANGUAGE;
  return (
    HOST_LANGUAGE_MAP[normalized]
    ?? HOST_LANGUAGE_MAP[normalized.split('-')[0]]
    ?? DEFAULT_LANGUAGE
  );
}

async function getHostLanguage(): Promise<SupportedLanguage> {
  try {
    const info = await PluginSDK.getInfo();
    return normalizeHostLanguage(info?.language);
  } catch (error) {
    console.error('获取插件语言设置失败:', error);
    return DEFAULT_LANGUAGE;
  }
}

// 返回 init Promise，调用方（main.tsx / test setup）await 后再 render，避免首屏闪 key。
export const i18nReady = getHostLanguage().then((lng) =>
  i18n
    .use(
      resourcesToBackend(async (lang: string, ns: string) => {
        const loader = loaders[pathFor(lang, ns)];
        if (!loader) {
          console.warn(`i18n: no resource for ${pathFor(lang, ns)}, falling back`);
          return {};
        }
        const mod = await loader();
        return applyBrandPlaceholders(mod.default) as Record<string, unknown>;
      }),
    )
    .use(initReactI18next)
    .init({
      lng,
      fallbackLng: DEFAULT_LANGUAGE,
      supportedLngs: SUPPORTED_LANGUAGES,
      debug: false,
      interpolation: { escapeValue: false },
      defaultNS: 'common',
      ns: I18N_NAMESPACES,
      partialBundledLanguages: true,
      react: { useSuspense: false },
    }),
);

export default i18n;
