import { useId, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { GenerationModeSelector } from "@/components/shared/GenerationModeSelector";
import { ACCENT_BTN_CLS, ACCENT_BUTTON_STYLE, radioCardClass } from "@/components/ui/darkroom-tokens";
import { FieldLabel } from "@/components/ui/FieldLabel";
import {
  ScriptSplittingTemplateSelector,
  defaultScriptSplittingTemplateId,
  disabledGenerationModesForTemplate,
  firstRecommendedGenerationMode,
  scriptSplittingContentModeDescription,
  scriptSplittingContentModeLabel,
  scriptSplittingTemplateSupportsGenerationMode,
  type ScriptSplittingContentMode,
} from "@/components/shared/ScriptSplittingTemplateSelector";
import type { ScriptSplittingTemplateInfo } from "@/api";
import type { GenerationMode } from "@/utils/generation-mode";

export interface WizardStep1Value {
  title: string;
  contentMode: "narration" | "drama";
  aspectRatio: "9:16" | "16:9";
  generationMode: GenerationMode;
  scriptSplittingTemplateId?: string | null;
}

export interface WizardStep1BasicsProps {
  value: WizardStep1Value;
  onChange: (next: WizardStep1Value) => void;
  onNext: () => void;
  onCancel: () => void;
  scriptSplittingTemplates?: ScriptSplittingTemplateInfo[];
}

export function WizardStep1Basics({
  value,
  onChange,
  onNext,
  onCancel,
  scriptSplittingTemplates = [],
}: WizardStep1BasicsProps) {
  const { t } = useTranslation(["common", "dashboard", "templates"]);
  const [titleError, setTitleError] = useState("");
  const reactId = useId();
  const titleId = `${reactId}-title`;
  const titleErrorId = `${reactId}-title-error`;
  const selectedScriptSplittingTemplate = scriptSplittingTemplates.find(
    (tpl) => tpl.id === value.scriptSplittingTemplateId,
  );

  const handleTitleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setTitleError("");
    onChange({ ...value, title: e.target.value });
  };

  const handleNext = () => {
    if (!value.title.trim()) {
      setTitleError(t("dashboard:project_title_required"));
      return;
    }
    onNext();
  };

  const changeContentMode = (contentMode: ScriptSplittingContentMode) => {
    const templateId = defaultScriptSplittingTemplateId(
      contentMode,
      scriptSplittingTemplates,
    );
    const template = scriptSplittingTemplates.find((tpl) => tpl.id === templateId);
    onChange({
      ...value,
      contentMode,
      generationMode: firstRecommendedGenerationMode(template, value.generationMode),
      scriptSplittingTemplateId: templateId || null,
    });
  };

  const changeScriptSplittingTemplate = (templateId: string) => {
    const template = scriptSplittingTemplates.find((tpl) => tpl.id === templateId);
    onChange({
      ...value,
      generationMode: firstRecommendedGenerationMode(template, value.generationMode),
      scriptSplittingTemplateId: templateId,
    });
  };

  const changeGenerationMode = (generationMode: GenerationMode) => {
    if (
      selectedScriptSplittingTemplate
      && !scriptSplittingTemplateSupportsGenerationMode(selectedScriptSplittingTemplate, generationMode)
    ) {
      return;
    }
    onChange({ ...value, generationMode });
  };

  return (
    <div className="space-y-5">
      {/* Title */}
      <div>
        <FieldLabel htmlFor={titleId} required>
          {t("dashboard:project_title")}
        </FieldLabel>
        <div className="relative">
          <input
            id={titleId}
            type="text"
            value={value.title}
            onChange={handleTitleChange}
            placeholder={t("dashboard:rebirth_empress_example")}
            aria-required="true"
            aria-invalid={titleError ? "true" : undefined}
            aria-describedby={titleError ? titleErrorId : undefined}
            className="w-full rounded-[8px] border border-hairline bg-bg-grad-a/55 px-3 py-2.5 text-[14px] text-text placeholder:text-text-4 transition-colors focus:border-accent/55 focus:bg-bg-grad-a/85 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          />
        </div>
        {titleError ? (
          <p
            id={titleErrorId}
            role="alert"
            aria-live="polite"
            className="mt-1.5 inline-flex items-center gap-1.5 font-mono text-[10.5px] uppercase tracking-[0.08em] text-warm"
          >
            <AlertTriangle aria-hidden className="h-3 w-3" />
            {titleError}
          </p>
        ) : null}
        <p className="mt-1.5 text-[11.5px] text-text-4">{t("dashboard:project_id_auto_gen_hint")}</p>
      </div>

      {/* Content Mode */}
      <div>
        <FieldLabel>{t("dashboard:content_mode")}</FieldLabel>
        <div className="flex gap-2.5" role="radiogroup" aria-label={t("dashboard:content_mode")}>
          <label className={radioCardClass(value.contentMode === "narration")}>
            <input
              type="radio"
              name="contentMode"
              value="narration"
              checked={value.contentMode === "narration"}
              onChange={() => changeContentMode("narration")}
              className="sr-only"
            />
            {scriptSplittingContentModeLabel("narration", t)}
          </label>
          <label className={radioCardClass(value.contentMode === "drama")}>
            <input
              type="radio"
              name="contentMode"
              value="drama"
              checked={value.contentMode === "drama"}
              onChange={() => changeContentMode("drama")}
              className="sr-only"
            />
            {scriptSplittingContentModeLabel("drama", t)}
          </label>
        </div>
        <p className="mt-2 text-[11.5px] leading-[1.55] text-text-3">
          {scriptSplittingContentModeDescription(value.contentMode, t)}
        </p>
      </div>

      {/* Script splitting template */}
      <ScriptSplittingTemplateSelector
        value={value.scriptSplittingTemplateId}
        contentMode={value.contentMode}
        generationMode={value.generationMode}
        templates={scriptSplittingTemplates}
        onChange={changeScriptSplittingTemplate}
        label={t("dashboard:script_splitting_preset_label", { defaultValue: "选择拆分方案" })}
        showHash={false}
      />

      {/* Aspect Ratio */}
      <div>
        <FieldLabel>{t("dashboard:aspect_ratio")}</FieldLabel>
        <div className="flex gap-2.5" role="radiogroup" aria-label={t("dashboard:aspect_ratio")}>
          <label className={radioCardClass(value.aspectRatio === "9:16")}>
            <input
              type="radio"
              name="aspectRatio"
              value="9:16"
              checked={value.aspectRatio === "9:16"}
              onChange={() => onChange({ ...value, aspectRatio: "9:16" })}
              className="sr-only"
            />
            <span className="inline-flex items-center gap-2">
              <span
                aria-hidden
                className="block h-3 w-[7.5px] rounded-[1.5px] border border-hairline"
                style={{
                  background:
                    value.aspectRatio === "9:16" ? "var(--color-accent-soft)" : "transparent",
                }}
              />
              {t("dashboard:portrait_9_16")}
            </span>
          </label>
          <label className={radioCardClass(value.aspectRatio === "16:9")}>
            <input
              type="radio"
              name="aspectRatio"
              value="16:9"
              checked={value.aspectRatio === "16:9"}
              onChange={() => onChange({ ...value, aspectRatio: "16:9" })}
              className="sr-only"
            />
            <span className="inline-flex items-center gap-2">
              <span
                aria-hidden
                className="block h-[7.5px] w-3 rounded-[1.5px] border border-hairline"
                style={{
                  background:
                    value.aspectRatio === "16:9" ? "var(--color-accent-soft)" : "transparent",
                }}
              />
              {t("dashboard:landscape_16_9")}
            </span>
          </label>
        </div>
      </div>

      {/* Generation Mode */}
      <div>
        <FieldLabel>{t("dashboard:generation_mode")}</FieldLabel>
        <GenerationModeSelector
          value={value.generationMode}
          onChange={changeGenerationMode}
          disabledModes={disabledGenerationModesForTemplate(selectedScriptSplittingTemplate)}
        />
      </div>

      {/* Footer */}
      <div className="mt-7 flex items-center justify-between border-t border-hairline-soft pt-5">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-[7px] px-2.5 py-1.5 text-[12.5px] text-text-3 transition-colors hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          {t("common:cancel")}
        </button>
        <button
          type="button"
          onClick={handleNext}
          disabled={!value.title.trim()}
          className={ACCENT_BTN_CLS}
          style={ACCENT_BUTTON_STYLE}
        >
          {t("templates:next_step")}
          <span aria-hidden>→</span>
        </button>
      </div>
    </div>
  );
}
