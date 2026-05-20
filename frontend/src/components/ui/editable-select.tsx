import * as React from "react"
import { ChevronDownIcon, CheckIcon } from "lucide-react"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { cn } from "@/lib/utils"

interface EditableSelectProps {
  value: string
  onValueChange: (value: string) => void
  options: string[]
  disabled?: boolean
  className?: string
  placeholder?: string
  /** 单位后缀，如 "k"。输入框只显示数字，对外输出时自动拼接后缀 */
  suffix?: string
}

/** 去除字符串末尾的后缀 */
function stripSuffix(val: string, suffix: string): string {
  if (suffix && val.endsWith(suffix)) {
    return val.slice(0, -suffix.length)
  }
  return val
}

/** 确保字符串末尾有后缀（值非空时） */
function ensureSuffix(val: string, suffix: string): string {
  if (!val) return val
  if (suffix && !val.endsWith(suffix)) {
    return val + suffix
  }
  return val
}

function EditableSelect({
  value,
  onValueChange,
  options,
  disabled = false,
  className,
  placeholder,
  suffix,
}: EditableSelectProps) {
  const [open, setOpen] = React.useState(false)

  // 输入框内部只显示不带后缀的数字部分
  const displayValue = suffix ? stripSuffix(value, suffix) : value
  const [inputValue, setInputValue] = React.useState(displayValue)

  React.useEffect(() => {
    setInputValue(suffix ? stripSuffix(value, suffix) : value)
  }, [value, suffix])

  // 选项的显示值（去掉后缀）
  const displayOptions = React.useMemo(() => {
    if (!suffix) return options.map((o) => ({ raw: o, display: o }))
    return options.map((o) => ({ raw: o, display: stripSuffix(o, suffix) }))
  }, [options, suffix])

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const raw = e.target.value
    // 只允许输入数字
    if (suffix && raw !== "" && !/^\d+$/.test(raw)) return
    setInputValue(raw)
    // 对外输出时拼接后缀
    onValueChange(suffix ? ensureSuffix(raw, suffix) : raw)
  }

  const handleSelect = (rawOption: string) => {
    const display = suffix ? stripSuffix(rawOption, suffix) : rawOption
    setInputValue(display)
    onValueChange(rawOption)
    setOpen(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      setOpen(false)
    }
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild disabled={disabled}>
        <div
          className={cn(
            "border-input dark:bg-input/30 flex h-9 w-full items-center rounded-md border bg-transparent shadow-xs",
            "focus-within:border-ring focus-within:ring-ring/50 focus-within:ring-[3px]",
            disabled && "cursor-not-allowed opacity-50",
            className
          )}
        >
          <div className="flex flex-1 items-center overflow-hidden px-3 py-1">
            <input
              type="text"
              value={inputValue}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              onFocus={() => !disabled && setOpen(true)}
              disabled={disabled}
              placeholder={placeholder}
              style={{ width: `${Math.max(inputValue.length, 1)}ch` }}
              className="h-full min-w-0 bg-transparent text-sm outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed"
            />
            {suffix && inputValue && (
              <span className="text-sm text-muted-foreground">{suffix}</span>
            )}
          </div>
          <ChevronDownIcon className="mr-2 size-4 shrink-0 opacity-50" />
        </div>
      </PopoverTrigger>
      <PopoverContent
        className="w-[var(--radix-popover-trigger-width)] p-1"
        align="start"
        sideOffset={4}
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        <div className="max-h-[200px] overflow-y-auto">
          {displayOptions.map(({ raw, display }) => (
            <div
              key={raw}
              className={cn(
                "relative flex cursor-pointer items-center rounded-sm px-2 py-1.5 text-sm select-none hover:bg-accent hover:text-accent-foreground",
                value === raw && "bg-accent/50"
              )}
              onClick={() => handleSelect(raw)}
            >
              <span className="flex-1">{display}{suffix ? suffix : ""}</span>
              {value === raw && (
                <CheckIcon className="ml-2 size-4 shrink-0" />
              )}
            </div>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  )
}

export { EditableSelect }
