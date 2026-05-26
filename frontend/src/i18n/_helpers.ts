export type StringResources<T> = {
  [K in keyof T]: T[K] extends string
    ? string
    : T[K] extends Record<string, unknown>
      ? StringResources<T[K]>
      : T[K];
};

export type DeepPartialStrings<T> = {
  [K in keyof T]?: T[K] extends string
    ? string
    : T[K] extends Record<string, unknown>
      ? DeepPartialStrings<T[K]>
      : T[K];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function mergeDeep(
  base: Record<string, unknown>,
  overlay: Record<string, unknown>,
): Record<string, unknown> {
  const out: Record<string, unknown> = { ...base };
  for (const [key, value] of Object.entries(overlay)) {
    const current = out[key];
    out[key] = isRecord(current) && isRecord(value)
      ? mergeDeep(current, value)
      : value;
  }
  return out;
}

export function mergeNamespace<T extends Record<string, unknown>>(
  base: T,
  overlay: DeepPartialStrings<StringResources<T>>,
): StringResources<T> {
  return mergeDeep(base, overlay) as StringResources<T>;
}
