/** 预设风格 prompt 与模板清单由后端接口提供。 */
export type StyleCategory = "live" | "anim" | "favorite";

export interface StyleTemplate {
  id: string;
  category: StyleCategory;
  thumbnailFile: string;
  thumbnailUrl?: string | null;
  name?: string | null;
  tagline?: string | null;
}

export const DEFAULT_TEMPLATE_ID = "live_premium_drama";
