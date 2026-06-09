import { memo, useState, useRef, useCallback, useEffect, useId, useLayoutEffect, useMemo } from "react";
import { PluginSDK } from "xiaowo-sdk";
import { voidCall, voidPromise } from "@/utils/async";
import { Bot, Send, Square, Plus, ChevronDown, Trash2, MessageSquare, ChevronsRight, Paperclip, X, ArrowDown } from "lucide-react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { ImageLightbox } from "@/components/ui/ImageLightbox";
import { useAssistantStore } from "@/stores/assistant-store";
import { useProjectsStore } from "@/stores/projects-store";
import { useAppStore } from "@/stores/app-store";
import { useAssistantSession } from "@/hooks/useAssistantSession";
import type { AttachedImage } from "@/hooks/useAssistantSession";
import { GlassPopover } from "@/components/ui/GlassPopover";
import { ContextBanner } from "./ContextBanner";
import { PendingQuestionWizard } from "./PendingQuestionWizard";
import { SlashCommandMenu } from "./SlashCommandMenu";
import type { SlashCommandMenuHandle } from "./SlashCommandMenu";
import { TodoListPanel } from "./TodoListPanel";
import { ChatMessage } from "./chat/ChatMessage";
import { composeAllTurns } from "./chat/utils";
import { uid } from "@/utils/id";
import { formatShortDateTime } from "@/utils/date-format";
import {
  desktopFileRefFromPath,
  pickDesktopFile,
  readDesktopFileAsDataUrl,
  type DesktopFileRef,
} from "@/utils/desktop-file";

const MAX_IMAGES = 5;
const MAX_IMAGE_BYTES = 5 * 1024 * 1024; // 5MB

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_TEXTAREA_HEIGHT_VH = 50;
const AUTO_SCROLL_THRESHOLD_PX = 48;

// ---------------------------------------------------------------------------
// SessionSelector — 会话下拉选择器
// ---------------------------------------------------------------------------

function SessionSelector({
  onSwitch,
  onDelete,
}: {
  onSwitch: (sessionId: string) => void;
  onDelete: (sessionId: string) => void;
}) {
  const { t } = useTranslation("dashboard");
  const sessions = useAssistantStore((s) => s.sessions);
  const currentSessionId = useAssistantStore((s) => s.currentSessionId);
  const isDraftSession = useAssistantStore((s) => s.isDraftSession);
  const [open, setOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const listboxId = useId();

  const currentSession = sessions.find((s) => s.id === currentSessionId);
  const displayTitle = isDraftSession ? t("new_session") : (currentSession?.title || formatTime(currentSession?.created_at, t));

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? listboxId : undefined}
        className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[11.5px] transition-colors focus-ring"
        style={{ color: "var(--color-text-3)" }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = "oklch(0.26 0.012 265 / 0.6)";
          e.currentTarget.style.color = "var(--color-text)";
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = "transparent";
          e.currentTarget.style.color = "var(--color-text-3)";
        }}
        title={t("switch_session")}
      >
        <MessageSquare className="h-3 w-3" />
        <span className="max-w-24 truncate">{displayTitle || t("no_session")}</span>
        <ChevronDown className={`h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {sessions.length > 0 && (
        <GlassPopover
          open={open}
          onClose={() => setOpen(false)}
          anchorRef={dropdownRef}
          sideOffset={4}
          width="w-64"
          layer="assistantLocalPopover"
          showHairline={false}
        >
          <div id={listboxId} role="menu" className="max-h-60 overflow-y-auto py-1">
            {sessions.map((session) => {
              const isActive = session.id === currentSessionId;
              const title = session.title || formatTime(session.created_at, t);
              return (
                <div
                  key={session.id}
                  className="group flex items-center gap-2 px-3 py-2 text-[12.5px] transition-colors"
                  style={
                    isActive
                      ? {
                          background: "var(--color-accent-dim)",
                          color: "var(--color-accent-2)",
                        }
                      : { color: "var(--color-text-2)" }
                  }
                  onMouseEnter={(e) => {
                    if (!isActive)
                      e.currentTarget.style.background = "oklch(0.26 0.012 265 / 0.5)";
                  }}
                  onMouseLeave={(e) => {
                    if (!isActive) e.currentTarget.style.background = "transparent";
                  }}
                >
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => { onSwitch(session.id); setOpen(false); }}
                    className="flex flex-1 items-center gap-2 truncate text-left"
                  >
                    <StatusDot status={session.status} />
                    <span className="truncate">{title}</span>
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={(e) => { e.stopPropagation(); if (confirm(t("confirm_delete_session"))) onDelete(session.id); }}
                    className="focus-ring shrink-0 rounded p-0.5 opacity-0 transition-all group-hover:opacity-100 focus-visible:opacity-100"
                    style={{ color: "var(--color-text-4)" }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.color = "var(--color-danger)";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.color = "var(--color-text-4)";
                    }}
                    title={t("delete_session")}
                    aria-label={t("delete_session")}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              );
            })}
          </div>
        </GlassPopover>
      )}
    </div>
  );
}

function StatusDot({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    idle: "var(--color-text-4)",
    running: "var(--color-warn)",
    completed: "var(--color-good)",
    error: "var(--color-danger)",
    interrupted: "var(--color-text-3)",
  };
  return (
    <span
      className="h-1.5 w-1.5 shrink-0 rounded-full"
      style={{ background: colorMap[status] ?? "var(--color-text-4)" }}
    />
  );
}

function formatTime(isoStr: string | undefined, t: TFunction): string {
  return formatShortDateTime(isoStr) ?? t("new_session");
}

function isNearScrollBottom(element: HTMLElement): boolean {
  return element.scrollHeight - element.clientHeight - element.scrollTop <= AUTO_SCROLL_THRESHOLD_PX;
}

function scrollElementToBottom(element: HTMLElement, behavior: ScrollBehavior = "auto"): void {
  const top = Math.max(0, element.scrollHeight - element.clientHeight);
  if (typeof element.scrollTo === "function") {
    element.scrollTo({ top, behavior });
    return;
  }
  element.scrollTop = top;
}

const CopilotMessageViewport = memo(function CopilotMessageViewport() {
  const { t } = useTranslation("dashboard");
  const currentSessionId = useAssistantStore((s) => s.currentSessionId);
  const isDraftSession = useAssistantStore((s) => s.isDraftSession);
  const turns = useAssistantStore((s) => s.turns);
  const draftTurn = useAssistantStore((s) => s.draftTurn);
  const messagesLoading = useAssistantStore((s) => s.messagesLoading);
  const scrollRef = useRef<HTMLDivElement>(null);
  const programmaticScrollResetRef = useRef<number | null>(null);
  const programmaticScrollRef = useRef(false);
  const scheduledScrollFrameRef = useRef<number | null>(null);
  const scheduledScrollTimersRef = useRef<number[]>([]);
  const [contentNode, setContentNode] = useState<HTMLDivElement | null>(null);
  const [autoScrollEnabled, setAutoScrollEnabled] = useState(true);
  const autoScrollEnabledRef = useRef(true);
  const allTurns = useMemo(() => composeAllTurns(turns, draftTurn), [turns, draftTurn]);
  const scrollContextKey = currentSessionId ?? (isDraftSession ? "draft" : "none");
  // eslint-disable-next-line react-hooks/incompatible-library -- useVirtualizer 与 React Compiler 不兼容（已知第三方库限制）
  const virtualizer = useVirtualizer({
    count: allTurns.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 160,
    overscan: 8,
    getItemKey: (index) => allTurns[index]?.uuid ?? `turn-${index}`,
  });
  const virtualItems = virtualizer.getVirtualItems();
  const totalSize = virtualizer.getTotalSize();

  const setAutoScrollState = useCallback((enabled: boolean) => {
    autoScrollEnabledRef.current = enabled;
    setAutoScrollEnabled(enabled);
  }, []);

  const clearProgrammaticScrollLock = useCallback(() => {
    programmaticScrollRef.current = false;
    if (programmaticScrollResetRef.current !== null) {
      window.clearTimeout(programmaticScrollResetRef.current);
      programmaticScrollResetRef.current = null;
    }
  }, []);

  const holdProgrammaticScrollLock = useCallback(() => {
    if (programmaticScrollResetRef.current !== null) {
      window.clearTimeout(programmaticScrollResetRef.current);
    }
    programmaticScrollRef.current = true;
    programmaticScrollResetRef.current = window.setTimeout(() => {
      programmaticScrollRef.current = false;
      programmaticScrollResetRef.current = null;
    }, 600);
  }, []);

  const cancelScheduledBottomScroll = useCallback(() => {
    if (scheduledScrollFrameRef.current !== null) {
      window.cancelAnimationFrame(scheduledScrollFrameRef.current);
      scheduledScrollFrameRef.current = null;
    }
    for (const timerId of scheduledScrollTimersRef.current) {
      window.clearTimeout(timerId);
    }
    scheduledScrollTimersRef.current = [];
  }, []);

  const runBottomScrollPass = useCallback(() => {
    if (!autoScrollEnabledRef.current) return;
    const element = scrollRef.current;
    if (!element) return;
    scrollElementToBottom(element);
  }, []);

  const scheduleBottomScrollPasses = useCallback(() => {
    cancelScheduledBottomScroll();
    scheduledScrollFrameRef.current = window.requestAnimationFrame(() => {
      scheduledScrollFrameRef.current = null;
      runBottomScrollPass();
      scheduledScrollTimersRef.current = [
        window.setTimeout(runBottomScrollPass, 80),
        window.setTimeout(runBottomScrollPass, 180),
      ];
    });
  }, [cancelScheduledBottomScroll, runBottomScrollPass]);

  const syncAutoScrollState = useCallback(() => {
    const element = scrollRef.current;
    if (!element) return;
    if (programmaticScrollRef.current) {
      if (isNearScrollBottom(element)) clearProgrammaticScrollLock();
      return;
    }
    setAutoScrollState(isNearScrollBottom(element));
  }, [clearProgrammaticScrollLock, setAutoScrollState]);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "auto") => {
    const element = scrollRef.current;
    if (!element) return;
    if (behavior === "smooth") holdProgrammaticScrollLock();
    scrollElementToBottom(element, behavior);
    setAutoScrollState(true);
    scheduleBottomScrollPasses();
  }, [holdProgrammaticScrollLock, scheduleBottomScrollPasses, setAutoScrollState]);

  useLayoutEffect(() => {
    clearProgrammaticScrollLock();
    cancelScheduledBottomScroll();
    setAutoScrollState(true);
    scrollToBottom();
  }, [cancelScheduledBottomScroll, clearProgrammaticScrollLock, scrollContextKey, scrollToBottom, setAutoScrollState]);

  useLayoutEffect(() => {
    if (!autoScrollEnabledRef.current) return;
    scrollToBottom();
  }, [allTurns, messagesLoading, scrollToBottom, totalSize]);

  useEffect(() => {
    if (typeof ResizeObserver === "undefined") return;
    const scrollNode = scrollRef.current;
    if (!scrollNode) return;
    const observer = new ResizeObserver(() => {
      if (!autoScrollEnabledRef.current) return;
      scrollElementToBottom(scrollNode);
      scheduleBottomScrollPasses();
    });

    observer.observe(scrollNode);
    if (contentNode) observer.observe(contentNode);

    return () => observer.disconnect();
  }, [contentNode, scheduleBottomScrollPasses]);

  useEffect(() => {
    return () => {
      clearProgrammaticScrollLock();
      cancelScheduledBottomScroll();
    };
  }, [cancelScheduledBottomScroll, clearProgrammaticScrollLock]);

  const showJumpToBottom = !autoScrollEnabled && allTurns.length > 0;

  return (
    <div className="relative min-h-0 flex-1">
      <div
        ref={scrollRef}
        data-testid="assistant-messages-scroll"
        onScroll={syncAutoScrollState}
        className="h-full min-w-0 overflow-y-auto overflow-x-hidden px-3 py-3"
      >
        {allTurns.length === 0 && !messagesLoading ? (
          <div ref={setContentNode} className="flex h-full min-h-52 flex-col items-center justify-center text-center">
            <div
              className="mb-3 grid h-12 w-12 place-items-center rounded-2xl"
              style={{
                background:
                  "linear-gradient(135deg, var(--color-accent-dim), oklch(0.22 0.011 265 / 0.6))",
                border: "1px solid var(--color-accent-soft)",
                boxShadow: "0 0 24px -8px var(--color-accent-glow)",
              }}
            >
              <Bot
                className="h-5 w-5"
                style={{ color: "var(--color-accent-2)" }}
              />
            </div>
            <p
              className="display-serif text-[14px] font-semibold"
              style={{ color: "var(--color-text)" }}
            >
              {t("start_chat_hint")}
            </p>
            <p
              className="mt-1 text-[11.5px]"
              style={{ color: "var(--color-text-3)" }}
            >
              {t("quick_skill_hint")}
            </p>
          </div>
        ) : (
          <div
            ref={setContentNode}
            className="relative w-full"
            style={{ height: totalSize > 0 ? `${totalSize}px` : undefined }}
          >
            {virtualItems.map((item) => {
              const turn = allTurns[item.index];
              if (!turn) return null;
              return (
                <div
                  key={item.key}
                  data-index={item.index}
                  ref={virtualizer.measureElement}
                  className="absolute left-0 top-0 w-full pb-3"
                  style={{ transform: `translateY(${item.start}px)` }}
                >
                  <ChatMessage message={turn} />
                </div>
              );
            })}
          </div>
        )}
      </div>

      {showJumpToBottom && (
        <button
          type="button"
          data-testid="assistant-scroll-bottom"
          onClick={() => scrollToBottom("smooth")}
          className="absolute bottom-4 right-4 flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[11.5px] shadow-lg transition-colors focus-ring"
          style={{
            background: "oklch(0.23 0.013 265 / 0.92)",
            border: "1px solid var(--color-accent-soft)",
            color: "var(--color-accent-2)",
            boxShadow: "0 10px 28px -18px var(--color-accent-glow)",
          }}
          aria-label={t("assistant_back_to_bottom", { defaultValue: "回到底部" })}
          title={t("assistant_back_to_bottom", { defaultValue: "回到底部" })}
        >
          <ArrowDown className="h-3.5 w-3.5" />
          <span>{t("assistant_back_to_bottom", { defaultValue: "回到底部" })}</span>
        </button>
      )}
    </div>
  );
});

CopilotMessageViewport.displayName = "CopilotMessageViewport";

const AssistantTodoListPanel = memo(function AssistantTodoListPanel() {
  const turns = useAssistantStore((s) => s.turns);
  const draftTurn = useAssistantStore((s) => s.draftTurn);
  return <TodoListPanel turns={turns} draftTurn={draftTurn} />;
});

AssistantTodoListPanel.displayName = "AssistantTodoListPanel";

// ---------------------------------------------------------------------------
// AgentCopilot — 主面板
// ---------------------------------------------------------------------------

export function AgentCopilot() {
  const { t } = useTranslation(["dashboard", "common"]);
  const sending = useAssistantStore((s) => s.sending);
  const sessionStatus = useAssistantStore((s) => s.sessionStatus);
  const pendingQuestion = useAssistantStore((s) => s.pendingQuestion);
  const answeringQuestion = useAssistantStore((s) => s.answeringQuestion);
  const error = useAssistantStore((s) => s.error);

  const { currentProjectName } = useProjectsStore();
  const toggleAssistantPanel = useAppStore((s) => s.toggleAssistantPanel);
  const { sendMessage, answerQuestion, interrupt, createNewSession, switchSession, deleteSession } =
    useAssistantSession(currentProjectName);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isComposingRef = useRef(false);
  const imageGenRef = useRef(0);
  const slashMenuRef = useRef<SlashCommandMenuHandle>(null);
  const dropActiveRef = useRef(false);
  const dropResetTimerRef = useRef<number | null>(null);
  const [localInput, setLocalInput] = useState("");
  const [showSlashMenu, setShowSlashMenu] = useState(false);
  const [attachedImages, setAttachedImages] = useState<AttachedImage[]>([]);
  const [attachError, setAttachError] = useState<string | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [inputFocused, setInputFocused] = useState(false);
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);
  const isRunning = sessionStatus === "running";
  const inputDisabled = Boolean(pendingQuestion) || answeringQuestion || isRunning || sending;
  const attachDisabled = inputDisabled || attachedImages.length >= MAX_IMAGES;
  const inputPlaceholder = pendingQuestion
    ? t("answer_above_hint")
    : isRunning
      ? t("generating_stop_hint")
      : t("input_placeholder");

  const clearDropResetTimer = useCallback(() => {
    if (dropResetTimerRef.current !== null) {
      window.clearTimeout(dropResetTimerRef.current);
      dropResetTimerRef.current = null;
    }
  }, []);

  const scheduleDropReset = useCallback(() => {
    clearDropResetTimer();
    dropResetTimerRef.current = window.setTimeout(() => {
      dropActiveRef.current = false;
      setIsDragOver(false);
      dropResetTimerRef.current = null;
    }, 1200);
  }, [clearDropResetTimer]);

  const addImages = useCallback((files: File[]) => {
    setAttachError(null);
    const gen = imageGenRef.current;
    for (const file of files) {
      if (!file.type.startsWith("image/")) continue;
      if (file.size > MAX_IMAGE_BYTES) {
        setAttachError(t("image_too_large_hint", { name: file.name }));
        continue;
      }
      const reader = new FileReader();
      reader.onload = (e) => {
        if (imageGenRef.current !== gen) return; // stale — message already sent
        const dataUrl = e.target?.result as string;
        setAttachedImages((prev) => {
          if (prev.length >= MAX_IMAGES) return prev;
          return [...prev, { id: uid(), dataUrl, mimeType: file.type }];
        });
      };
      reader.readAsDataURL(file);
    }
  }, [t]);

  const addDesktopImage = useCallback(async (file: DesktopFileRef) => {
    if (attachDisabled) return;
    setAttachError(null);
    try {
      const image = await readDesktopFileAsDataUrl(file, MAX_IMAGE_BYTES);
      if (!image.mimeType.startsWith("image/")) {
        setAttachError(t("source_unsupported_extension", { filename: file.name }));
        return;
      }
      setAttachedImages((prev) => {
        if (prev.length >= MAX_IMAGES) return prev;
        return [
          ...prev,
          {
            id: uid(),
            dataUrl: image.dataUrl,
            mimeType: image.mimeType,
          },
        ];
      });
    } catch (err) {
      setAttachError(err instanceof Error ? err.message : String(err));
    }
  }, [attachDisabled, t]);

  const handlePickImage = useCallback(async () => {
    if (attachDisabled) return;

    const file = await pickDesktopFile({
      title: t("upload_attachment_aria"),
      filters: [
        { name: "Images", extensions: ["png", "jpg", "jpeg", "webp", "gif"] },
      ],
      preview: true,
    });
    if (file) await addDesktopImage(file);
  }, [addDesktopImage, attachDisabled, t]);

  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    const items = Array.from(e.clipboardData.items);
    const imageItems = items.filter((item) => item.type.startsWith("image/"));
    if (imageItems.length === 0) return;
    e.preventDefault();
    const files = imageItems.map((item) => item.getAsFile()).filter(Boolean) as File[];
    addImages(files);
  }, [addImages]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    const hasFiles = Array.from(e.dataTransfer.items).some((i) => i.kind === "file");
    if (!hasFiles) return;
    e.preventDefault();
    dropActiveRef.current = true;
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    dropActiveRef.current = false;
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    dropActiveRef.current = true;
    setIsDragOver(false);
    scheduleDropReset();
  }, [scheduleDropReset]);

  useEffect(() => {
    const handleFileDrop = (paths: string[]) => {
      if (!dropActiveRef.current || attachDisabled) return;
      clearDropResetTimer();
      dropActiveRef.current = false;
      setIsDragOver(false);
      voidCall((async () => {
        for (const path of paths.slice(0, MAX_IMAGES)) {
          await addDesktopImage(desktopFileRefFromPath(path, { preview: true }));
        }
      })());
    };
    const handleCancelled = () => {
      clearDropResetTimer();
      dropActiveRef.current = false;
      setIsDragOver(false);
    };
    PluginSDK.onFileDrop(handleFileDrop);
    PluginSDK.onFileDropCancelled(handleCancelled);
    return () => {
      clearDropResetTimer();
      PluginSDK.offFileDrop(handleFileDrop);
      PluginSDK.offFileDropCancelled(handleCancelled);
    };
  }, [addDesktopImage, attachDisabled, clearDropResetTimer]);

  const removeImage = useCallback((id: string) => {
    setAttachedImages((prev) => prev.filter((img) => img.id !== id));
    setAttachError(null);
  }, []);

  const handleSend = useCallback(() => {
    if (inputDisabled || (!localInput.trim() && attachedImages.length === 0)) return;
    imageGenRef.current += 1; // invalidate pending FileReader callbacks
    voidCall(sendMessage(localInput.trim(), attachedImages.length > 0 ? attachedImages : undefined));
    setLocalInput("");
    setAttachedImages([]);
    setAttachError(null);
    setShowSlashMenu(false);
    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [inputDisabled, localInput, attachedImages, sendMessage]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Delegate to slash menu when open
    if (showSlashMenu && slashMenuRef.current) {
      const consumed = slashMenuRef.current.handleKeyDown(e.key);
      if (consumed) {
        e.preventDefault();
        if (e.key === "Escape") setShowSlashMenu(false);
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      const nativeEvent = e.nativeEvent;
      if (nativeEvent.isComposing || nativeEvent.keyCode === 229 || isComposingRef.current) {
        return;
      }
      e.preventDefault();
      handleSend();
    }
  }, [handleSend, showSlashMenu]);

  // Track the slash "/" position so we know where the command token starts
  const slashPosRef = useRef(-1);

  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value;
    const cursor = e.target.selectionStart ?? val.length;
    setLocalInput(val);

    // Check text left of cursor: trigger menu when "/" is at start or after whitespace/newline
    const textBeforeCursor = val.slice(0, cursor);
    const lastSlash = textBeforeCursor.lastIndexOf("/");
    if (lastSlash >= 0) {
      const charBefore = lastSlash > 0 ? textBeforeCursor[lastSlash - 1] : undefined;
      const atBoundary = charBefore === undefined || /\s/.test(charBefore);
      const afterSlash = textBeforeCursor.slice(lastSlash + 1);
      const noSpaceAfterSlash = !afterSlash.includes(" ");
      if (atBoundary && noSpaceAfterSlash) {
        setShowSlashMenu(true);
        slashPosRef.current = lastSlash;
      } else {
        setShowSlashMenu(false);
        slashPosRef.current = -1;
      }
    } else {
      setShowSlashMenu(false);
      slashPosRef.current = -1;
    }

    // Auto-resize: grow upward until 50vh, then scroll
    const el = e.target;
    el.style.height = "auto";
    const maxH = window.innerHeight * (MAX_TEXTAREA_HEIGHT_VH / 100);
    el.style.height = `${Math.min(el.scrollHeight, maxH)}px`;
    el.style.overflowY = el.scrollHeight > maxH ? "auto" : "hidden";
  }, []);

  // Derive slash filter from input (text after "/" up to cursor)
  // eslint-disable-next-line react-hooks/refs -- slashPosRef 同时被 render 和 handleSlashSelect 使用，转 state 会引入 stale-closure 问题；此处仅用于过滤展示，不影响 UI 一致性
  const slashFilter = showSlashMenu && slashPosRef.current >= 0
    // eslint-disable-next-line react-hooks/refs -- 同上
    ? localInput.slice(slashPosRef.current + 1).split(/\s/)[0]
    : "";

  const handleSlashSelect = useCallback((cmd: string) => {
    // Replace the "/filter" token with the selected command, keep surrounding text
    const pos = slashPosRef.current;
    if (pos >= 0) {
      const before = localInput.slice(0, pos);
      // Find end of the slash token (next whitespace or end of string)
      const afterSlash = localInput.slice(pos);
      const tokenEnd = afterSlash.search(/\s/);
      const after = tokenEnd >= 0 ? localInput.slice(pos + tokenEnd) : "";
      setLocalInput(before + cmd + " " + after.trimStart());
    } else {
      setLocalInput(localInput + cmd + " ");
    }
    setShowSlashMenu(false);
    slashPosRef.current = -1;
    textareaRef.current?.focus();
  }, [localInput]);

  const handleInputShellMouseDown = useCallback((e: React.MouseEvent<HTMLButtonElement>) => {
    if (inputDisabled) return;
    e.preventDefault();
    textareaRef.current?.focus();
  }, [inputDisabled]);

  return (
    <div
      className="relative isolate flex h-full flex-col"
      style={{ background: "oklch(0.19 0.011 250 / 0.5)" }}
    >
      {/* Header */}
      <div
        className="flex h-12 items-center gap-2 px-3"
        style={{ borderBottom: "1px solid var(--color-hairline)" }}
      >
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <div
            className="grid h-6 w-6 shrink-0 place-items-center rounded-md"
            style={{
              background:
                "linear-gradient(135deg, var(--color-accent), oklch(0.60 0.10 280))",
              color: "oklch(0.12 0 0)",
            }}
          >
            <Bot className="h-3.5 w-3.5" />
          </div>
          {isRunning ? (
            <span
              className="flex shrink-0 items-center gap-1.5 whitespace-nowrap text-[12px]"
              style={{ color: "var(--color-accent-2)" }}
              title={t("arcreel_agent")}
            >
              <span
                className="h-1.5 w-1.5 animate-pulse rounded-full"
                style={{ background: "var(--color-accent)" }}
              />
              {t("thinking")}
            </span>
          ) : (
            <span className="display-serif min-w-0 truncate text-[13px] font-semibold leading-[1.1]">
              {t("arcreel_agent")}
            </span>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <SessionSelector onSwitch={voidPromise(switchSession)} onDelete={voidPromise(deleteSession)} />
          <button
            type="button"
            onClick={createNewSession}
            className="rounded p-1 transition-colors focus-ring"
            style={{ color: "var(--color-text-3)" }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = "oklch(0.26 0.012 265 / 0.6)";
              e.currentTarget.style.color = "var(--color-text)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "transparent";
              e.currentTarget.style.color = "var(--color-text-3)";
            }}
            title={t("new_session")}
            aria-label={t("new_session")}
          >
            <Plus aria-hidden className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Context banner */}
      <ContextBanner />

      {/* Messages */}
      <CopilotMessageViewport />

      {pendingQuestion && (
        <PendingQuestionWizard
          pendingQuestion={pendingQuestion}
          answeringQuestion={answeringQuestion}
          error={error}
          onSubmitAnswers={voidPromise(answerQuestion)}
        />
      )}

      <AssistantTodoListPanel />

      {!pendingQuestion && (error || attachError) && (
        <div
          role="alert"
          aria-live="assertive"
          className="px-3 py-2 text-[11.5px]"
          style={{
            borderTop: "1px solid oklch(0.70 0.18 25 / 0.3)",
            background: "oklch(0.70 0.18 25 / 0.12)",
            color: "oklch(0.85 0.10 25)",
          }}
        >
          {error || attachError}
        </div>
      )}

      {/* Input area */}
      <div
        className="relative p-3"
        style={{ borderTop: "1px solid var(--color-hairline-soft)" }}
      >
        <button
          type="button"
          onClick={toggleAssistantPanel}
          className="absolute bottom-0 left-0 z-20 cursor-pointer bg-transparent p-0 transition-colors focus-ring"
          style={{
            color: "var(--color-text-3)",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.color = "var(--color-accent-2)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.color = "var(--color-text-3)";
          }}
          title={t("collapse_panel")}
          aria-label={t("collapse_panel")}
        >
          <ChevronsRight aria-hidden className="h-4 w-4" />
        </button>

        {/* Thumbnail strip */}
        {attachedImages.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2">
            {attachedImages.map((img) => (
              <div key={img.id} className="relative">
                <button
                  type="button"
                  className="h-16 w-16 cursor-pointer border-0 bg-transparent p-0"
                  onClick={() => setLightboxSrc(img.dataUrl)}
                  aria-label={t("enlarge_image")}
                >
                  <img
                    src={img.dataUrl}
                    alt={t("assistant_input")}
                    className="h-16 w-16 rounded-md object-cover"
                    style={{ border: "1px solid var(--color-hairline)" }}
                  />
                </button>
                <button
                  type="button"
                  onClick={() => removeImage(img.id)}
                  className="absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full transition-colors focus-ring"
                  style={{
                    background: "oklch(0.14 0.008 265)",
                    color: "var(--color-text-2)",
                    border: "1px solid var(--color-hairline)",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = "var(--color-danger)";
                    e.currentTarget.style.color = "oklch(0.14 0 0)";
                    e.currentTarget.style.borderColor = "var(--color-danger)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = "oklch(0.14 0.008 265)";
                    e.currentTarget.style.color = "var(--color-text-2)";
                    e.currentTarget.style.borderColor = "var(--color-hairline)";
                  }}
                  aria-label={t("remove_image")}
                >
                  <X className="h-2.5 w-2.5" />
                </button>
              </div>
            ))}
          </div>
        )}

        <div
          className="relative mb-[5px] min-h-[76px] rounded-lg pb-10 pl-3 pr-0 pt-2 transition-colors"
          style={{
            background: isDragOver
              ? "var(--color-accent-dim)"
              : inputFocused
                ? "oklch(0.245 0.014 265 / 0.86)"
                : "oklch(0.225 0.012 265 / 0.78)",
            backdropFilter: "blur(8px)",
            WebkitBackdropFilter: "blur(8px)",
            boxShadow: isDragOver
              ? "0 0 0 3px var(--color-accent-soft)"
              : inputFocused
                ? "0 10px 28px -24px var(--color-accent-glow), inset 0 1px 0 oklch(1 0 0 / 0.035)"
                : "inset 0 1px 0 oklch(1 0 0 / 0.025)",
          }}
          onFocus={() => setInputFocused(true)}
          onBlur={(e) => {
            const next = e.relatedTarget;
            if (!next || !e.currentTarget.contains(next)) {
              setInputFocused(false);
            }
          }}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <button
            type="button"
            tabIndex={-1}
            aria-hidden="true"
            data-testid="assistant-input-shell-focus"
            onMouseDown={handleInputShellMouseDown}
            className="absolute inset-0 z-0 cursor-text rounded-lg border-0 bg-transparent p-0"
            disabled={inputDisabled}
          />
          {showSlashMenu && (
            <SlashCommandMenu
              ref={slashMenuRef}
              filter={slashFilter}
              onSelect={handleSlashSelect}
            />
          )}
          <textarea
            ref={textareaRef}
            role="combobox"
            value={localInput}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            onCompositionStart={() => {
              isComposingRef.current = true;
            }}
            onCompositionEnd={() => {
              isComposingRef.current = false;
            }}
            onPaste={handlePaste}
            placeholder={inputPlaceholder}
            rows={1}
            aria-label={t("assistant_input")}
            aria-expanded={showSlashMenu}
            aria-controls={showSlashMenu ? "slash-command-menu" : undefined}
            aria-activedescendant={
              // eslint-disable-next-line react-hooks/refs -- aria-activedescendant 需实时读取 slashMenuRef 的派生值，改用回调 prop 需修改 SlashCommandMenu 接口，超出范围
              slashMenuRef.current?.activeDescendantId
            }
            className="relative z-10 block w-full resize-none overflow-hidden bg-transparent pb-1 text-[13px] outline-none"
            style={{
              maxHeight: `${MAX_TEXTAREA_HEIGHT_VH}vh`,
              color: "var(--color-text)",
            }}
            disabled={inputDisabled}
          />

          <div className="absolute bottom-2 right-2 z-10 flex items-center gap-1">
            {/* Attachment button */}
            <button
              type="button"
              onClick={voidPromise(handlePickImage)}
              disabled={attachDisabled}
              className="shrink-0 rounded p-1.5 transition-colors focus-ring disabled:opacity-30"
              style={{ color: "var(--color-text-3)" }}
              onMouseEnter={(e) => {
                if (!attachDisabled) {
                  e.currentTarget.style.background = "oklch(0.26 0.012 265 / 0.6)";
                  e.currentTarget.style.color = "var(--color-text)";
                }
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = "transparent";
                e.currentTarget.style.color = "var(--color-text-3)";
              }}
              title={attachedImages.length >= MAX_IMAGES ? t("max_images_hint", { count: MAX_IMAGES }) : t("attach_image")}
              aria-label={t("attach_image")}
            >
              <Paperclip className="h-4 w-4" />
            </button>

            {isRunning ? (
              <button
                onClick={voidPromise(interrupt)}
                className="shrink-0 rounded p-1.5 transition-colors focus-ring"
                style={{ color: "var(--color-danger)" }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = "oklch(0.70 0.18 25 / 0.15)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = "transparent";
                }}
                title={t("stop_session")}
                aria-label={t("stop_session")}
              >
                <Square className="h-4 w-4" />
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={(!localInput.trim() && attachedImages.length === 0) || inputDisabled}
                className="shrink-0 rounded-md p-1.5 transition-opacity focus-ring disabled:cursor-not-allowed disabled:opacity-30"
                style={{
                  color: "oklch(0.14 0 0)",
                  background:
                    "linear-gradient(180deg, var(--color-accent-2), var(--color-accent))",
                  boxShadow:
                    "inset 0 1px 0 oklch(1 0 0 / 0.3), 0 4px 14px -4px var(--color-accent-glow)",
                }}
                title={t("send_message")}
                aria-label={t("send_message")}
              >
                <Send className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>

      </div>

      {lightboxSrc && (
        <ImageLightbox
          src={lightboxSrc}
          alt={t("assistant_input")}
          onClose={() => setLightboxSrc(null)}
        />
      )}
    </div>
  );
}
