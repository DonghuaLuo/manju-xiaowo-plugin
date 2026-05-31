import { useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, ChevronDown, Plus, X } from "lucide-react";
import { Popover } from "@/components/ui/Popover";
import type { Dialogue } from "@/types";

interface DialogueListEditorProps {
  dialogue: Dialogue[];
  speakerOptions: string[];
  onChange: (dialogue: Dialogue[]) => void;
}

/** Editable list of speaker/line dialogue pairs. */
export function DialogueListEditor({
  dialogue,
  speakerOptions,
  onChange,
}: DialogueListEditorProps) {
  const { t } = useTranslation("dashboard");

  const update = (index: number, patch: Partial<Dialogue>) => {
    const next = dialogue.map((d, i) =>
      i === index ? { ...d, ...patch } : d
    );
    onChange(next);
  };

  const remove = (index: number) => {
    onChange(dialogue.filter((_, i) => i !== index));
  };

  const add = () => {
    const speaker = speakerOptions[0];
    if (!speaker) return;
    onChange([...dialogue, { speaker, line: "" }]);
  };

  return (
    <div className="flex flex-col gap-1.5">
      {dialogue.map((d, i) => (
        <div key={i} className="flex items-start gap-1.5">
          <SpeakerSelect
            value={speakerOptions.includes(d.speaker) ? d.speaker : ""}
            options={speakerOptions}
            placeholder={t("speaker_placeholder")}
            onChange={(speaker) => update(i, { speaker })}
          />
          <input
            type="text"
            value={d.line}
            onChange={(e) => update(i, { line: e.target.value })}
            placeholder={t("line_placeholder")}
            className="dlg-input min-w-0 flex-1"
          />
          <button
            type="button"
            onClick={() => remove(i)}
            aria-label={t("dialogue_remove")}
            title={t("dialogue_remove")}
            className="focus-ring grid h-7 w-7 shrink-0 place-items-center rounded-md transition-colors hover:bg-[oklch(1_0_0_/_0.05)]"
            style={{ color: "var(--color-text-4)" }}
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}

      <button
        type="button"
        onClick={add}
        disabled={speakerOptions.length === 0}
        className="focus-ring inline-flex items-center gap-1 self-start rounded-md px-2 py-1 text-[11.5px] transition-colors hover:bg-[oklch(1_0_0_/_0.05)]"
        style={{ color: "var(--color-text-3)" }}
      >
        <Plus className="h-3 w-3" />
        {t("add_dialogue")}
      </button>
    </div>
  );
}

function SpeakerSelect({
  value,
  options,
  placeholder,
  onChange,
}: {
  value: string;
  options: string[];
  placeholder: string;
  onChange: (speaker: string) => void;
}) {
  const { t } = useTranslation("dashboard");
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const listboxId = useId();
  const selectedLabel = value || placeholder;

  const selectSpeaker = (speaker: string) => {
    onChange(speaker);
    setOpen(false);
  };

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        role="combobox"
        aria-label={placeholder}
        aria-controls={listboxId}
        aria-expanded={open ? "true" : "false"}
        aria-haspopup="listbox"
        onClick={() => setOpen((prev) => !prev)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            setOpen(false);
            return;
          }
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setOpen(true);
          }
        }}
        className="dlg-input dlg-input--speaker focus-ring flex h-[30px] w-24 shrink-0 items-center justify-between gap-1 px-2 py-0"
      >
        <span
          className="min-w-0 flex-1 truncate text-left text-[12.5px] font-semibold leading-none"
          style={{
            color: value ? "var(--color-accent-2)" : "var(--color-text-4)",
          }}
        >
          {selectedLabel}
        </span>
        <ChevronDown
          className={`h-3 w-3 shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden="true"
          style={{ color: "var(--color-text-4)" }}
        />
      </button>

      <Popover
        open={open}
        onClose={() => setOpen(false)}
        anchorRef={buttonRef}
        align="start"
        sideOffset={5}
        width="w-44"
        className="overflow-hidden rounded-lg border border-white/10 p-1 shadow-2xl shadow-black/35"
        style={{
          background:
            "linear-gradient(180deg, oklch(0.205 0.012 265 / 0.98), oklch(0.165 0.010 265 / 0.98))",
        }}
      >
        <div className="px-2 py-1.5">
          <div
            className="text-[9.5px] font-bold uppercase"
            style={{
              color: "var(--color-text-4)",
              letterSpacing: "0.8px",
            }}
          >
            {t("speaker_placeholder")}
          </div>
        </div>
        <div
          id={listboxId}
          role="listbox"
          aria-label={placeholder}
          className="max-h-56 overflow-y-auto"
        >
          {options.map((name) => {
            const selected = name === value;
            return (
              <button
                key={name}
                type="button"
                role="option"
                aria-selected={selected}
                onClick={() => selectSpeaker(name)}
                className="focus-ring flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-[oklch(1_0_0_/_0.08)]"
                style={{
                  background: selected
                    ? "linear-gradient(135deg, var(--color-accent-dim), oklch(0.22 0.014 265 / 0.7))"
                    : "transparent",
                  color: selected ? "var(--color-accent-2)" : "var(--color-text)",
                }}
              >
                <span
                  className="min-w-0 flex-1 truncate text-[12.5px] font-semibold"
                  style={{ color: selected ? "var(--color-accent-2)" : "var(--color-text-2)" }}
                >
                  {name}
                </span>
                <Check
                  className={`h-3.5 w-3.5 shrink-0 ${selected ? "opacity-100" : "opacity-0"}`}
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
