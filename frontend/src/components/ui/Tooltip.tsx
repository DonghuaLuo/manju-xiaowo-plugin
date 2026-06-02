import { createContext, useContext, useId, useRef, useState, type ReactNode, type RefObject } from "react";
import { Popover } from "@/components/ui/Popover";

interface TooltipContextValue {
  open: boolean;
  contentId: string;
  triggerRef: RefObject<HTMLSpanElement | null>;
  show: () => void;
  hide: () => void;
}

const TooltipContext = createContext<TooltipContextValue | null>(null);

function useTooltipContext() {
  const context = useContext(TooltipContext);
  if (!context) throw new Error("Tooltip components must be used inside <Tooltip>");
  return context;
}

function TooltipProvider({ children }: { children: ReactNode }) {
  return <>{children}</>;
}

function Tooltip({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const contentId = useId();
  const triggerRef = useRef<HTMLSpanElement | null>(null);

  return (
    <TooltipProvider>
      <TooltipContext.Provider
        value={{
          open,
          contentId,
          triggerRef,
          show: () => setOpen(true),
          hide: () => setOpen(false),
        }}
      >
        {children}
      </TooltipContext.Provider>
    </TooltipProvider>
  );
}

function TooltipTrigger({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  const { contentId, triggerRef, show, hide } = useTooltipContext();
  return (
    <span
      ref={triggerRef}
      aria-describedby={contentId}
      className={`inline-flex ${className}`}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
    >
      {children}
    </span>
  );
}

function TooltipContent({
  children,
  side = "top",
  sideOffset = 8,
  className = "",
}: {
  children: ReactNode;
  side?: "top" | "right" | "bottom" | "left";
  sideOffset?: number;
  className?: string;
}) {
  const { open, contentId, triggerRef, show, hide } = useTooltipContext();
  return (
    <Popover
      open={open}
      anchorRef={triggerRef}
      placement={side}
      sideOffset={sideOffset}
      width="w-auto"
      backgroundColor="transparent"
      className={`pointer-events-none rounded-md border border-hairline bg-[oklch(0.18_0.011_270_/_0.98)] px-2.5 py-1.5 shadow-[0_14px_36px_-18px_oklch(0_0_0_/_0.8)] ${className}`}
    >
      <div
        id={contentId}
        role="tooltip"
        onMouseEnter={show}
        onMouseLeave={hide}
        className="max-w-[220px] text-left text-[12px] font-medium leading-snug text-text"
      >
        {children}
      </div>
    </Popover>
  );
}

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider };
