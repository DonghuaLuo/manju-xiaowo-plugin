import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { Check, ChevronDown } from "lucide-react";
import { Popover } from "@/components/ui/Popover";
import { DROPDOWN_PANEL_CLS, SELECT_MENU_PANEL_STYLE } from "@/components/ui/darkroom-tokens";

export interface SelectMenuOption {
  value: string;
  label: ReactNode;
  description?: ReactNode;
  hint?: ReactNode;
  disabled?: boolean;
}

interface SelectMenuProps {
  id?: string;
  value: string;
  options: readonly SelectMenuOption[];
  onChange: (value: string) => void;
  ariaLabel?: string;
  disabled?: boolean;
  placeholder?: ReactNode;
  panelLabel?: ReactNode;
  className?: string;
  triggerClassName?: string;
  triggerSize?: "default" | "compact" | "tiny" | "micro";
  maxHeightClassName?: string;
  minPanelWidth?: number;
}

const TRIGGER_BASE_CLS =
  "focus-ring inline-flex items-center justify-between gap-2 border transition-colors disabled:cursor-not-allowed disabled:opacity-50";

const TRIGGER_SIZE_CLS: Record<NonNullable<SelectMenuProps["triggerSize"]>, string> = {
  default:
    "w-full rounded-[8px] border-hairline bg-bg-grad-a/55 px-3 py-2 text-[13px] text-text hover:border-hairline-strong hover:bg-bg-grad-a/65",
  compact:
    "min-w-[8rem] rounded-[7px] border-hairline-soft bg-bg-grad-a/45 px-3 py-1.5 text-[12px] text-text-2 hover:border-hairline hover:text-text",
  tiny:
    "rounded-[6px] border-hairline bg-bg-grad-a/55 px-2 py-1 text-[11.5px] text-text-2 hover:border-hairline-strong hover:text-text",
  micro:
    "rounded-[5px] border-hairline bg-bg-grad-a/55 px-1.5 py-0.5 text-[11px] text-text-2 hover:border-hairline-strong hover:text-text",
};

export function SelectMenu({
  id,
  value,
  options,
  onChange,
  ariaLabel,
  disabled,
  placeholder,
  panelLabel,
  className,
  triggerClassName,
  triggerSize = "default",
  maxHeightClassName = "max-h-56",
  minPanelWidth = 160,
}: SelectMenuProps) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [panelWidth, setPanelWidth] = useState<number | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listboxRef = useRef<HTMLDivElement>(null);
  const listboxId = useId();

  const selectedIndex = useMemo(
    () => options.findIndex((option) => option.value === value),
    [options, value],
  );
  const selected = selectedIndex >= 0 ? options[selectedIndex] : undefined;

  useEffect(() => {
    if (!open) return;
    const rect = triggerRef.current?.getBoundingClientRect();
    if (rect) setPanelWidth(Math.max(rect.width, minPanelWidth));
    setActiveIndex(selectedIndex >= 0 ? selectedIndex : 0);
    const id = requestAnimationFrame(() => listboxRef.current?.focus());
    return () => cancelAnimationFrame(id);
  }, [open, minPanelWidth, selectedIndex]);

  const closeAndFocusTrigger = () => {
    setOpen(false);
    requestAnimationFrame(() => triggerRef.current?.focus());
  };

  const selectOption = (option: SelectMenuOption) => {
    if (option.disabled) return;
    onChange(option.value);
    closeAndFocusTrigger();
  };

  const moveActive = (delta: number) => {
    if (options.length === 0) return;
    setActiveIndex((prev) => {
      let next = prev;
      for (let i = 0; i < options.length; i += 1) {
        next = (next + delta + options.length) % options.length;
        if (!options[next]?.disabled) return next;
      }
      return prev;
    });
  };

  const onTriggerKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>) => {
    if (disabled) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      setOpen(true);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  const onListboxKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      moveActive(1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      moveActive(-1);
    } else if (e.key === "Home") {
      e.preventDefault();
      setActiveIndex(0);
    } else if (e.key === "End") {
      e.preventDefault();
      setActiveIndex(Math.max(0, options.length - 1));
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      const option = options[activeIndex];
      if (option) selectOption(option);
    } else if (e.key === "Escape") {
      e.preventDefault();
      closeAndFocusTrigger();
    }
  };

  return (
    <>
      <button
        ref={triggerRef}
        id={id}
        type="button"
        role="combobox"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listboxId : undefined}
        aria-activedescendant={open ? `${listboxId}-option-${activeIndex}` : undefined}
        disabled={disabled}
        value={value}
        data-value={value}
        onClick={() => setOpen((prev) => !prev)}
        onKeyDown={onTriggerKeyDown}
        className={`${TRIGGER_BASE_CLS} ${TRIGGER_SIZE_CLS[triggerSize]} ${className ?? ""} ${triggerClassName ?? ""}`}
      >
        <span className={`min-w-0 flex-1 truncate text-left ${selected ? "" : "text-text-4"}`}>
          {selected?.label ?? placeholder ?? value}
        </span>
        <ChevronDown
          className={`h-3.5 w-3.5 shrink-0 text-text-4 transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden="true"
        />
      </button>

      <Popover
        open={open}
        onClose={() => setOpen(false)}
        anchorRef={triggerRef}
        align="start"
        layer="modal"
        sideOffset={5}
        width=""
        className={DROPDOWN_PANEL_CLS}
        style={{
          ...SELECT_MENU_PANEL_STYLE,
          width: panelWidth ?? undefined,
          minWidth: minPanelWidth,
        }}
      >
        {panelLabel && (
          <div className="px-2 py-1.5">
            <div
              className="font-mono text-[9.5px] font-bold uppercase text-text-4"
              style={{ letterSpacing: "0.8px" }}
            >
              {panelLabel}
            </div>
          </div>
        )}
        <div
          ref={listboxRef}
          id={listboxId}
          role="listbox"
          aria-label={ariaLabel}
          tabIndex={-1}
          onKeyDown={onListboxKeyDown}
          className={`${maxHeightClassName} overflow-y-auto outline-none`}
        >
          {options.map((option, index) => {
            const selectedOption = option.value === value;
            const active = index === activeIndex;
            const hasDescription = Boolean(option.description);
            return (
              <button
                key={option.value}
                id={`${listboxId}-option-${index}`}
                type="button"
                role="option"
                aria-selected={selectedOption}
                disabled={option.disabled}
                onClick={() => selectOption(option)}
                onMouseEnter={() => setActiveIndex(index)}
                className={`focus-ring flex w-full gap-2 rounded-md px-2 text-left transition-colors hover:bg-[oklch(1_0_0_/_0.08)] disabled:cursor-not-allowed disabled:opacity-45 ${
                  hasDescription ? "items-start py-2" : "items-center py-1.5"
                }`}
                style={{
                  background:
                    selectedOption || active
                      ? "linear-gradient(135deg, var(--color-accent-dim), oklch(0.22 0.014 265 / 0.7))"
                      : "transparent",
                }}
              >
                <span className="min-w-0 flex-1">
                  <span
                    className="block truncate text-[12.5px] font-semibold"
                    style={{
                      color: selectedOption ? "var(--color-accent-2)" : "var(--color-text-2)",
                    }}
                  >
                    {option.label}
                  </span>
                  {hasDescription && (
                    <span className="mt-0.5 block whitespace-normal text-[11.5px] leading-[1.45] text-text-4">
                      {option.description}
                    </span>
                  )}
                </span>
                {option.hint && (
                  <span className={`ml-auto shrink-0 font-mono text-[10.5px] text-text-4 ${hasDescription ? "mt-0.5" : ""}`}>
                    {option.hint}
                  </span>
                )}
                <Check
                  className={`h-3.5 w-3.5 shrink-0 text-accent-2 ${hasDescription ? "mt-0.5" : ""} ${
                    selectedOption ? "opacity-100" : "opacity-0"
                  }`}
                  aria-hidden="true"
                />
              </button>
            );
          })}
        </div>
      </Popover>
    </>
  );
}
