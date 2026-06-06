
import { useEffect, useMemo } from "react";
import { Link, useLocation, useSearch } from "wouter";
import {
  AlertTriangle,
  BarChart3,
  Bot,
  ChevronLeft,
  Film,
  LineChart,
  Plug,
  Scissors,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useConfigStatusStore } from "@/stores/config-status-store";
import { AgentConfigTab } from "./AgentConfigTab";
import { MediaModelSection } from "./settings/MediaModelSection";
import { ProviderSection } from "./ProviderSection";
import { QualityAnalysisSection } from "./settings/QualityAnalysisSection";
import { ScriptSplittingTemplatesSection } from "./settings/ScriptSplittingTemplatesSection";
import { UsageStatsSection } from "./settings/UsageStatsSection";

// 全局设置页 · "Control Booth"
// 延续 Darkroom 美学：editorial 大标题 + mono kicker + 分组侧栏 + accent 紫色高亮。

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type SettingsSection = "agent" | "providers" | "media" | "script-splitting" | "quality" | "usage";

interface SectionDef {
  id: SettingsSection;
  labelKey?: string;
  label?: string;
  Icon: React.ComponentType<{ className?: string }>;
}

interface SectionGroup {
  kicker: string;
  items: SectionDef[];
}

// ---------------------------------------------------------------------------
// Sidebar navigation config — grouped by purpose
// ---------------------------------------------------------------------------

const SECTION_GROUPS: SectionGroup[] = [
  {
    kicker: "Configuration",
    items: [
      { id: "providers", labelKey: "dashboard:providers", Icon: Plug },
      { id: "agent", labelKey: "dashboard:agents", Icon: Bot },
      { id: "media", labelKey: "dashboard:models", Icon: Film },
      { id: "script-splitting", label: "拆分方案", Icon: Scissors },
    ],
  },
  {
    kicker: "Insight",
    items: [
      { id: "quality", labelKey: "dashboard:quality_analysis", Icon: LineChart },
      { id: "usage", labelKey: "dashboard:usage", Icon: BarChart3 },
    ],
  },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function SystemConfigPage() {
  const { t } = useTranslation(["common", "dashboard"]);
  const [location, navigate] = useLocation();
  const search = useSearch();

  const activeSection = useMemo((): SettingsSection => {
    const section = new URLSearchParams(search).get("section");
    if (section === "agent") return "agent";
    if (section === "media") return "media";
    if (section === "script-splitting") return "script-splitting";
    if (section === "quality") return "quality";
    if (section === "usage") return "usage";
    return "providers";
  }, [search]);

  const setActiveSection = (section: SettingsSection) => {
    const params = new URLSearchParams(search);
    params.set("section", section);
    navigate(`${location}?${params.toString()}`, { replace: true });
  };

  const configIssues = useConfigStatusStore((s) => s.issues);
  const fetchConfigStatus = useConfigStatusStore((s) => s.fetch);

  useEffect(() => {
    void fetchConfigStatus();
  }, [fetchConfigStatus]);

  // -------------------------------------------------------------------------
  // Main render
  // -------------------------------------------------------------------------

  return (
    <div
      className="relative flex h-screen flex-col text-text"
      style={
        {
          background:
            "radial-gradient(900px 480px at 8% -10%, oklch(0.32 0.05 295 / 0.22), transparent 55%), radial-gradient(800px 460px at 100% 110%, oklch(0.26 0.04 260 / 0.22), transparent 55%), linear-gradient(180deg, var(--color-bg-grad-a), var(--color-bg-grad-b))",
        }
      }
    >
      {/* ─── Top bar ─── */}
      <header
        className="shrink-0 sticky top-0 z-30"
        style={{
          background:
            "linear-gradient(180deg, oklch(0.20 0.011 265 / 0.55), oklch(0.15 0.010 265 / 0.45))",
          backdropFilter: "blur(28px) saturate(1.5)",
          WebkitBackdropFilter: "blur(28px) saturate(1.5)",
          borderBottom: "1px solid var(--color-hairline)",
          boxShadow:
            "inset 0 1px 0 oklch(1 0 0 / 0.05), 0 6px 24px -12px oklch(0 0 0 / 0.45)",
        }}
      >
        <div className="mx-auto flex max-w-[1320px] items-center gap-5 px-6 py-4">
          <Link
            href="/app/projects"
            className="inline-flex items-center gap-1.5 rounded-md border border-hairline-soft bg-bg-grad-a/45 px-2.5 py-1.5 text-[12px] text-text-3 transition-colors hover:border-hairline hover:bg-bg-grad-a hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            aria-label={t("common:back")}
          >
            <ChevronLeft className="h-3.5 w-3.5" />
            <span>{t("common:back")}</span>
          </Link>
          <span aria-hidden className="h-5 w-px bg-hairline-soft" />
          <div className="min-w-0 flex-1">
            <div className="font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-accent-2">
              Control Booth
            </div>
            <h1
              className="font-editorial mt-0.5"
              style={{
                fontWeight: 400,
                fontSize: 26,
                lineHeight: 1.05,
                letterSpacing: "-0.012em",
                color: "var(--color-text)",
              }}
            >
              {t("common:settings")}
              <span className="ml-2 align-middle font-mono text-[11.5px] font-medium uppercase tracking-[0.08em] text-text-3">
                {t("dashboard:system_config_title")}
              </span>
            </h1>
          </div>
        </div>
      </header>

      {/* ─── Body: sidebar + content ─── */}
      <div className="min-h-0 flex-1 overflow-hidden">
        <div className="mx-auto flex h-full w-full max-w-[1320px] px-6">
          {/* Sidebar */}
          <nav
            aria-label={t("common:settings")}
            className="w-[220px] shrink-0 overflow-y-auto border-l border-r border-hairline-soft px-3 py-5"
            style={{ background: "oklch(0.16 0.010 265 / 0.45)" }}
          >
            {SECTION_GROUPS.map((group, gi) => (
              <div key={group.kicker} className={gi > 0 ? "mt-5" : undefined}>
                <div className="mb-2 px-3 font-mono text-[9.5px] font-bold uppercase tracking-[0.16em] text-text-4">
                  {group.kicker}
                </div>
                {group.items.map(({ id, labelKey, label, Icon }) => {
                  const isActive = activeSection === id;
                  const hasIssue =
                    (id === "providers" || id === "agent" || id === "media") &&
                    configIssues.length > 0;

                  return (
                    <button
                      key={id}
                      type="button"
                      onClick={() => setActiveSection(id)}
                      aria-current={isActive ? "page" : undefined}
                      aria-pressed={isActive}
                      className={
                        "group relative mb-0.5 flex w-full items-center gap-2.5 rounded-[8px] border px-3 py-2 text-left text-[12.5px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent " +
                        (isActive
                          ? "border-accent/35 bg-accent-dim text-text shadow-[inset_0_1px_0_oklch(1_0_0_/_0.04),0_0_22px_-10px_var(--color-accent-glow)]"
                          : "border-transparent text-text-3 hover:border-hairline-soft hover:bg-bg-grad-a/55 hover:text-text")
                      }
                    >
                      {/* Active rail — thin accent bar on the left edge */}
                      <span
                        aria-hidden
                        className="absolute left-0 top-1.5 bottom-1.5 w-[2px] rounded-r-[2px] transition-opacity"
                        style={{
                          background:
                            "linear-gradient(180deg, var(--color-accent-2), var(--color-accent))",
                          opacity: isActive ? 1 : 0,
                        }}
                      />
                      <Icon
                        className={
                          "h-3.5 w-3.5 shrink-0 " +
                          (isActive ? "text-accent-2" : "text-text-3 group-hover:text-text-2")
                        }
                      />
                      <span className="flex-1 truncate">{labelKey ? t(labelKey) : label}</span>
                      {hasIssue && (
                        <span
                          aria-label={t("dashboard:config_incomplete")}
                          className="grid h-4 w-4 place-items-center rounded-full"
                          style={{
                            background: "oklch(0.30 0.10 25 / 0.22)",
                            color: "var(--color-warm-bright)",
                          }}
                        >
                          <AlertTriangle className="h-2.5 w-2.5" />
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            ))}
          </nav>

          {/* Content area — main is the scroll container inside the centered settings board. */}
          <main className="min-w-0 flex-1 overflow-y-auto border-r border-hairline-soft">
            {activeSection === "providers" ? (
              <ProviderSection />
            ) : (
              <div className="w-full px-8 py-8">
                {/* Quick alert for config issues */}
                {configIssues.length > 0 && (
                  <div
                    className="mb-7 rounded-[10px] border p-4"
                    style={{
                      borderColor: "var(--color-warm-ring)",
                      background: "var(--color-warm-tint)",
                    }}
                  >
                    <div className="mb-2 flex items-center gap-2 font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-warm-bright">
                      <AlertTriangle className="h-3.5 w-3.5" />
                      {t("dashboard:config_issues")}
                    </div>
                    <p className="mb-2.5 text-[12px] leading-[1.55] text-text-2">
                      {t("dashboard:config_issues_hint")}
                    </p>
                    <ul className="space-y-1.5">
                      {configIssues.map((issue, idx) => (
                        <li
                          key={idx}
                          className="flex items-start gap-2 text-[12px] text-text-3"
                        >
                          <span
                            aria-hidden
                            className="mt-1.5 h-[5px] w-[5px] shrink-0 rounded-full"
                            style={{ background: "var(--color-warm)" }}
                          />
                          {t(`dashboard:${issue.label}`)}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {activeSection === "agent" && <AgentConfigTab visible />}
                {activeSection === "media" && <MediaModelSection />}
                {activeSection === "script-splitting" && <ScriptSplittingTemplatesSection />}
                {activeSection === "quality" && <QualityAnalysisSection />}
                {activeSection === "usage" && <UsageStatsSection />}
              </div>
            )}
          </main>
        </div>
      </div>
    </div>
  );
}
