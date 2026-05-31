import { PluginSDK } from "xiaowo-sdk";

/** Copy text to clipboard. Prefer the desktop SDK so async flows after native dialogs stay reliable. */
export async function copyText(text: string): Promise<void> {
  try {
    await PluginSDK.clipboard.writeText(text);
    return;
  } catch {
    // Browser fallbacks keep dev/test contexts working when the desktop bridge is unavailable.
  }

  if (navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(text);
  }

  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  try {
    ta.select();
    const copied = document.execCommand("copy");
    if (!copied) {
      throw new Error("复制到剪贴板失败");
    }
  } finally {
    document.body.removeChild(ta);
  }
}
