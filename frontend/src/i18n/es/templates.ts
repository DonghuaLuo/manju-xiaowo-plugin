import baseTemplates from "../en/templates";
import { mergeNamespace, type DeepPartialStrings, type StringResources } from "../_helpers";
import type enTemplates from "../en/templates";

type TemplateResource = StringResources<typeof enTemplates>;

const templateOverrides = {
    category: { custom: "Personalizado", live: "Acción real", anim: "Animación" },
    name: {
      live_cinematic_ancient: "Histórico cinematográfico",
      live_ancient_xianxia: "Xianxia histórico",
      live_premium_drama: "Drama premium",
      live_cinema: "Película de cine",
      live_spartan: "Épica espartana",
      live_cyberpunk: "Cyberpunk de acción real",
      anim_3d_cg: "CG de juego 3D",
      anim_cn_3d: "3D chino",
      anim_us_3d: "Animación 3D estadounidense",
      anim_ink_wushan: "Tinta intensa",
      anim_ink_papercut: "Tinta y papel recortado",
      anim_felt: "Stop motion de fieltro",
      anim_clay: "Stop motion de arcilla",
      anim_jp_horror: "Terror japonés",
      anim_kr_webtoon: "Webtoon coreano",
      anim_cyberpunk: "Cyberpunk animado",
      anim_90s_retro: "Anime retro de los 90",
    },
    default_hint: "Los modelos predeterminados se pueden cambiar en Panel > Configuración > Selección de modelos",
    current_global_default: "Predeterminado global actual: {{value}}",
    use_global_default: "Usar predeterminado global",
    model_video: "Modelo de video",
    model_image: "Modelo de imagen",
    model_image_t2i: "Modelo de imagen (T2I)",
    model_image_i2i: "Modelo de imagen (I2I)",
    model_image_dual_hint: "Se recomienda elegir modelos con la capacidad T2I/I2I correspondiente",
    model_text_script: "Modelo para generar guion",
    model_text_overview: "Modelo para generar resumen",
    model_text_style: "Modelo para análisis de estilo",
    duration_label: "Duración predeterminada",
    duration_auto: "auto",
    resolution_label: "Resolución",
    resolution_default_placeholder: "Predeterminado (sin definir)",
    tab_custom_desc: "Sube una imagen de referencia de estilo; la IA la analizará. Elegir esta pestaña borra la plantilla seleccionada.",
    upload_reference: "Subir referencia de estilo",
    supported_formats: "PNG / JPG / WEBP",
    template_selected_default: "(predeterminado)",
    wizard_step_basics: "Básicos",
    wizard_step_models: "Modelos",
    wizard_step_style: "Estilo",
    next_step: "Siguiente",
    prev_step: "Atrás",
  } satisfies DeepPartialStrings<TemplateResource>;

export default mergeNamespace(baseTemplates, templateOverrides);
