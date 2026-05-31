import {
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
} from "react";
import { ZoomIn } from "lucide-react";
import { ImageLightbox } from "./ImageLightbox";
import type { ImageDownloadSource } from "@/utils/image-export";

interface PreviewableImageFrameProps {
  src: string | null;
  alt: string;
  children: ReactNode;
  buttonClassName?: string;
  downloadSource?: ImageDownloadSource;
  showPreviewIcon?: boolean;
}

const INTERACTIVE_CHILD_SELECTOR =
  "button,a,input,textarea,select,[role='button'],[role='link'],[tabindex]:not([tabindex='-1'])";

function isNestedInteractiveTarget(
  target: EventTarget | null,
  container: HTMLElement,
): boolean {
  if (!(target instanceof Element)) return false;
  const interactive = target.closest(INTERACTIVE_CHILD_SELECTOR);
  return Boolean(interactive && interactive !== container && container.contains(interactive));
}

export function PreviewableImageFrame({
  src,
  alt,
  children,
  buttonClassName,
  downloadSource,
  showPreviewIcon = true,
}: PreviewableImageFrameProps) {
  const [open, setOpen] = useState(false);
  const previewLabel = `${alt} 全屏预览`;

  const openPreview = () => {
    if (src) setOpen(true);
  };

  const handleClick = (event: MouseEvent<HTMLDivElement>) => {
    if (!src || isNestedInteractiveTarget(event.target, event.currentTarget)) return;
    openPreview();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!src || event.target !== event.currentTarget) return;
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    openPreview();
  };

  return (
    <>
      <div
        role={src ? "button" : undefined}
        tabIndex={src ? 0 : undefined}
        aria-label={src ? previewLabel : undefined}
        onClick={handleClick}
        onKeyDown={handleKeyDown}
        className={
          "group relative " +
          (src
            ? "cursor-zoom-in focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/24 "
            : "")
        }
      >
        {children}
        {src && showPreviewIcon && (
          <span
            aria-hidden="true"
            className={
              "pointer-events-none absolute right-1.5 top-1.5 inline-flex h-7 w-7 items-center justify-center rounded-full border border-white/10 bg-slate-950/40 text-white/84 opacity-100 shadow-[0_8px_18px_rgba(15,23,42,0.24)] backdrop-blur-md transition-all sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100 " +
              (buttonClassName ?? "")
            }
          >
            <ZoomIn className="h-3 w-3" />
          </span>
        )}
      </div>

      {open && src && (
        <ImageLightbox
          src={src}
          alt={alt}
          downloadSource={downloadSource}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}
