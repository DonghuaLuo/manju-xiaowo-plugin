import { describe, expect, it } from "vitest";
import type { TFunction } from "i18next";
import { summarizeUserFacingError } from "./error-summary";

const t = ((key: string, params?: Record<string, unknown>) =>
  `${key}|${params?.violations ?? ""}|${params?.requestId ?? ""}`) as unknown as TFunction;

describe("summarizeUserFacingError", () => {
  it("summarizes OpenAI moderation blocks without losing the category or request id", () => {
    const text = summarizeUserFacingError(
      t,
      "openai.BadRequestError: Error code: 400 - {'error': {'code': 'moderation_blocked', 'message': 'Your request was rejected by the safety system. If you believe this is an error, contact us at help.openai.com and include the request ID 82e29bca-bdf0-4679-a24b-49c27c1690f4. safety_violations=[violence].'}}",
    );

    expect(text).toBe("image_safety_blocked_summary|violence|82e29bca-bdf0-4679-a24b-49c27c1690f4");
  });

  it("passes non-moderation errors through unchanged", () => {
    expect(summarizeUserFacingError(t, "timeout")).toBe("timeout");
  });
});
