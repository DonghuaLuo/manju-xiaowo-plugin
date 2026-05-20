import { useState, useEffect } from "react"
import { PluginSDK } from "xiaowo-sdk"
import { useTranslation } from "@/i18n"

const LICENSE_TAG_TEXT = "License"

type OpenSourceInfo = {
  upstreamName: string
  upstreamAuthor: string
  upstreamUrls: string[]
  upstreamSourceModified: boolean
  licenseName: string
  licenseSpdx: string
  licenseFiles: string[]
  noticeFiles: string[]
  copyrightFiles: string[]
  modificationFiles: string[]
  sourceRequired: boolean
  modificationNotice: string
}

type PluginInfoPayload = {
  open_source?: {
    upstream_name?: string
    upstream_author?: string
    upstream_url?: string[]
    upstream_source_modified?: boolean
    license_name?: string
    license_spdx?: string
    license_files?: string[]
    notice_files?: string[]
    copyright_files?: string[]
    modification_files?: string[]
    source_required?: boolean
    modification_notice?: string
  }
  manifest?: {
    title?: string
    version?: string
    open_source?: PluginInfoPayload["open_source"]
  }
}

const fallbackOpenSourceInfo: OpenSourceInfo = {
  upstreamName: "Unknown",
  upstreamAuthor: "Unknown",
  upstreamUrls: [],
  upstreamSourceModified: false,
  licenseName: "License",
  licenseSpdx: "",
  licenseFiles: [],
  noticeFiles: [],
  copyrightFiles: [],
  modificationFiles: [],
  sourceRequired: false,
  modificationNotice: "当前插件未提供完整的开源与版权说明。",
}

function normalizeOpenSourceInfo(
  raw?: PluginInfoPayload["open_source"]
): OpenSourceInfo {
  if (!raw) return fallbackOpenSourceInfo

  return {
    upstreamName: raw.upstream_name || fallbackOpenSourceInfo.upstreamName,
    upstreamAuthor:
      raw.upstream_author || fallbackOpenSourceInfo.upstreamAuthor,
    upstreamUrls: Array.isArray(raw.upstream_url)
      ? raw.upstream_url.map((item) => item.trim()).filter(Boolean)
      : [],
    upstreamSourceModified:
      typeof raw.upstream_source_modified === "boolean"
        ? raw.upstream_source_modified
        : fallbackOpenSourceInfo.upstreamSourceModified,
    licenseName: raw.license_name || fallbackOpenSourceInfo.licenseName,
    licenseSpdx: raw.license_spdx || fallbackOpenSourceInfo.licenseSpdx,
    licenseFiles: Array.isArray(raw.license_files) ? raw.license_files : [],
    noticeFiles: Array.isArray(raw.notice_files) ? raw.notice_files : [],
    copyrightFiles: Array.isArray(raw.copyright_files)
      ? raw.copyright_files
      : [],
    modificationFiles: Array.isArray(raw.modification_files)
      ? raw.modification_files
      : [],
    sourceRequired:
      typeof raw.source_required === "boolean"
        ? raw.source_required
        : fallbackOpenSourceInfo.sourceRequired,
    modificationNotice:
      raw.modification_notice || fallbackOpenSourceInfo.modificationNotice,
  }
}

function getSourceLabel(tagText: string, index: number) {
  return tagText === "许可" ? `来源 ${index}` : `Source ${index}`
}

export function TitleBar() {
  const { t } = useTranslation()
  const [isMaximized, setIsMaximized] = useState(false)
  const [title, setTitle] = useState("插件")
  const [version, setVersion] = useState("")
  const [showShortcutDialog, setShowShortcutDialog] = useState(false)
  const [showLicenseDialog, setShowLicenseDialog] = useState(false)
  const [shortcutName, setShortcutName] = useState("")
  const [isDark, setIsDark] = useState(false)
  const [hasOpenSource, setHasOpenSource] = useState(false)
  const [openSourceInfo, setOpenSourceInfo] = useState<OpenSourceInfo>(
    fallbackOpenSourceInfo
  )
  const hasIntegrationChanges = Boolean(
    openSourceInfo.modificationNotice.trim() ||
      openSourceInfo.modificationFiles.length > 0
  )

  // 通过 SDK 获取插件信息
  useEffect(() => {
    PluginSDK.getInfo().then((info) => {
      const pluginInfo = info as PluginInfoPayload | undefined
      if (pluginInfo?.manifest) {
        setTitle(pluginInfo.manifest.title || "插件")
        setVersion(pluginInfo.manifest.version || "")
        setShortcutName(pluginInfo.manifest.title || "插件")
        const openSource = pluginInfo.manifest.open_source
        setHasOpenSource(!!openSource)
        if (openSource) {
          setOpenSourceInfo(normalizeOpenSourceInfo(openSource))
        }
      }
    })
    setIsDark(document.documentElement.classList.contains("dark"))
  }, [])

  useEffect(() => {
    if (!showLicenseDialog) return

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setShowLicenseDialog(false)
      }
    }

    window.addEventListener("keydown", handleEscape)
    return () => window.removeEventListener("keydown", handleEscape)
  }, [showLicenseDialog])

  const handleToggleTheme = () => {
    const html = document.documentElement
    const dark = html.classList.toggle("dark")
    setIsDark(dark)
  }

  const handleMinimize = () => PluginSDK.minimize()
  const handleMaximize = () => {
    setIsMaximized(!isMaximized)
    PluginSDK.toggleMaximize()
  }
  const handleClose = () => PluginSDK.close()

  const handleCreateShortcut = async () => {
    try {
      await PluginSDK.createDesktopShortcut(shortcutName)
      setShowShortcutDialog(false)
    } catch (e) {
      console.error("创建快捷方式失败:", e)
    }
  }

  const handleOpenUpstream = async (url: string) => {
    if (!url) return
    try {
      await PluginSDK.shell.open(url)
    } catch (e) {
      console.error("打开上游项目失败:", e)
    }
  }

  const handleOpenLegalDocument = async (
    relativePath?: string,
    displayName?: string
  ) => {
    if (!relativePath) return
    try {
      await PluginSDK.openLegalDocumentViewer(relativePath, displayName)
    } catch (e) {
      console.error("打开法律文件阅读窗口失败:", e)
    }
  }

  const legalTagText = t("titlebar.legalTag")
  const documentSections = [
    {
      title: t("titlebar.legalLicenseFiles"),
      files: openSourceInfo.licenseFiles,
      viewerTitle: openSourceInfo.licenseName || LICENSE_TAG_TEXT,
    },
    {
      title: "COPYRIGHT",
      files: openSourceInfo.copyrightFiles,
      viewerTitle: "COPYRIGHT",
    },
    {
      title: t("titlebar.legalNoticeFiles"),
      files: openSourceInfo.noticeFiles,
      viewerTitle: "NOTICE",
    },
    {
      title: t("titlebar.legalChangeFiles"),
      files: openSourceInfo.modificationFiles,
      viewerTitle: "Changes",
    },
  ].filter((section) => section.files.length > 0)

  return (
    <>
      <div
        className="flex h-10 shrink-0 items-center justify-between pl-3 select-none"
        style={{ WebkitAppRegion: "drag" } as React.CSSProperties}
        onDoubleClick={handleMaximize}
      >
        {/* 左侧: Logo + 标题 + 元信息 */}
        <div className="flex min-w-0 items-center gap-2.5">
          <img
            src="./logo.png"
            alt={title}
            className="size-6 shrink-0 rounded-lg"
          />

          <div className="inline-flex h-5 min-w-0 items-center truncate text-[14px] leading-none font-medium tracking-[0.01em] text-gray-800 dark:text-gray-100">
            {title}
          </div>

          <div className="flex shrink-0 items-center gap-1.5">
            <span className="inline-flex h-5 items-center text-[12px] leading-none text-gray-300 dark:text-gray-600">
              •
            </span>
            <span className="inline-flex h-5 items-center text-[12px] leading-none font-medium text-gray-500 dark:text-gray-400">
              v{version}
            </span>
          </div>

          {hasOpenSource && (
            <button
              onClick={() => setShowLicenseDialog(true)}
              className="inline-flex h-5 shrink-0 cursor-pointer items-center gap-1 rounded-full border border-indigo-200/70 bg-indigo-50/70 px-2 text-[10px] font-medium text-indigo-700 transition-colors hover:border-indigo-300 hover:bg-indigo-100 hover:text-indigo-800 dark:border-indigo-800/50 dark:bg-indigo-950/20 dark:text-indigo-300 dark:hover:border-indigo-700 dark:hover:bg-indigo-900/35 dark:hover:text-indigo-200"
              title={LICENSE_TAG_TEXT}
              aria-label={LICENSE_TAG_TEXT}
              style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
            >
              <span>{LICENSE_TAG_TEXT}</span>
            </button>
          )}
        </div>

        {/* 右侧: 窗口控制按钮 */}
        <div
          className="flex h-10 items-center"
          style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
          onDoubleClick={(e) => e.stopPropagation()}
        >
          {/* 主题切换按钮 */}
          <button
            onClick={handleToggleTheme}
            className="flex h-10 w-10 cursor-pointer items-center justify-center text-gray-500 transition-colors hover:bg-black/5 dark:hover:bg-white/10"
            title={isDark ? "切换浅色主题" : "切换深色主题"}
          >
            {isDark ? (
              <svg
                className="size-4"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
              </svg>
            ) : (
              <svg
                className="size-4"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <circle cx="12" cy="12" r="4" />
                <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
              </svg>
            )}
          </button>
          {/* 创建桌面快捷方式按钮 */}
          <button
            onClick={() => setShowShortcutDialog(true)}
            className="flex h-10 w-10 cursor-pointer items-center justify-center text-gray-500 transition-colors hover:bg-black/5 dark:hover:bg-white/10"
            title={t("titlebar.createShortcut")}
          >
            <svg
              className="size-4"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
              <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
            </svg>
          </button>
          <button
            onClick={handleMinimize}
            className="flex h-10 w-10 cursor-pointer items-center justify-center text-gray-500 transition-colors hover:bg-black/5 dark:hover:bg-white/10"
            title={t("titlebar.minimize")}
          >
            <svg
              className="size-4"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M5 12h14" />
            </svg>
          </button>
          <button
            onClick={handleMaximize}
            className="flex h-10 w-10 cursor-pointer items-center justify-center text-gray-500 transition-colors hover:bg-black/5 dark:hover:bg-white/10"
            title={isMaximized ? t("titlebar.restore") : t("titlebar.maximize")}
          >
            <svg
              className="size-4"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <rect x="5" y="5" width="14" height="14" rx="1" />
            </svg>
          </button>
          <button
            onClick={handleClose}
            className="flex h-10 w-10 cursor-pointer items-center justify-center text-gray-500 transition-colors hover:bg-red-500 hover:text-white"
            title={t("titlebar.close")}
          >
            <svg
              className="size-4"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M6 6l12 12M6 18L18 6" />
            </svg>
          </button>
        </div>
      </div>

      {/* 版权与许可证对话框 */}
      {hasOpenSource && showLicenseDialog && (
        <div
          className="animate-in fade-in fixed inset-0 z-50 flex items-center justify-center bg-black/45 duration-200"
          onClick={() => setShowLicenseDialog(false)}
        >
          <div
            className="animate-in zoom-in-95 fade-in flex max-h-[calc(100vh-2rem)] w-[720px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-2xl border border-gray-200 bg-white/95 shadow-2xl duration-200 dark:border-[#3e3e42] dark:bg-[#252526]"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4 border-b border-gray-200/80 px-6 py-5 dark:border-[#3e3e42]">
              <div className="flex min-w-0 items-start gap-3">
                <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-sky-100 dark:bg-sky-900/30">
                  <svg
                    className="size-5 text-sky-600 dark:text-sky-400"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                  >
                    <circle cx="12" cy="12" r="9" />
                    <path d="M12 10v6" />
                    <path d="M12 7h.01" />
                  </svg>
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">
                      {t("titlebar.openSource")}
                    </h3>
                  </div>
                  <p className="text-xs leading-relaxed text-gray-500 dark:text-gray-400">
                    {t("titlebar.openSourceDesc")}
                  </p>
                </div>
              </div>
              <button
                onClick={() => setShowLicenseDialog(false)}
                className="flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-full text-gray-500 transition-colors hover:bg-black/5 hover:text-gray-700 dark:text-gray-400 dark:hover:bg-white/10 dark:hover:text-gray-200"
                title={t("titlebar.close")}
                aria-label={t("titlebar.close")}
              >
                <svg
                  className="size-4"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <path d="M6 6l12 12M6 18L18 6" />
                </svg>
              </button>
            </div>

            <div className="overflow-y-auto px-6 py-5">
              <div className="space-y-4">
                <div className="space-y-4">
                  <div className="rounded-2xl border border-gray-200 bg-gray-50/80 p-4 dark:border-[#3a3a3d] dark:bg-[#2c2c2c]/80">
                    <div className="text-xs font-medium text-gray-500 dark:text-gray-400">
                      {t("titlebar.legalProject")}
                    </div>
                    <div className="mt-2 text-[17px] leading-snug font-semibold break-words text-gray-900 dark:text-gray-100">
                      {openSourceInfo.upstreamName}
                    </div>

                    <div className="mt-4 space-y-3">
                      <div className="grid gap-1">
                        <div className="text-xs text-gray-500 dark:text-gray-400">
                          {t("titlebar.legalAuthor")}
                        </div>
                        <div className="text-sm leading-relaxed break-words text-gray-800 dark:text-gray-200">
                          {openSourceInfo.upstreamAuthor}
                        </div>
                      </div>

                      <div className="grid gap-1">
                        <div className="text-xs text-gray-500 dark:text-gray-400">
                          {t("titlebar.legalLicense")}
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="inline-flex items-center rounded-full border border-sky-200 bg-sky-50 px-2.5 py-1 text-[11px] font-medium text-sky-700 dark:border-sky-800/60 dark:bg-sky-950/30 dark:text-sky-300">
                            {openSourceInfo.licenseName}
                          </span>
                          {openSourceInfo.licenseSpdx && (
                            <span className="inline-flex items-center rounded-md bg-gray-100 px-2 py-1 font-mono text-[11px] text-gray-600 dark:bg-[#2f2f33] dark:text-gray-300">
                              {openSourceInfo.licenseSpdx}
                            </span>
                          )}
                        </div>
                      </div>

                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className={`inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-medium ${
                            openSourceInfo.upstreamSourceModified
                              ? "border border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-800/60 dark:bg-amber-950/20 dark:text-amber-300"
                              : "border border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800/60 dark:bg-emerald-950/20 dark:text-emerald-300"
                          }`}
                        >
                          {openSourceInfo.upstreamSourceModified
                            ? t("titlebar.legalUpstreamSourceModifiedYes")
                            : t("titlebar.legalUpstreamSourceModifiedNo")}
                        </span>
                        <span
                          className={`inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-medium ${
                            hasIntegrationChanges
                              ? "bg-slate-800 text-white dark:bg-slate-200 dark:text-slate-900"
                              : "border border-gray-200 bg-white text-gray-600 dark:border-[#47474c] dark:bg-[#2f2f33] dark:text-gray-300"
                          }`}
                        >
                          {hasIntegrationChanges
                            ? t("titlebar.legalIntegrationModifiedYes")
                            : t("titlebar.legalIntegrationModifiedNo")}
                        </span>
                      </div>

                      {openSourceInfo.sourceRequired && (
                        <div className="rounded-xl border border-rose-200 bg-rose-50/80 px-3 py-2 text-xs leading-relaxed text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/20 dark:text-rose-300">
                          Source required
                        </div>
                      )}
                    </div>
                  </div>

                  {openSourceInfo.upstreamUrls.length > 0 && (
                    <div className="rounded-2xl border border-gray-200 bg-white/80 p-4 dark:border-[#3a3a3d] dark:bg-[#2c2c2c]/80">
                      <div className="mb-3 text-xs font-medium text-gray-500 dark:text-gray-400">
                        {t("titlebar.legalHomepage")}
                      </div>
                      <div className="space-y-2">
                        {openSourceInfo.upstreamUrls.map((url, index) => (
                          <button
                            key={url}
                            onClick={() => handleOpenUpstream(url)}
                            className="group flex w-full cursor-pointer items-center justify-between gap-3 rounded-xl border border-gray-200 bg-gray-50/70 px-3 py-3 text-left transition-colors hover:border-sky-200 hover:bg-sky-50/80 dark:border-[#343438] dark:bg-[#252526] dark:hover:border-sky-800/60 dark:hover:bg-sky-950/20"
                          >
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="inline-flex shrink-0 items-center rounded-full border border-gray-200 bg-white px-2 py-0.5 text-[10px] font-medium tracking-[0.04em] text-gray-500 uppercase dark:border-[#47474c] dark:bg-[#2f2f33] dark:text-gray-400">
                                  {getSourceLabel(legalTagText, index + 1)}
                                </span>
                                <span className="min-w-0 text-sm font-medium break-all text-sky-700 transition-colors group-hover:text-sky-800 dark:text-sky-400 dark:group-hover:text-sky-300">
                                  {url}
                                </span>
                              </div>
                            </div>
                            <svg
                              className="size-4 shrink-0 text-gray-400 transition-colors group-hover:text-sky-600 dark:group-hover:text-sky-400"
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="2"
                            >
                              <path d="M7 17L17 7" />
                              <path d="M7 7h10v10" />
                            </svg>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                {documentSections.length > 0 && (
                  <div className="rounded-2xl border border-gray-200 bg-white/80 p-4 dark:border-[#3a3a3d] dark:bg-[#2c2c2c]/80">
                    <div className="mb-3 text-xs font-medium text-gray-500 dark:text-gray-400">
                      相关文件
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2">
                      {documentSections.map((section) => (
                        <div
                          key={section.title}
                          className="rounded-xl border border-gray-200 bg-gray-50/70 p-3 dark:border-[#343438] dark:bg-[#252526]"
                        >
                          <div className="mb-2 text-xs text-gray-500 dark:text-gray-400">
                            {section.title}
                          </div>
                          <div className="space-y-1.5">
                            {section.files.map((file) => (
                              <button
                                key={file}
                                onClick={() =>
                                  handleOpenLegalDocument(
                                    file,
                                    section.viewerTitle
                                  )
                                }
                                className="block w-full cursor-pointer rounded-lg px-2 py-1.5 text-left text-sm text-sky-700 transition-colors hover:bg-sky-50 hover:text-sky-800 dark:text-sky-400 dark:hover:bg-sky-950/20 dark:hover:text-sky-300"
                              >
                                <span className="break-all">{file}</span>
                              </button>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {openSourceInfo.modificationNotice && (
                  <div className="rounded-2xl border border-gray-200 bg-white/80 p-4 dark:border-[#3a3a3d] dark:bg-[#2c2c2c]/80">
                    <div className="mb-2 text-xs font-medium text-gray-500 dark:text-gray-400">
                      {t("titlebar.legalModified")}
                    </div>
                    <p className="text-[13px] leading-relaxed text-gray-700 dark:text-gray-300">
                      {openSourceInfo.modificationNotice}
                    </p>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 创建快捷方式对话框 */}
      {showShortcutDialog && (
        <div
          className="animate-in fade-in fixed inset-0 z-50 flex items-center justify-center bg-black/40 duration-200"
          onClick={() => setShowShortcutDialog(false)}
        >
          <div
            className="animate-in zoom-in-95 fade-in w-[340px] rounded-xl bg-white/95 p-6 shadow-2xl duration-200 dark:bg-[#252526]"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-5 flex items-center gap-3">
              <div className="flex size-10 items-center justify-center rounded-full bg-blue-100 dark:bg-blue-900/30">
                <svg
                  className="size-5 text-blue-600 dark:text-blue-400"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
                  <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
                </svg>
              </div>
              <div>
                <h3 className="text-base text-gray-900 dark:text-gray-100">
                  {t("titlebar.createShortcut")}
                </h3>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  {t("titlebar.shortcutTip")}
                </p>
              </div>
            </div>
            <div className="mb-5">
              <label className="mb-1.5 block text-sm text-gray-700 dark:text-gray-300">
                {t("titlebar.shortcutName")}
              </label>
              <input
                type="text"
                value={shortcutName}
                onChange={(e) => setShortcutName(e.target.value)}
                className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2.5 text-sm transition-colors focus:border-blue-500 focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:outline-none dark:border-[#3e3e42] dark:bg-[#2c2c2c] dark:text-[#cccccc] dark:focus:bg-[#2c2c2c]"
                autoFocus
              />
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowShortcutDialog(false)}
                className="cursor-pointer rounded-lg px-4 py-2 text-sm text-gray-600 transition-colors hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-700"
              >
                {t("titlebar.cancel")}
              </button>
              <button
                onClick={handleCreateShortcut}
                className="cursor-pointer rounded-lg bg-blue-500 px-4 py-2 text-sm text-white transition-colors hover:bg-blue-600 active:bg-blue-700"
              >
                {t("titlebar.confirm")}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
