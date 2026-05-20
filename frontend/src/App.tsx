import { useTranslation } from "@/i18n"
import { useBackend } from "@/hooks/useBackend"
import { TitleBar } from "@/components/TitleBar"
import { Sparkles } from "lucide-react"

export default function App() {
  const { t } = useTranslation()
  const { backendReady } = useBackend()

  return (
    <div className="flex h-screen flex-col">
      <TitleBar />
      <div className="flex min-h-0 w-full flex-1 flex-col px-5 pt-2 pb-5">
        {/* Backend Loading Banner */}
        {!backendReady && (
          <div className="animate-fade-in mb-4 rounded-xl border border-amber-200 bg-amber-50 p-3 dark:border-amber-800 dark:bg-amber-950/40">
            <div className="flex items-start gap-2">
              <div className="mt-0.5 h-4 w-4 flex-shrink-0">
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-amber-600 border-t-transparent dark:border-amber-400"></div>
              </div>
              <div className="flex-1">
                <p className="text-xs leading-relaxed text-amber-900 dark:text-amber-300">
                  {t("init.loading")}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Info Banner */}
        {backendReady && (
          <div className="animate-fade-in mb-4 rounded-xl border border-gray-200 bg-white p-3 dark:border-zinc-700 dark:bg-zinc-800">
            <div className="flex items-start gap-2">
              <Sparkles className="mt-0.5 h-4 w-4 flex-shrink-0 text-indigo-600 dark:text-indigo-400" />
              <div className="flex-1">
                <p className="text-xs leading-relaxed text-gray-600 dark:text-gray-400">
                  {t("init.tip")}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Main Content Area - Empty for new development */}
        <div className="flex min-h-0 flex-1 items-center justify-center">
          <p className="text-muted-foreground text-sm">
            {/* 在这里添加你的内容 */}
          </p>
        </div>
      </div>
    </div>
  )
}
