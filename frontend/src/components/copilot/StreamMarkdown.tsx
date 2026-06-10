import {
  useEffect,
  useMemo,
  useRef,
  useState,
  isValidElement,
  type ComponentType,
  type ReactNode,
  type TableHTMLAttributes,
  type ThHTMLAttributes,
} from "react";
import { createPortal } from "react-dom";
import {
  Check,
  ChevronDown,
  Copy,
  Download,
  Maximize2,
  X,
} from "lucide-react";
import {
  extractTableDataFromElement,
  tableDataToCSV,
  tableDataToMarkdown,
  tableDataToTSV,
  type ControlsConfig,
  type StreamdownTranslations,
  type TableData,
} from "streamdown";
import { useTranslation } from "react-i18next";
import { errMsg, voidCall, voidPromise } from "@/utils/async";
import { useAppStore } from "@/stores/app-store";
import { copyText } from "@/utils/clipboard";
import { saveBlobWithDialog } from "@/utils/desktop-download";
import { readableMarkdownTableFieldLabel } from "@/utils/field-labels";

// ---------------------------------------------------------------------------
// StreamMarkdown - lazy-loads the Streamdown component from the `streamdown`
// package and renders markdown content. Falls back to a plain whitespace-
// preserving <div> while the library is loading.
// ---------------------------------------------------------------------------

let streamdownPromise: Promise<ComponentType<Record<string, unknown>> | null> | null =
  null;

async function loadStreamdownComponent(): Promise<ComponentType<Record<string, unknown>> | null> {
  if (streamdownPromise) return streamdownPromise;

  streamdownPromise = import("streamdown")
    .then((mod) => {
      // The named export `Streamdown` is a MemoExoticComponent.
      const Comp = (mod as Record<string, unknown>).Streamdown ??
        (mod as Record<string, unknown>).default ??
        null;
      return Comp as ComponentType<Record<string, unknown>> | null;
    })
    .catch((error) => {
      console.warn("Failed to load Streamdown:", error);
      return null;
    });

  return streamdownPromise;
}

interface StreamMarkdownProps {
  content: string;
  mapTableFieldLabels?: boolean;
}

type TableExportFormat = "markdown" | "csv" | "tsv";

const STREAMDOWN_CONTROLS: ControlsConfig = {
  code: {
    copy: true,
    download: false,
  },
  table: false,
  mermaid: {
    copy: true,
    download: false,
    fullscreen: true,
    panZoom: true,
  },
};

const TABLE_FORMATS: Array<{
  format: TableExportFormat;
  label: string;
  extension: string;
  mimeType: string;
  filterName: string;
}> = [
  {
    format: "markdown",
    label: "Markdown",
    extension: "md",
    mimeType: "text/markdown;charset=utf-8",
    filterName: "Markdown",
  },
  {
    format: "csv",
    label: "CSV",
    extension: "csv",
    mimeType: "text/csv;charset=utf-8",
    filterName: "CSV",
  },
  {
    format: "tsv",
    label: "TSV",
    extension: "tsv",
    mimeType: "text/tab-separated-values;charset=utf-8",
    filterName: "TSV",
  },
];

function getTableFormat(format: TableExportFormat) {
  return TABLE_FORMATS.find((item) => item.format === format) ?? TABLE_FORMATS[0];
}

function serializeTableData(data: TableData, format: TableExportFormat): string {
  if (format === "csv") return tableDataToCSV(data);
  if (format === "tsv") return tableDataToTSV(data);
  return tableDataToMarkdown(data);
}

function tableBlob(data: TableData, format: TableExportFormat): Blob {
  const meta = getTableFormat(format);
  const text = serializeTableData(data, format);
  return new Blob([format === "csv" ? `\uFEFF${text}` : text], {
    type: meta.mimeType,
  });
}

function TableDropdown({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="markdown-table-dropdown" role="menu" aria-label={label}>
      {children}
    </div>
  );
}

function plainTextFromNode(node: ReactNode): string | null {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) {
    const parts = node.map(plainTextFromNode);
    return parts.every((part): part is string => part !== null) ? parts.join("") : null;
  }
  if (isValidElement<{ children?: ReactNode }>(node)) {
    return plainTextFromNode(node.props.children);
  }
  return null;
}

function MarkdownTableHeader({
  children,
  mapFieldLabels,
  node: _node,
  ...props
}: ThHTMLAttributes<HTMLTableCellElement> & { mapFieldLabels?: boolean; node?: unknown }) {
  const plainText = plainTextFromNode(children);
  return (
    <th {...props}>
      {plainText === null || !mapFieldLabels ? children : readableMarkdownTableFieldLabel(plainText)}
    </th>
  );
}

function MarkdownTable({
  children,
  className,
  node: _node,
  style,
  ...props
}: TableHTMLAttributes<HTMLTableElement> & { node?: unknown }) {
  const { t } = useTranslation(["dashboard", "common"]);
  const pushToast = useAppStore((s) => s.pushToast);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const [tableData, setTableData] = useState<TableData | null>(null);
  const [copyMenuOpen, setCopyMenuOpen] = useState(false);
  const [downloadMenuOpen, setDownloadMenuOpen] = useState(false);
  const [fullscreenOpen, setFullscreenOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const table = wrapperRef.current?.querySelector("table");
    setTableData(table ? extractTableDataFromElement(table) : null);
  }, [children]);

  useEffect(() => {
    if (!copyMenuOpen && !downloadMenuOpen) return;

    const closeMenus = (event: MouseEvent) => {
      const target = event.target;
      if (target instanceof Node && wrapperRef.current?.contains(target)) return;
      setCopyMenuOpen(false);
      setDownloadMenuOpen(false);
    };

    document.addEventListener("mousedown", closeMenus);
    return () => document.removeEventListener("mousedown", closeMenus);
  }, [copyMenuOpen, downloadMenuOpen]);

  useEffect(() => {
    if (!fullscreenOpen) return;

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFullscreenOpen(false);
    };

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", handleEscape);

    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleEscape);
    };
  }, [fullscreenOpen]);

  const getRenderedTableData = () => {
    if (!tableData) throw new Error("Table not found");
    return tableData;
  };

  const handleCopy = async (format: TableExportFormat) => {
    try {
      await copyText(serializeTableData(getRenderedTableData(), format));
      setCopyMenuOpen(false);
      setCopied(true);
      pushToast(t("common:copied"), "success");
      window.setTimeout(() => setCopied(false), 1600);
    } catch (error) {
      pushToast(t("dashboard:copy_failed", { message: errMsg(error) }), "error");
    }
  };

  const handleDownload = async (format: TableExportFormat) => {
    try {
      const meta = getTableFormat(format);
      const savedPath = await saveBlobWithDialog(tableBlob(getRenderedTableData(), format), {
        title: t("dashboard:table_save_title"),
        defaultFileName: `table.${meta.extension}`,
        filters: [{ name: meta.filterName, extensions: [meta.extension] }],
      });
      setDownloadMenuOpen(false);
      if (!savedPath) return;
      pushToast(t("dashboard:table_saved", { path: savedPath }), "success");
    } catch (error) {
      pushToast(t("dashboard:save_failed", { message: errMsg(error) }), "error");
    }
  };

  const tableElement = (
    <table
      className={className}
      style={{
        display: "table",
        width: "max-content",
        minWidth: "100%",
        tableLayout: "auto",
        ...style,
      }}
      {...props}
      data-streamdown="table"
    >
      {children}
    </table>
  );

  return (
    <div ref={wrapperRef} className="markdown-table-card" data-streamdown="table-wrapper">
      <div className="markdown-table-toolbar">
        <div className="markdown-table-action-group">
          <div className="markdown-table-menu">
            <button
              type="button"
              className="markdown-table-tool"
              aria-label={t("common:copy")}
              title={t("common:copy")}
              onClick={() => {
                setCopyMenuOpen((open) => !open);
                setDownloadMenuOpen(false);
              }}
            >
              {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
              <ChevronDown className="h-3 w-3 opacity-70" />
            </button>
            {copyMenuOpen && (
              <TableDropdown label={t("common:copy")}>
                {TABLE_FORMATS.map((item) => (
                  <button
                    key={item.format}
                    type="button"
                    role="menuitem"
                    onClick={voidPromise(() => handleCopy(item.format))}
                  >
                    {item.label}
                  </button>
                ))}
              </TableDropdown>
            )}
          </div>

          <div className="markdown-table-menu">
            <button
              type="button"
              className="markdown-table-tool"
              aria-label={t("common:download")}
              title={t("common:download")}
              onClick={() => {
                setDownloadMenuOpen((open) => !open);
                setCopyMenuOpen(false);
              }}
            >
              <Download className="h-3.5 w-3.5" />
              <ChevronDown className="h-3 w-3 opacity-70" />
            </button>
            {downloadMenuOpen && (
              <TableDropdown label={t("common:download")}>
                {TABLE_FORMATS.map((item) => (
                  <button
                    key={item.format}
                    type="button"
                    role="menuitem"
                    onClick={voidPromise(() => handleDownload(item.format))}
                  >
                    {item.label}
                  </button>
                ))}
              </TableDropdown>
            )}
          </div>

          <button
            type="button"
            className="markdown-table-tool"
            aria-label={t("common:titlebar.maximize")}
            title={t("common:titlebar.maximize")}
            onClick={() => setFullscreenOpen(true)}
          >
            <Maximize2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div className="markdown-table-scroll">
        {tableElement}
      </div>

      {fullscreenOpen
        ? createPortal(
            <div
              className="markdown-table-fullscreen"
              data-streamdown="table-fullscreen"
              role="dialog"
              aria-modal="true"
              aria-label={t("common:titlebar.maximize")}
            >
              <div className="markdown-table-fullscreen-toolbar">
                <button
                  type="button"
                  className="markdown-table-tool"
                  aria-label={t("common:close")}
                  title={t("common:close")}
                  onClick={() => setFullscreenOpen(false)}
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="markdown-table-fullscreen-body">
                <div className="markdown-table-scroll markdown-table-scroll-fullscreen">
                  {tableElement}
                </div>
              </div>
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}

export function StreamMarkdown({ content, mapTableFieldLabels = false }: StreamMarkdownProps) {
  const [StreamdownComponent, setStreamdownComponent] =
    useState<ComponentType<Record<string, unknown>> | null>(null);
  const { t } = useTranslation(["common"]);

  const streamdownTranslations = useMemo<Partial<StreamdownTranslations>>(() => ({
    close: t("common:close"),
    copied: t("common:copied"),
    copyCode: t("common:copy"),
    copyTable: t("common:copy"),
    downloadFile: t("common:download"),
    downloadTable: t("common:download"),
    exitFullscreen: t("common:titlebar.restore"),
    viewFullscreen: t("common:titlebar.maximize"),
  }), [t]);

  const components = useMemo(
    () => ({
      table: MarkdownTable,
      th: (props: ThHTMLAttributes<HTMLTableCellElement> & { node?: unknown }) => (
        <MarkdownTableHeader {...props} mapFieldLabels={mapTableFieldLabels} />
      ),
    }),
    [mapTableFieldLabels],
  );

  useEffect(() => {
    let mounted = true;

    voidCall(loadStreamdownComponent().then((component) => {
      if (!mounted || !component) return;
      setStreamdownComponent(() => component);
    }));

    return () => {
      mounted = false;
    };
  }, []);

  if (!StreamdownComponent) {
    return <div className="whitespace-pre-wrap break-words">{content || ""}</div>;
  }

  return (
    <StreamdownComponent
      className="markdown-body text-sm leading-6"
      components={components}
      controls={STREAMDOWN_CONTROLS}
      parseIncompleteMarkdown={true}
      translations={streamdownTranslations}
    >
      {String(content || "")}
    </StreamdownComponent>
  );
}
