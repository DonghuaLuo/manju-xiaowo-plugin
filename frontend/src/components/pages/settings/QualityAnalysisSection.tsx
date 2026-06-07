import { useEffect, useMemo, useState, type ComponentType, type CSSProperties } from "react";
import { useTranslation } from "react-i18next";
import { BarChart3, Layers3, Loader2, Star, Trophy } from "lucide-react";
import { API, type QualityAnalysisGroupItem, type QualityAnalysisResponse } from "@/api";
import { CARD_STYLE } from "@/components/ui/darkroom-tokens";
import { errMsg } from "@/utils/async";

const EDITORIAL_HEADING_STYLE: CSSProperties = {
  fontWeight: 400,
  fontSize: 22,
  lineHeight: 1.1,
  letterSpacing: 0,
  color: "var(--color-text)",
};

const KPI_VALUE_STYLE: CSSProperties = {
  fontSize: 24,
  fontWeight: 400,
  letterSpacing: 0,
  lineHeight: 1.1,
  color: "var(--color-text)",
};

function scoreText(score: number | null | undefined): string {
  return typeof score === "number" ? `${score.toFixed(1)}/5` : "-";
}

function scoreTone(score: number | null | undefined): string {
  if (typeof score !== "number") return "text-text-4";
  if (score >= 4.2) return "text-good";
  if (score >= 3.4) return "text-accent-2";
  if (score >= 2.6) return "text-warm";
  return "text-danger-2";
}

function dimensionLabel(
  t: (key: string, options?: Record<string, unknown>) => string,
  key: string,
): string {
  const fallback: Record<string, string> = {
    character_consistency: "角色一致性",
    composition: "构图质量",
    motion_naturalness: "动作自然度",
    prompt_faithfulness: "提示词贴合度",
  };
  return t(`quality_dimension_${key}`, { defaultValue: fallback[key] ?? key });
}

function groupLabel(item: QualityAnalysisGroupItem): string {
  return String(item.label || item.project_title || item.key || "");
}

interface KpiCardProps {
  label: string;
  value: string;
  sub?: string;
  Icon: ComponentType<{ className?: string }>;
}

function KpiCard({ label, value, sub, Icon }: KpiCardProps) {
  return (
    <div className="rounded-[10px] border border-hairline px-5 py-4" style={CARD_STYLE}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="font-mono text-[9.5px] font-bold uppercase tracking-[0.18em] text-text-4">
          {label}
        </div>
        <Icon className="h-4 w-4 text-accent-2" aria-hidden />
      </div>
      <div className="font-editorial" style={KPI_VALUE_STYLE}>
        {value}
      </div>
      {sub ? <div className="mt-1 text-[11.5px] text-text-3">{sub}</div> : null}
    </div>
  );
}

interface AnalysisTableProps {
  title: string;
  subtitle: string;
  items: QualityAnalysisGroupItem[];
  emptyText: string;
  secondaryLabel?: string;
  secondaryValue?: (item: QualityAnalysisGroupItem) => string | null;
}

function AnalysisTable({
  title,
  subtitle,
  items,
  emptyText,
  secondaryLabel,
  secondaryValue,
}: AnalysisTableProps) {
  const { t } = useTranslation("dashboard");
  const rows = items.slice(0, 10);

  return (
    <section className="rounded-[10px] border border-hairline p-5" style={CARD_STYLE}>
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h4 className="m-0 text-[14px] font-semibold text-text">{title}</h4>
          <p className="mt-1 text-[12px] leading-[1.5] text-text-3">{subtitle}</p>
        </div>
      </div>
      {rows.length === 0 ? (
        <div className="rounded-[8px] border border-hairline-soft bg-bg-grad-a/45 px-4 py-6 text-center text-[12.5px] text-text-3">
          {emptyText}
        </div>
      ) : (
        <div className="overflow-hidden rounded-[8px] border border-hairline-soft">
          <table className="w-full border-collapse text-left text-[12px]">
            <thead className="bg-bg-grad-a/55 font-mono text-[9.5px] uppercase tracking-[0.14em] text-text-4">
              <tr>
                <th className="px-3 py-2 font-bold">{t("quality_analysis_column_name", { defaultValue: "对象" })}</th>
                {secondaryLabel ? <th className="px-3 py-2 font-bold">{secondaryLabel}</th> : null}
                <th className="px-3 py-2 text-right font-bold">{t("quality_analysis_column_count", { defaultValue: "样本" })}</th>
                <th className="px-3 py-2 text-right font-bold">{t("quality_analysis_column_score", { defaultValue: "评分" })}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((item) => (
                <tr key={item.key} className="border-t border-hairline-soft">
                  <td className="min-w-0 px-3 py-2.5 text-text">
                      <div className="truncate">{groupLabel(item)}</div>
                    {item.provider && item.model && !secondaryValue ? (
                      <div className="mt-0.5 truncate font-mono text-[10px] text-text-4">
                        {String(item.provider)} / {String(item.model)}
                      </div>
                    ) : null}
                  </td>
                  {secondaryValue ? (
                    <td className="px-3 py-2.5 font-mono text-[11px] text-text-3">
                      {secondaryValue(item) ?? "-"}
                    </td>
                  ) : null}
                  <td className="px-3 py-2.5 text-right font-mono tabular-nums text-text-3">
                    {item.count}
                  </td>
                  <td className={`px-3 py-2.5 text-right font-mono tabular-nums font-semibold ${scoreTone(item.average_rating)}`}>
                    {scoreText(item.average_rating)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function QualityAnalysisSection() {
  const { t } = useTranslation("dashboard");
  const [analysis, setAnalysis] = useState<QualityAnalysisResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    API.getQualityAnalysis()
      .then((res) => {
        if (!cancelled) {
          setAnalysis(res);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setAnalysis(null);
          setError(errMsg(err));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const dimensionRows = useMemo(
    () => (analysis?.dimension_averages ?? []).slice().sort((a, b) => (a.average_rating ?? 0) - (b.average_rating ?? 0)),
    [analysis],
  );
  const modelRows = analysis?.groups.provider_model ?? [];
  const resolutionRows = analysis?.groups.resolution ?? [];
  const serviceTierRows = analysis?.groups.service_tier ?? [];
  const continuityRows = analysis?.groups.video_continuity_effective_policy ?? analysis?.groups.video_continuity_policy ?? [];
  const storyboardModeRows = analysis?.groups.final_generation_mode ?? [];
  const sourceStoryboardModelRows = analysis?.groups.source_storyboard_provider_model ?? [];
  const referenceImageCountRows = analysis?.groups.reference_image_count ?? [];
  const projectRows = analysis?.groups.project ?? [];

  const emptyText = t("quality_analysis_empty", {
    defaultValue: "还没有评分数据。先在分镜图或视频卡片下方评分，分析会自动汇总。",
  });

  return (
    <div className="space-y-7">
      <div>
        <div className="font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-accent-2">
          {t("quality_analysis_eyebrow", { defaultValue: "Quality Ledger" })}
        </div>
        <h3 className="font-editorial mt-1" style={EDITORIAL_HEADING_STYLE}>
          {t("quality_analysis", { defaultValue: "质量分析" })}
        </h3>
        <p className="mt-1.5 text-[12.5px] leading-[1.6] text-text-3">
          {t("quality_analysis_desc", {
            defaultValue: "汇总所有项目的分镜和视频评分，按模型、分辨率、首尾帧连续性、分镜生成方式和评分维度分析实际生成质量。",
          })}
        </p>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 px-1 text-text-3">
          <Loader2 className="h-3.5 w-3.5 motion-safe:animate-spin text-accent-2" aria-hidden />
          <span className="font-mono text-[11px] uppercase tracking-[0.14em]">
            {t("common:loading", { defaultValue: "加载中..." })}
          </span>
        </div>
      ) : error ? (
        <div className="rounded-[10px] border border-danger/35 bg-danger/10 px-5 py-6 text-[12.5px] leading-[1.6] text-danger-2">
          {t("quality_analysis_load_failed", {
            defaultValue: "质量分析加载失败：{{message}}",
            message: error,
          })}
        </div>
      ) : !analysis || analysis.count === 0 ? (
        <div className="rounded-[10px] border border-hairline-soft bg-bg-grad-a/45 px-5 py-10 text-center text-[12.5px] text-text-3">
          {emptyText}
        </div>
      ) : (
        <>
          <div className="grid gap-3 md:grid-cols-4">
            <KpiCard
              label={t("quality_analysis_avg_score", { defaultValue: "总评分" })}
              value={scoreText(analysis.average_rating)}
              sub={t("quality_analysis_sample_count", {
                defaultValue: "{{count}} 个已评分版本",
                count: analysis.count,
              })}
              Icon={Star}
            />
            <KpiCard
              label={t("quality_analysis_projects", { defaultValue: "覆盖项目" })}
              value={`${analysis.project_count}/${analysis.total_projects}`}
              sub={t("quality_analysis_projects_hint", { defaultValue: "有评分 / 全部项目" })}
              Icon={Layers3}
            />
            <KpiCard
              label={t("quality_analysis_models", { defaultValue: "覆盖模型" })}
              value={String(analysis.rated_model_count)}
              sub={t("quality_analysis_models_hint", { defaultValue: "参与评分的供应商模型" })}
              Icon={BarChart3}
            />
            <KpiCard
              label={t("quality_analysis_dimensions", { defaultValue: "维度评分" })}
              value={String(dimensionRows.length)}
              sub={t("quality_analysis_dimensions_hint", { defaultValue: "角色、构图、动作、提示词等" })}
              Icon={Trophy}
            />
          </div>

          <section className="rounded-[10px] border border-hairline p-5" style={CARD_STYLE}>
            <div className="mb-4">
              <h4 className="m-0 text-[14px] font-semibold text-text">
                {t("quality_analysis_dimension_title", { defaultValue: "评分维度短板" })}
              </h4>
              <p className="mt-1 text-[12px] leading-[1.5] text-text-3">
                {t("quality_analysis_dimension_desc", { defaultValue: "低分维度排在前面，便于判断主要问题是角色、构图、动作还是提示词贴合。" })}
              </p>
            </div>
            {dimensionRows.length === 0 ? (
              <div className="rounded-[8px] border border-hairline-soft bg-bg-grad-a/45 px-4 py-6 text-center text-[12.5px] text-text-3">
                {t("quality_analysis_no_dimension_data", { defaultValue: "暂无维度评分。" })}
              </div>
            ) : (
              <div className="grid gap-2 md:grid-cols-2">
                {dimensionRows.map((item) => (
                  <div
                    key={item.key}
                    className="flex items-center justify-between gap-3 rounded-[8px] border border-hairline-soft bg-bg-grad-a/45 px-3 py-2.5"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-[12.5px] text-text">
                        {dimensionLabel(t, item.key)}
                      </div>
                      <div className="mt-0.5 font-mono text-[10px] uppercase tracking-[0.12em] text-text-4">
                        {t("quality_analysis_dimension_samples", {
                          defaultValue: "{{count}} 个样本",
                          count: item.count,
                        })}
                      </div>
                    </div>
                    <div className={`font-mono text-[13px] font-semibold tabular-nums ${scoreTone(item.average_rating)}`}>
                      {scoreText(item.average_rating)}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <div className="grid gap-4 xl:grid-cols-2">
            <AnalysisTable
              title={t("quality_analysis_model_title", { defaultValue: "模型效果排行" })}
              subtitle={t("quality_analysis_model_desc", { defaultValue: "按供应商和模型汇总所有已评分版本。" })}
              items={modelRows}
              emptyText={emptyText}
            />
            <AnalysisTable
              title={t("quality_analysis_resolution_title", { defaultValue: "分辨率对比" })}
              subtitle={t("quality_analysis_resolution_desc", { defaultValue: "对比不同分辨率下的平均评分和样本量。" })}
              items={resolutionRows}
              emptyText={emptyText}
            />
            <AnalysisTable
              title={t("quality_analysis_service_tier_title", { defaultValue: "服务档位对比" })}
              subtitle={t("quality_analysis_service_tier_desc", { defaultValue: "对比默认调度和 Flex 调度下的平均评分与样本量。" })}
              items={serviceTierRows}
              emptyText={emptyText}
            />
            <AnalysisTable
              title={t("quality_analysis_continuity_title", { defaultValue: "视频连续性对比" })}
              subtitle={t("quality_analysis_continuity_desc", { defaultValue: "观察仅首帧、首尾帧连续等策略的真实表现。" })}
              items={continuityRows}
              emptyText={emptyText}
            />
            <AnalysisTable
              title={t("quality_analysis_storyboard_mode_title", { defaultValue: "分镜生成方式对比" })}
              subtitle={t("quality_analysis_storyboard_mode_desc", { defaultValue: "观察沿当前分镜继续生成与重新出图的实际表现。" })}
              items={storyboardModeRows}
              emptyText={emptyText}
            />
            <AnalysisTable
              title={t("quality_analysis_source_storyboard_model_title", { defaultValue: "来源分镜模型" })}
              subtitle={t("quality_analysis_source_storyboard_model_desc", { defaultValue: "观察视频引用的是哪种分镜模型，对最终评分有什么影响。" })}
              items={sourceStoryboardModelRows}
              emptyText={emptyText}
            />
            <AnalysisTable
              title={t("quality_analysis_reference_count_title", { defaultValue: "参考图数量对比" })}
              subtitle={t("quality_analysis_reference_count_desc", { defaultValue: "对比不同参考图数量下的平均评分和样本量。" })}
              items={referenceImageCountRows}
              emptyText={emptyText}
            />
            <AnalysisTable
              title={t("quality_analysis_project_title", { defaultValue: "项目质量排行" })}
              subtitle={t("quality_analysis_project_desc", { defaultValue: "按项目汇总评分，帮助发现表现稳定或需要调参的项目。" })}
              items={projectRows}
              emptyText={emptyText}
              secondaryLabel={t("quality_analysis_column_project", { defaultValue: "项目" })}
              secondaryValue={(item) => String(item.project_name || "-")}
            />
          </div>
        </>
      )}
    </div>
  );
}
