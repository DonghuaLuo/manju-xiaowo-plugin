/** 预设风格 prompt 与模板清单由后端接口提供。 */
export type StyleCategory = "live" | "anim";

export interface StyleTemplate {
  id: string;
  category: StyleCategory;
  thumbnailFile: string;
}

export const DEFAULT_TEMPLATE_ID = "live_premium_drama";
