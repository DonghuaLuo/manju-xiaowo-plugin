import {
  useEffect,
  useRef,
  useState,
  type MouseEvent,
  type PointerEvent,
  type WheelEvent,
} from "react";
import { createPortal } from "react-dom";
import { Copy, Download, Loader2, X } from "lucide-react";
import { UI_LAYERS } from "@/utils/ui-layers";
import { useEscapeClose } from "@/hooks/useEscapeClose";
import { useAppStore } from "@/stores/app-store";
import {
  copyImageToClipboard,
  downloadImageWithDialog,
  type ImageDownloadSource,
} from "@/utils/image-export";
import { errMsg } from "@/utils/async";

export interface ImageLightboxProps {
  src: string;
  alt: string;
  downloadSource?: ImageDownloadSource;
  onClose: () => void;
}

interface ImageViewport {
  scale: number;
  x: number;
  y: number;
}

interface DragState {
  pointerId: number;
  startX: number;
  startY: number;
  originX: number;
  originY: number;
}

type MenuAction = "copy" | "download";

const MIN_SCALE = 1;
const MAX_SCALE = 6;
const WHEEL_ZOOM_FACTOR = 1.12;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function ImageLightbox({ src, alt, downloadSource, onClose }: ImageLightboxProps) {
  const dragRef = useRef<DragState | null>(null);
  const [viewport, setViewport] = useState<ImageViewport>({
    scale: 1,
    x: 0,
    y: 0,
  });
  const [dragging, setDragging] = useState(false);
  const [menuPos, setMenuPos] = useState<{ x: number; y: number } | null>(null);
  const [busyAction, setBusyAction] = useState<MenuAction | null>(null);

  useEscapeClose(onClose);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, []);

  if (typeof document === "undefined") {
    return null;
  }

  const handleWheel = (event: WheelEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setMenuPos(null);
    const direction = event.deltaY < 0 ? 1 : -1;

    setViewport((current) => {
      const nextScale = clamp(
        current.scale * (direction > 0 ? WHEEL_ZOOM_FACTOR : 1 / WHEEL_ZOOM_FACTOR),
        MIN_SCALE,
        MAX_SCALE,
      );

      if (nextScale === MIN_SCALE) {
        return { scale: MIN_SCALE, x: 0, y: 0 };
      }

      return {
        ...current,
        scale: nextScale,
      };
    });
  };

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    setMenuPos(null);
    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: viewport.x,
      originY: viewport.y,
    };
    setDragging(true);
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };

  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    event.preventDefault();
    event.stopPropagation();
    setViewport((current) => ({
      ...current,
      x: drag.originX + event.clientX - drag.startX,
      y: drag.originY + event.clientY - drag.startY,
    }));
  };

  const stopDragging = (event: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    event.preventDefault();
    event.stopPropagation();
    dragRef.current = null;
    setDragging(false);
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const openContextMenu = (event: MouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
    setMenuPos({ x: event.clientX, y: event.clientY });
  };

  const runMenuAction = async (action: MenuAction) => {
    if (busyAction) return;
    setBusyAction(action);
    try {
      if (action === "copy") {
        await copyImageToClipboard(src);
        useAppStore.getState().pushToast("图片已复制", "success");
      } else {
        if (!downloadSource) {
          throw new Error("缺少可下载的本地图片文件路径");
        }
        const savedPath = await downloadImageWithDialog(downloadSource, alt);
        if (savedPath) {
          useAppStore.getState().pushToast("图片已保存", "success");
        }
      }
      setMenuPos(null);
    } catch (error) {
      useAppStore.getState().pushToast(errMsg(error), "error");
    } finally {
      setBusyAction(null);
    }
  };

  return createPortal(
    <div className={`fixed inset-0 bg-slate-950/94 backdrop-blur-sm ${UI_LAYERS.modal}`}>
      {/* backdrop: click-to-close */}
      <button
        type="button"
        aria-label="关闭全屏预览"
        className="absolute inset-0 cursor-default appearance-none border-0 bg-transparent p-0"
        onClick={onClose}
      />

      <div className="absolute right-4 top-4 z-30 sm:right-6 sm:top-6">
        <button
          type="button"
          onClick={onClose}
          aria-label="关闭图片预览"
          className="relative inline-flex h-11 w-11 items-center justify-center rounded-full border border-white/12 bg-black/55 text-white shadow-lg shadow-black/30 backdrop-blur transition-colors hover:bg-black/75"
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      <div className="flex h-full w-full items-center justify-center overflow-hidden p-5 sm:p-8 lg:p-12">
        <div
          role="dialog"
          aria-modal="true"
          aria-label={`${alt} 全屏预览`}
          className={
            "relative z-10 max-h-full max-w-full touch-none select-none " +
            (dragging ? "cursor-grabbing" : "cursor-grab")
          }
          onWheel={handleWheel}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={stopDragging}
          onPointerCancel={stopDragging}
        >
          <img
            src={src}
            alt={alt}
            onContextMenu={openContextMenu}
            className="max-h-[calc(100vh-3rem)] max-w-[calc(100vw-2rem)] rounded-2xl border border-white/10 bg-black/35 object-contain shadow-[0_30px_120px_rgba(0,0,0,0.55)] sm:max-h-[calc(100vh-5rem)] sm:max-w-[calc(100vw-4rem)]"
            draggable={false}
            style={{
              transform: `translate3d(${viewport.x}px, ${viewport.y}px, 0) scale(${viewport.scale})`,
              transformOrigin: "center center",
            }}
          />
        </div>
      </div>

      {menuPos && (
        <div
          className="fixed z-50 min-w-32 overflow-hidden rounded-lg border border-white/10 bg-slate-950/95 p-1 text-[12px] text-white shadow-2xl shadow-black/50 backdrop-blur"
          style={{
            left: menuPos.x,
            top: menuPos.y,
          }}
        >
          <button
            type="button"
            disabled={busyAction !== null}
            onClick={() => void runMenuAction("copy")}
            className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-white/10 disabled:opacity-60"
          >
            {busyAction === "copy" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
            <span>复制</span>
          </button>
          {downloadSource && (
            <button
              type="button"
              disabled={busyAction !== null}
              onClick={() => void runMenuAction("download")}
              className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-white/10 disabled:opacity-60"
            >
              {busyAction === "download" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Download className="h-3.5 w-3.5" />
              )}
              <span>下载</span>
            </button>
          )}
        </div>
      )}
    </div>,
    document.body,
  );
}
