import { useState, useEffect } from "react"
import { PluginSDK } from "xiaowo-sdk"

// 导入所有语言包
import { zhCN } from "./zh-CN"


// 翻译字典类型
export type TranslationKeys = keyof typeof zhCN

// 所有语言包
const translations: Record<string, Record<string, string>> = {
  "zh-CN": zhCN,

}

// 语言映射
function getLangKey(lang: string): string {
  const langMap: Record<string, string> = {
    "zh-CN": "zh-CN",
    "zh-TW": "zh-TW",
    en: "en",
    ja: "ja",
    ko: "ko",
    fr: "fr",
    de: "de",
    es: "es",
    ru: "ru",
    vi: "vi",
  }
  return langMap[lang] || "zh-CN"
}

// 全局语言状态
let currentLang = "zh-CN"
const listeners: Set<() => void> = new Set()

// 初始化语言
export async function initLanguage() {
  try {
    const info = await PluginSDK.getInfo()
    if (info?.language) {
      currentLang = getLangKey(info.language)
      listeners.forEach((fn) => fn())
    }
  } catch (error) {
    console.error("获取语言设置失败:", error)
  }
}

// useTranslation hook
export function useTranslation() {
  const [lang, setLang] = useState(currentLang)

  useEffect(() => {
    const update = () => setLang(currentLang)
    listeners.add(update)
    initLanguage()
    return () => {
      listeners.delete(update)
    }
  }, [])

  const t = (
    key: TranslationKeys,
    params?: Record<string, string | number>
  ): string => {
    let text = translations[lang]?.[key] || translations["zh-CN"][key] || key

    if (params) {
      Object.entries(params).forEach(([k, v]) => {
        text = text.replace(new RegExp(`\\{${k}\\}`, "g"), String(v))
      })
    }

    return text
  }

  return { t, lang }
}
