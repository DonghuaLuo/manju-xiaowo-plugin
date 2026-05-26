import { useEffect } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { useEscapeClose } from "@/hooks/useEscapeClose";
import { UI_LAYERS } from "@/utils/ui-layers";

interface VideoLightboxProps {
  src: string;
  title: string;
  poster?: string | null;
  onClose: () => void;
}

export function VideoLightbox({ src, title, poster, onClose }: VideoLightboxProps) {
  useEscapeClose(onClose);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, []);

  if (typeof document === "undefined") return null;

  return createPortal(
    <div className={`fixed inset-0 bg-slate-950/96 backdrop-blur-sm ${UI_LAYERS.modal}`}>
      <button
        type="button"
        aria-label="关闭全屏预览"
        className="absolute inset-0 cursor-default appearance-none border-0 bg-transparent p-0"
        onClick={onClose}
      />

      <div className="absolute right-4 top-4 sm:right-6 sm:top-6">
        <button
          type="button"
          onClick={onClose}
          aria-label="关闭视频预览"
          className="relative z-20 inline-flex h-11 w-11 items-center justify-center rounded-full border border-white/12 bg-black/55 text-white shadow-lg shadow-black/30 backdrop-blur transition-colors hover:bg-black/75"
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      <div className="flex h-full w-full items-center justify-center p-3 sm:p-6 lg:p-8">
        <div
          role="dialog"
          aria-modal="true"
          aria-label={`${title} 全屏预览`}
          className="relative z-10 flex h-full w-full items-center justify-center"
        >
          {/* eslint-disable-next-line jsx-a11y/media-has-caption -- 生成式预览视频暂无字幕源 */}
          <video
            src={src}
            poster={poster ?? undefined}
            controls
            autoPlay
            playsInline
            preload="metadata"
            controlsList="nodownload noremoteplayback"
            className="max-h-full max-w-full rounded-xl border border-white/10 bg-black object-contain shadow-[0_30px_120px_rgba(0,0,0,0.55)]"
          />
        </div>
      </div>
    </div>,
    document.body,
  );
}
