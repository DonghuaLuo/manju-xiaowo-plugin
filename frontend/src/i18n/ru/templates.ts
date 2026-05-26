import baseTemplates from "../en/templates";
import { mergeNamespace, type DeepPartialStrings, type StringResources } from "../_helpers";
import type enTemplates from "../en/templates";

type TemplateResource = StringResources<typeof enTemplates>;

const templateOverrides = {
    category: { custom: "Пользовательский", live: "Живое действие", anim: "Анимация" },
    name: {
      live_cinematic_ancient: "Кинематографическая история",
      live_ancient_xianxia: "Историческое сянься",
      live_premium_drama: "Премиальная драма",
      live_cinema: "Кинофильм",
      live_spartan: "Спартанский эпос",
      live_cyberpunk: "Киберпанк live",
      anim_3d_cg: "3D game CG",
      anim_cn_3d: "Китайское 3D",
      anim_us_3d: "Американская 3D-анимация",
      anim_ink_wushan: "Сильная тушь",
      anim_ink_papercut: "Тушь и вырезанная бумага",
      anim_felt: "Фетровый stop motion",
      anim_clay: "Пластилиновый stop motion",
      anim_jp_horror: "Японский хоррор",
      anim_kr_webtoon: "Корейский вебтун",
      anim_cyberpunk: "Анимационный киберпанк",
      anim_90s_retro: "Ретро-аниме 90-х",
    },
    default_hint: "Модели по умолчанию можно изменить в Панель > Настройки > Выбор модели",
    current_global_default: "Текущее глобальное значение: {{value}}",
    use_global_default: "Использовать глобальное значение",
    model_video: "Видео-модель",
    model_image: "Модель изображений",
    model_image_t2i: "Модель изображений (T2I)",
    model_image_i2i: "Модель изображений (I2I)",
    model_image_dual_hint: "Рекомендуется выбрать модель с подходящей поддержкой T2I/I2I",
    model_text_script: "Модель генерации сценария",
    model_text_overview: "Модель генерации обзора",
    model_text_style: "Модель анализа стиля",
    duration_label: "Длительность по умолчанию",
    duration_auto: "авто",
    resolution_label: "Разрешение",
    resolution_default_placeholder: "По умолчанию (не задано)",
    tab_custom_desc: "Загрузите референс стиля; ИИ его проанализирует. Выбор этой вкладки очищает выбранный шаблон.",
    upload_reference: "Загрузить референс стиля",
    supported_formats: "PNG / JPG / WEBP",
    template_selected_default: "(по умолчанию)",
    wizard_step_basics: "Основы",
    wizard_step_models: "Модели",
    wizard_step_style: "Стиль",
    next_step: "Далее",
    prev_step: "Назад",
  } satisfies DeepPartialStrings<TemplateResource>;

export default mergeNamespace(baseTemplates, templateOverrides);
