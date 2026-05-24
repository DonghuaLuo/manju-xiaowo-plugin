import type { TFunction } from "i18next";

function extractRequestId(message: string): string | null {
  const match = message.match(/\brequest ID\s+([a-zA-Z0-9-]+)/i);
  return match?.[1] ?? null;
}

function extractSafetyViolations(message: string): string | null {
  const match = message.match(/safety_violations=\[([^\]]+)\]/i);
  return match?.[1]?.trim() || null;
}

export function summarizeUserFacingError(
  t: TFunction,
  message: string | null | undefined,
): string | null {
  if (!message) return null;
  if (/moderation_blocked/i.test(message) || /safety_violations=/i.test(message)) {
    const requestId = extractRequestId(message);
    const violations = extractSafetyViolations(message);
    return t("image_safety_blocked_summary", {
      violations: violations || t("image_safety_blocked_unknown_violation"),
      requestId: requestId || t("image_safety_blocked_no_request_id"),
    });
  }
  return message;
}
