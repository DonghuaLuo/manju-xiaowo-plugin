import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import i18n, { i18nReady } from "@/i18n";

vi.mock("xiaowo-sdk", () => {
  const sdk = {
    waitReady: vi.fn(() => Promise.resolve()),
    callBackend: vi.fn(() => Promise.resolve({})),
    getInfo: vi.fn(() => Promise.resolve({
      manifest: {
        id: "manju",
        title: "Manju",
        version: "0.0.0",
      },
      language: "zh",
    })),
    getBackendState: vi.fn(() => Promise.resolve({ is_ready: true, status: "ready" })),
    restartBackend: vi.fn(() => Promise.resolve()),
    onBackendEvent: vi.fn(),
    offBackendEvent: vi.fn(),
    onBackendExit: vi.fn(() => vi.fn()),
    offBackendExit: vi.fn(),
    onBackendReady: vi.fn(() => vi.fn()),
    offBackendReady: vi.fn(),
    onFileDrop: vi.fn(() => vi.fn()),
    offFileDrop: vi.fn(),
    onFileDropHover: vi.fn(() => vi.fn()),
    offFileDropHover: vi.fn(),
    onFileDropCancelled: vi.fn(() => vi.fn()),
    offFileDropCancelled: vi.fn(),
    showWindow: vi.fn(() => Promise.resolve()),
    close: vi.fn(() => Promise.resolve()),
    minimize: vi.fn(() => Promise.resolve()),
    maximize: vi.fn(() => Promise.resolve()),
    unmaximize: vi.fn(() => Promise.resolve()),
    toggleMaximize: vi.fn(() => Promise.resolve()),
    createDesktopShortcut: vi.fn(() => Promise.resolve()),
    openLegalDocumentViewer: vi.fn(() => Promise.resolve("")),
    convertFileSrc: vi.fn((filePath: string) =>
      `asset://localhost/${filePath.replace(/\\/g, "/").replace(/^\/+/, "")}`,
    ),
    app: {
      getName: vi.fn(() => Promise.resolve("xiaowo")),
      getVersion: vi.fn(() => Promise.resolve("0.0.0")),
      getTauriVersion: vi.fn(() => Promise.resolve("0.0.0")),
    },
    os: {
      platform: vi.fn(() => Promise.resolve("windows")),
      version: vi.fn(() => Promise.resolve("0.0.0")),
      arch: vi.fn(() => Promise.resolve("x86_64")),
      locale: vi.fn(() => Promise.resolve("zh-CN")),
      hostname: vi.fn(() => Promise.resolve("localhost")),
    },
    path: {
      appDataDir: vi.fn(() => Promise.resolve("")),
      homeDir: vi.fn(() => Promise.resolve("")),
      desktopDir: vi.fn(() => Promise.resolve("")),
      downloadDir: vi.fn(() => Promise.resolve("")),
      documentDir: vi.fn(() => Promise.resolve("")),
      tempDir: vi.fn(() => Promise.resolve("")),
      join: vi.fn((...parts: string[]) => Promise.resolve(parts.join("/"))),
      basename: vi.fn((path: string) => Promise.resolve(path.split(/[\\/]/).pop() ?? path)),
      dirname: vi.fn((path: string) =>
        Promise.resolve(path.split(/[\\/]/).slice(0, -1).join("/")),
      ),
      extname: vi.fn((path: string) => {
        const name = path.split(/[\\/]/).pop() ?? "";
        const index = name.lastIndexOf(".");
        return Promise.resolve(index >= 0 ? name.slice(index) : "");
      }),
    },
    clipboard: {
      readText: vi.fn(() => Promise.resolve(null)),
      writeText: vi.fn(() => Promise.resolve()),
    },
    shell: {
      open: vi.fn(() => Promise.resolve()),
    },
    dialog: {
      open: vi.fn(() => Promise.resolve(null)),
      save: vi.fn(() => Promise.resolve(null)),
      message: vi.fn(() => Promise.resolve()),
      ask: vi.fn(() => Promise.resolve(false)),
      confirm: vi.fn(() => Promise.resolve(false)),
    },
    fs: {
      createFile: vi.fn(() => Promise.resolve()),
      createDir: vi.fn(() => Promise.resolve()),
      writeTextFile: vi.fn(() => Promise.resolve()),
      writeBase64File: vi.fn(() => Promise.resolve()),
      readTextFile: vi.fn(() => Promise.resolve("")),
      removeFile: vi.fn(() => Promise.resolve()),
      removeDir: vi.fn(() => Promise.resolve()),
      getInfo: vi.fn(() =>
        Promise.resolve({ path: "", exists: false, is_file: false, is_dir: false }),
      ),
      exists: vi.fn(() => Promise.resolve(false)),
      isFile: vi.fn(() => Promise.resolve(false)),
      isDir: vi.fn(() => Promise.resolve(false)),
      copyFile: vi.fn(() => Promise.resolve()),
    },
    notification: {
      isPermissionGranted: vi.fn(() => Promise.resolve(true)),
      requestPermission: vi.fn(() => Promise.resolve("granted")),
      send: vi.fn(() => Promise.resolve()),
    },
    process: {
      exit: vi.fn(() => Promise.resolve()),
      relaunch: vi.fn(() => Promise.resolve()),
    },
  };

  return {
    PluginSDK: sdk,
    default: sdk,
    waitReady: sdk.waitReady,
    callBackend: sdk.callBackend,
    getInfo: sdk.getInfo,
    getBackendState: sdk.getBackendState,
    restartBackend: sdk.restartBackend,
    onBackendEvent: sdk.onBackendEvent,
    offBackendEvent: sdk.offBackendEvent,
    onBackendExit: sdk.onBackendExit,
    offBackendExit: sdk.offBackendExit,
    onBackendReady: sdk.onBackendReady,
    offBackendReady: sdk.offBackendReady,
    onFileDrop: sdk.onFileDrop,
    offFileDrop: sdk.offFileDrop,
    onFileDropHover: sdk.onFileDropHover,
    offFileDropHover: sdk.offFileDropHover,
    onFileDropCancelled: sdk.onFileDropCancelled,
    offFileDropCancelled: sdk.offFileDropCancelled,
    showWindow: sdk.showWindow,
    close: sdk.close,
    minimize: sdk.minimize,
    maximize: sdk.maximize,
    unmaximize: sdk.unmaximize,
    toggleMaximize: sdk.toggleMaximize,
    createDesktopShortcut: sdk.createDesktopShortcut,
    openLegalDocumentViewer: sdk.openLegalDocumentViewer,
    convertFileSrc: sdk.convertFileSrc,
    app: sdk.app,
    os: sdk.os,
    path: sdk.path,
    clipboard: sdk.clipboard,
    shell: sdk.shell,
    dialog: sdk.dialog,
    fs: sdk.fs,
    notification: sdk.notification,
    process: sdk.process,
  };
});

// i18n 改为 lazy backend (issue #489) 后，测试运行前必须 await 资源加载完，
// 否则首次 t() 返回 key 字符串而不是中文，断言会失败。
await i18nReady;
await i18n.changeLanguage("zh");

// jsdom 默认不实现 ResizeObserver；@floating-ui/react 的 autoUpdate 会调它来
// 跟踪 reference / floating 元素尺寸变化。用空 stub 即可，测试只断言可见性、
// 交互与结构，不验位置像素。
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    constructor(_cb: ResizeObserverCallback) {}
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

if (
  typeof window !== "undefined"
  && (
    typeof window.localStorage?.getItem !== "function"
    || typeof window.localStorage?.setItem !== "function"
    || typeof window.localStorage?.clear !== "function"
  )
) {
  const storage = new Map<string, string>();
  const localStorageMock: Storage = {
    get length() {
      return storage.size;
    },
    clear() {
      storage.clear();
    },
    getItem(key: string) {
      return storage.has(key) ? storage.get(key)! : null;
    },
    key(index: number) {
      return Array.from(storage.keys())[index] ?? null;
    },
    removeItem(key: string) {
      storage.delete(key);
    },
    setItem(key: string, value: string) {
      storage.set(String(key), String(value));
    },
  };
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: localStorageMock,
  });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.clearAllTimers();
  vi.useRealTimers();
  window.localStorage.clear();
  window.sessionStorage.clear();
  document.body.innerHTML = "";
});
