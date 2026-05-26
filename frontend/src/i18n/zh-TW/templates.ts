import baseTemplates from "../zh/templates";
import { mergeNamespace, type DeepPartialStrings, type StringResources } from "../_helpers";
import type enTemplates from "../en/templates";

type TemplateResource = StringResources<typeof enTemplates>;

const templateOverrides = {
    category: { custom: "自訂", live: "真人實拍", anim: "動畫" },
    default_hint: "預設模型可在儀表板 > 設定 > 模型選擇中修改",
    current_global_default: "目前全域預設：{{value}}",
    use_global_default: "使用全域預設",
    model_video: "影片模型",
    model_image: "圖片模型",
    model_image_t2i: "圖片模型（T2I）",
    model_image_i2i: "圖片模型（I2I）",
    model_image_dual_hint: "建議分別選擇具備對應 T2I/I2I 能力的模型",
    model_text_script: "劇本生成模型",
    model_text_overview: "概述生成模型",
    model_text_style: "風格分析模型",
    duration_label: "預設時長",
    duration_auto: "自動",
    resolution_label: "解析度",
    resolution_default_placeholder: "預設（未設定）",
    tab_custom_desc: "上傳風格參考圖，AI 將進行分析。選擇此分頁會清除目前的模板選擇。",
    upload_reference: "上傳風格參考",
    supported_formats: "PNG / JPG / WEBP",
    template_selected_default: "（預設）",
    wizard_step_basics: "基本",
    wizard_step_models: "模型",
    wizard_step_style: "風格",
    next_step: "下一步",
    prev_step: "返回",
  } satisfies DeepPartialStrings<TemplateResource>;

export default mergeNamespace(baseTemplates, templateOverrides);
