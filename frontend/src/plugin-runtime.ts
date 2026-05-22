import { PluginSDK } from "xiaowo-sdk";

type DesktopRequestBody =
  | { kind: "empty" }
  | { kind: "json"; value: unknown }
  | { kind: "text"; text: string; mimeType?: string }
  | { kind: "fields"; fields: Record<string, string[]> }
  | { kind: "binary"; base64: string; mimeType?: string };

type DesktopContent =
  | { kind: "empty" }
  | { kind: "json"; value: unknown }
  | { kind: "text"; text: string; mimeType?: string }
  | { kind: "binary"; base64: string; mimeType?: string };

type DesktopResult = {
  success?: boolean;
  error?: {
    code?: string;
    message?: string;
  };
  content?: DesktopContent;
};

type PluginStreamPayload = {
  stream: string;
  event: string;
  id?: string | number | null;
  data?: unknown;
};

const originalFetch = globalThis.fetch.bind(globalThis);
let installed = false;

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

function base64ToBytes(base64: string): Uint8Array {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

function isApiUrl(url: string): boolean {
  const parsed = new URL(url, window.location.href);
  return parsed.pathname.startsWith("/api/");
}

function apiResourceFromUrl(url: string): {
  resource: string;
  query: Record<string, string[]>;
} {
  const parsed = new URL(url, window.location.href);
  const resource = parsed.pathname
    .replace(/^\/api\/v1\/?/, "")
    .replace(/^\/api\/?/, "")
    .replace(/^\/+/, "");
  const query: Record<string, string[]> = {};
  parsed.searchParams.forEach((value, key) => {
    query[key] = [...(query[key] ?? []), value];
  });
  return { resource: resource || "root", query };
}

function operationFromMethod(method: string): string {
  switch (method.toUpperCase()) {
    case "POST":
      return "create";
    case "PUT":
      return "replace";
    case "PATCH":
      return "update";
    case "DELETE":
      return "delete";
    default:
      return "read";
  }
}

function fieldsFromSearchParams(params: URLSearchParams): Record<string, string[]> {
  const fields: Record<string, string[]> = {};
  params.forEach((value, key) => {
    fields[key] = [...(fields[key] ?? []), value];
  });
  return fields;
}

function jsonOrTextPayload(text: string, mimeType?: string): DesktopRequestBody {
  if (mimeType?.toLowerCase().includes("json")) {
    try {
      return { kind: "json", value: JSON.parse(text) };
    } catch {
      return { kind: "text", text, mimeType };
    }
  }
  return { kind: "text", text, mimeType };
}

async function bodyToDesktopBody(body: BodyInit | null | undefined, headers: Headers): Promise<DesktopRequestBody> {
  if (body == null) return { kind: "empty" };

  const mimeType = headers.get("content-type") ?? undefined;

  if (typeof body === "string") {
    return jsonOrTextPayload(body, mimeType);
  }

  if (body instanceof URLSearchParams) {
    return { kind: "fields", fields: fieldsFromSearchParams(body) };
  }

  if (body instanceof FormData) {
    throw new Error("Multipart browser payloads are disabled in the Xiaowo plugin");
  }

  if (body instanceof Blob) {
    return { kind: "binary", base64: bytesToBase64(new Uint8Array(await body.arrayBuffer())), mimeType: body.type || mimeType };
  }

  if (body instanceof ArrayBuffer) {
    return { kind: "binary", base64: bytesToBase64(new Uint8Array(body)), mimeType };
  }

  if (ArrayBuffer.isView(body)) {
    return {
      kind: "binary",
      base64: bytesToBase64(new Uint8Array(body.buffer, body.byteOffset, body.byteLength)),
      mimeType,
    };
  }

  return { kind: "text", text: String(body), mimeType };
}

function statusFromErrorCode(code?: string): number {
  switch (code) {
    case "validation_error":
      return 422;
    case "not_found":
      return 404;
    case "conflict":
      return 409;
    case "too_large":
      return 413;
    case "forbidden":
      return 403;
    case "unauthorized":
      return 401;
    default:
      return 500;
  }
}

function contentToResponseBody(content: DesktopContent | undefined): {
  body: BodyInit;
  mimeType: string;
  empty: boolean;
} {
  if (!content || content.kind === "empty") {
    return { body: "", mimeType: "text/plain;charset=utf-8", empty: true };
  }
  if (content.kind === "json") {
    return { body: JSON.stringify(content.value ?? null), mimeType: "application/json;charset=utf-8", empty: false };
  }
  if (content.kind === "binary") {
    return {
      body: new Blob([base64ToBytes(content.base64).slice().buffer]),
      mimeType: content.mimeType || "application/octet-stream",
      empty: false,
    };
  }
  return { body: content.text, mimeType: content.mimeType || "text/plain;charset=utf-8", empty: false };
}

function desktopResultToResponse(result: DesktopResult): Response {
  const success = result.success !== false;
  const fallbackContent: DesktopContent | undefined = success
    ? result.content
    : result.content ?? { kind: "json", value: { detail: result.error?.message || "请求失败" } };
  const { body, mimeType, empty } = contentToResponseBody(fallbackContent);
  return new Response(body, {
    status: success ? (empty ? 204 : 200) : statusFromErrorCode(result.error?.code),
    headers: { "content-type": mimeType },
  });
}

async function pluginFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const request = input instanceof Request ? input : null;
  const url = request?.url ?? String(input);

  if (!isApiUrl(url)) {
    return originalFetch(input, init);
  }

  const method = init.method ?? request?.method ?? "GET";
  const headers = new Headers(request?.headers);
  new Headers(init.headers).forEach((value, key) => headers.set(key, value));

  const requestBody = init.body ?? null;
  const body = await bodyToDesktopBody(requestBody, headers);
  const resource = apiResourceFromUrl(url);

  try {
    const result = await PluginSDK.callBackend<DesktopResult>("arcreel_resource_request", {
      operation: operationFromMethod(method),
      ...resource,
      locale: headers.get("accept-language") || navigator.language,
      body,
    });
    return desktopResultToResponse(result);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return new Response(JSON.stringify({ detail: message }), {
      status: 500,
      headers: { "content-type": "application/json" },
    });
  }
}

function streamKeyFromUrl(url: string): string {
  const parsed = new URL(url, window.location.href);
  return parsed.pathname.replace(/^\/api\/v1\//, "");
}

class PluginEventSource extends EventTarget {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;

  readonly CONNECTING = 0;
  readonly OPEN = 1;
  readonly CLOSED = 2;
  readonly url: string;
  withCredentials = false;
  readyState = PluginEventSource.CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  private readonly stream: string;
  private readonly backendHandler: (payload: PluginStreamPayload) => void;
  private readonly seenEventIds = new Set<string>();
  private lastEventId: string | number | null = null;
  private pollTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(url: string | URL) {
    super();
    this.url = String(url);
    this.stream = streamKeyFromUrl(this.url);
    this.backendHandler = (payload) => {
      if (!payload || payload.stream !== this.stream || this.readyState === PluginEventSource.CLOSED) {
        return;
      }
      if (this.isDuplicateEvent(payload)) {
        return;
      }
      this.rememberEventCursor(payload);
      this.emitMessage(payload.event || "message", payload.data);
    };

    PluginSDK.onBackendEvent<PluginStreamPayload>("arcreel_event", this.backendHandler);
    queueMicrotask(() => {
      if (this.readyState === PluginEventSource.CLOSED) return;
      this.readyState = PluginEventSource.OPEN;
      const event = new Event("open");
      this.dispatchEvent(event);
      this.onopen?.(event);
      void PluginSDK.callBackend<{ events?: PluginStreamPayload[] }>("arcreel_event_subscribe", {
        ...apiResourceFromUrl(this.url),
        stream: this.stream,
      })
        .then((snapshot) => {
          for (const eventPayload of snapshot.events ?? []) {
            this.backendHandler(eventPayload);
          }
          this.schedulePoll();
        })
        .catch(() => {
          const errorEvent = new Event("error");
          this.dispatchEvent(errorEvent);
          this.onerror?.(errorEvent);
          this.schedulePoll();
        });
    });
  }

  close(): void {
    if (this.readyState === PluginEventSource.CLOSED) return;
    this.readyState = PluginEventSource.CLOSED;
    if (this.pollTimer) {
      clearTimeout(this.pollTimer);
      this.pollTimer = null;
    }
    PluginSDK.offBackendEvent("arcreel_event", this.backendHandler);
  }

  private rememberEventCursor(payload: PluginStreamPayload): void {
    if (
      payload.event === "snapshot"
      && payload.data
      && typeof payload.data === "object"
      && "last_event_id" in payload.data
    ) {
      const snapshot = payload.data as { last_event_id?: unknown };
      if (snapshot.last_event_id != null && snapshot.last_event_id !== "") {
        this.lastEventId = String(snapshot.last_event_id);
      }
      return;
    }
    if (payload.id != null && payload.id !== "") {
      this.lastEventId = payload.id;
    }
  }

  private isDuplicateEvent(payload: PluginStreamPayload): boolean {
    if (payload.id == null || payload.id === "") {
      return false;
    }
    const key = `${payload.stream}:${payload.event}:${String(payload.id)}`;
    if (this.seenEventIds.has(key)) {
      return true;
    }
    this.seenEventIds.add(key);
    if (this.seenEventIds.size > 1000) {
      const oldest = this.seenEventIds.values().next().value;
      if (oldest) {
        this.seenEventIds.delete(oldest);
      }
    }
    return false;
  }

  private schedulePoll(): void {
    if (this.readyState === PluginEventSource.CLOSED || this.pollTimer) return;
    this.pollTimer = setTimeout(() => {
      this.pollTimer = null;
      void this.poll();
    }, 1000);
  }

  private async poll(): Promise<void> {
    if (this.readyState === PluginEventSource.CLOSED) return;
    try {
      const result = await PluginSDK.callBackend<{ events?: PluginStreamPayload[] }>("arcreel_event_poll", {
        ...apiResourceFromUrl(this.url),
        stream: this.stream,
        lastEventId: this.lastEventId,
      });
      for (const eventPayload of result.events ?? []) {
        this.backendHandler(eventPayload);
      }
    } catch {
      const errorEvent = new Event("error");
      this.dispatchEvent(errorEvent);
      this.onerror?.(errorEvent);
    } finally {
      this.schedulePoll();
    }
  }

  private emitMessage(type: string, data: unknown): void {
    const event = new MessageEvent(type, {
      data: typeof data === "string" ? data : JSON.stringify(data ?? {}),
    });
    this.dispatchEvent(event);
    if (type === "message") {
      this.onmessage?.(event);
    }
  }
}

const apiMediaObjectUrls = new WeakMap<Element, string>();
const apiMediaTokens = new WeakMap<Element, number>();
let mediaAdaptersInstalled = false;

function isApiResourceUrl(value: string): boolean {
  try {
    return isApiUrl(value);
  } catch {
    return false;
  }
}

function releaseApiMediaObjectUrl(element: Element): void {
  const previous = apiMediaObjectUrls.get(element);
  if (!previous) return;
  URL.revokeObjectURL(previous);
  apiMediaObjectUrls.delete(element);
}

function refreshParentMedia(element: Element): void {
  if (element instanceof HTMLSourceElement && element.parentElement instanceof HTMLMediaElement) {
    element.parentElement.load();
  }
}

function setApiAwareMediaSrc(element: Element, value: string, applyNative: (next: string) => void): void {
  if (!isApiResourceUrl(value)) {
    releaseApiMediaObjectUrl(element);
    applyNative(value);
    refreshParentMedia(element);
    return;
  }

  const token = (apiMediaTokens.get(element) ?? 0) + 1;
  apiMediaTokens.set(element, token);
  releaseApiMediaObjectUrl(element);
  applyNative("");

  void pluginFetch(value)
    .then((response) => {
      if (!response.ok) {
        throw new Error(response.statusText || "Resource request failed");
      }
      return response.blob();
    })
    .then((blob) => {
      if (apiMediaTokens.get(element) !== token) return;
      const objectUrl = URL.createObjectURL(blob);
      apiMediaObjectUrls.set(element, objectUrl);
      applyNative(objectUrl);
      refreshParentMedia(element);
    })
    .catch(() => {
      if (apiMediaTokens.get(element) !== token) return;
      applyNative("");
      refreshParentMedia(element);
    });
}

function patchSrcProperty(proto: object): void {
  const descriptor = Object.getOwnPropertyDescriptor(proto, "src");
  if (!descriptor?.get || !descriptor.set) return;

  Object.defineProperty(proto, "src", {
    ...descriptor,
    set(this: Element, value: string) {
      setApiAwareMediaSrc(this, String(value), (next) => descriptor.set?.call(this, next));
    },
  });
}

function installMediaResourceAdapter(): void {
  if (mediaAdaptersInstalled) return;
  mediaAdaptersInstalled = true;

  patchSrcProperty(HTMLImageElement.prototype);
  patchSrcProperty(HTMLMediaElement.prototype);
  patchSrcProperty(HTMLSourceElement.prototype);

  const originalSetAttribute = Element.prototype.setAttribute;
  Element.prototype.setAttribute = function setAttribute(name: string, value: string): void {
    if (name.toLowerCase() === "src") {
      setApiAwareMediaSrc(this, String(value), (next) => originalSetAttribute.call(this, name, next));
      return;
    }
    originalSetAttribute.call(this, name, value);
  };
}

export function installPluginRuntimeAdapters(): void {
  if (installed) return;
  installed = true;
  globalThis.fetch = pluginFetch;
  globalThis.EventSource = PluginEventSource as typeof EventSource;
  installMediaResourceAdapter();
}
