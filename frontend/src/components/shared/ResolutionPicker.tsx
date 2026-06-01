import { useEffect, useId, useMemo, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { Popover } from "@/components/ui/Popover";
import { SelectMenu } from "@/components/ui/SelectMenu";
import {
  DROPDOWN_PANEL_CLS,
  ICON_BTN_CLS,
  INPUT_CLS,
  SELECT_MENU_PANEL_STYLE,
} from "@/components/ui/darkroom-tokens";

export interface ResolutionPickerProps {
  mode: "select" | "combobox";
  options: string[];
  value: string | null;
  onChange: (v: string | null) => void;
  placeholder?: string;
  disabled?: boolean;
  "aria-label"?: string;
}

export function ResolutionPicker({
  mode,
  options,
  value,
  onChange,
  placeholder = "默认（不传）",
  disabled,
  "aria-label": ariaLabel,
}: ResolutionPickerProps) {
  if (options.length === 0) return null;

  if (mode === "select") {
    const menuOptions = [
      { value: "", label: placeholder },
      ...options.map((o) => ({ value: o, label: o })),
    ];
    return (
      <SelectMenu
        value={value ?? ""}
        options={menuOptions}
        onChange={(next) => onChange(next === "" ? null : next)}
        ariaLabel={ariaLabel}
        placeholder={placeholder}
        panelLabel={ariaLabel}
        disabled={disabled}
        minPanelWidth={180}
      />
    );
  }

  return <ComboboxInput {...{ ariaLabel, options, value, onChange, placeholder, disabled }} />;
}

interface ComboboxInputProps {
  ariaLabel?: string;
  options: string[];
  value: string | null;
  onChange: (v: string | null) => void;
  placeholder: string;
  disabled?: boolean;
}

function ComboboxInput({ ariaLabel, options, value, onChange, placeholder, disabled }: ComboboxInputProps) {
  // 本地编辑态允许用户自由输入（含空格/清空）——外部 value 变化时通过 render-phase
  // 判断同步（React 官方推荐的"派生 state from props"模式，非 effect）。
  const anchorRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const skipNextFocusOpenRef = useRef(false);
  const listboxId = useId();
  const [local, setLocal] = useState<string>(value ?? "");
  const [lastSync, setLastSync] = useState<string | null>(value);
  const [open, setOpen] = useState(false);
  const [showAllOptions, setShowAllOptions] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [panelWidth, setPanelWidth] = useState<number | null>(null);
  if (value !== lastSync) {
    setLastSync(value);
    setLocal(value ?? "");
  }

  const filteredOptions = useMemo(() => {
    if (showAllOptions) return options;
    const q = local.trim().toLowerCase();
    if (!q) return options;
    return options.filter((o) => o.toLowerCase().includes(q));
  }, [local, options, showAllOptions]);

  const choices = useMemo(
    () => [
      { value: "", label: placeholder },
      ...filteredOptions.map((option) => ({ value: option, label: option })),
    ],
    [filteredOptions, placeholder],
  );

  useEffect(() => {
    if (!open) return;
    const rect = anchorRef.current?.getBoundingClientRect();
    if (rect) setPanelWidth(Math.max(rect.width, 180));
    // 输入过滤或展开时把键盘候选重置到第一项。
    setActiveIndex(0);
  }, [open, choices.length]);

  const selectChoice = (next: string) => {
    setLocal(next);
    onChange(next === "" ? null : next);
    setOpen(false);
    setShowAllOptions(false);
    focusInput(false);
  };

  const focusInput = (shouldOpenOnFocus: boolean) => {
    skipNextFocusOpenRef.current = !shouldOpenOnFocus;
    requestAnimationFrame(() => {
      inputRef.current?.focus();
      if (!shouldOpenOnFocus) {
        requestAnimationFrame(() => {
          skipNextFocusOpenRef.current = false;
        });
      }
    });
  };

  const onInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (disabled) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) {
        setShowAllOptions(true);
        setOpen(true);
        return;
      }
      setActiveIndex((i) => (i + 1) % choices.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) {
        setShowAllOptions(true);
        setOpen(true);
        return;
      }
      setActiveIndex((i) => (i - 1 + choices.length) % choices.length);
    } else if (e.key === "Enter" && open) {
      e.preventDefault();
      const choice = choices[activeIndex];
      if (choice) selectChoice(choice.value);
    } else if (e.key === "Escape") {
      setOpen(false);
      setShowAllOptions(false);
    }
  };

  return (
    <div ref={anchorRef} className="relative">
      <input
        ref={inputRef}
        type="text"
        role="combobox"
        aria-label={ariaLabel}
        aria-expanded={open}
        aria-controls={listboxId}
        aria-autocomplete="list"
        className={`${INPUT_CLS} pr-8`}
        value={local}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(e) => {
          const raw = e.target.value;
          setLocal(raw);
          setShowAllOptions(false);
          onChange(raw === "" ? null : raw);
          setOpen(true);
        }}
        onFocus={() => {
          if (skipNextFocusOpenRef.current) {
            skipNextFocusOpenRef.current = false;
            return;
          }
          setOpen(true);
        }}
        onKeyDown={onInputKeyDown}
        onBlur={() => {
          // 输入后可能带首尾空格，离焦时 normalize 避免脏值流入后端查找表
          const trimmed = local.trim();
          if (trimmed !== local) {
            setLocal(trimmed);
            onChange(trimmed === "" ? null : trimmed);
          }
        }}
      />
      <button
        type="button"
        className={`absolute right-2 top-1/2 -translate-y-1/2 ${ICON_BTN_CLS}`}
        aria-label={ariaLabel}
        disabled={disabled}
        tabIndex={-1}
        onClick={() => {
          const nextOpen = !open;
          setShowAllOptions(nextOpen);
          setOpen(nextOpen);
          focusInput(nextOpen);
        }}
      >
        <ChevronDown
          className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden="true"
        />
      </button>
      <Popover
        open={open}
        onClose={() => {
          setOpen(false);
          setShowAllOptions(false);
        }}
        anchorRef={anchorRef}
        align="start"
        layer="modal"
        sideOffset={5}
        width=""
        className={DROPDOWN_PANEL_CLS}
        style={{
          ...SELECT_MENU_PANEL_STYLE,
          width: panelWidth ?? undefined,
          minWidth: 180,
        }}
      >
        <div
          id={listboxId}
          className="max-h-56 overflow-y-auto outline-none"
          role="listbox"
          aria-label={ariaLabel}
        >
          {choices.map((choice, index) => {
            const selected = choice.value === (value ?? "");
            const active = index === activeIndex;
            return (
              <button
                key={choice.value || "__default__"}
                type="button"
                role="option"
                aria-selected={selected}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => selectChoice(choice.value)}
                className="focus-ring flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-[oklch(1_0_0_/_0.08)]"
                style={{
                  background:
                    selected || active
                      ? "linear-gradient(135deg, var(--color-accent-dim), oklch(0.22 0.014 265 / 0.7))"
                      : "transparent",
                }}
              >
                <span
                  className="min-w-0 flex-1 truncate text-[12.5px] font-semibold"
                  style={{
                    color: selected ? "var(--color-accent-2)" : "var(--color-text-2)",
                  }}
                >
                  {choice.label}
                </span>
              </button>
            );
          })}
        </div>
      </Popover>
    </div>
  );
}
