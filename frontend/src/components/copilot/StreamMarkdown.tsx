import { Fragment, type ReactNode } from "react";

interface StreamMarkdownProps {
  content: string;
}

function inlineMarkdown(text: string, keyPrefix: string): ReactNode[] {
  const result: ReactNode[] = [];
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*)/g;
  let lastIndex = 0;
  let matchIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      result.push(text.slice(lastIndex, match.index));
    }

    const token = match[0];
    const key = `${keyPrefix}-inline-${matchIndex}`;
    if (token.startsWith("`")) {
      result.push(
        <code key={key} className="rounded bg-bg-grad-a/70 px-1 py-0.5 font-mono text-[0.92em]">
          {token.slice(1, -1)}
        </code>,
      );
    } else {
      result.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    }

    matchIndex += 1;
    lastIndex = pattern.lastIndex;
  }

  if (lastIndex < text.length) {
    result.push(text.slice(lastIndex));
  }

  return result.length > 0 ? result : [text];
}

function renderParagraph(lines: string[], key: string): ReactNode {
  return (
    <p key={key} className="whitespace-pre-wrap break-words">
      {inlineMarkdown(lines.join(" "), key)}
    </p>
  );
}

function renderList(items: string[], key: string): ReactNode {
  return (
    <ul key={key} className="list-disc space-y-1 pl-5">
      {items.map((item, index) => (
        <li key={`${key}-item-${index}`}>{inlineMarkdown(item, `${key}-${index}`)}</li>
      ))}
    </ul>
  );
}

function renderMarkdown(content: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const paragraph: string[] = [];
  const listItems: string[] = [];
  const codeLines: string[] = [];
  let inCodeBlock = false;

  const flushParagraph = () => {
    if (paragraph.length === 0) return;
    nodes.push(renderParagraph([...paragraph], `p-${nodes.length}`));
    paragraph.length = 0;
  };

  const flushList = () => {
    if (listItems.length === 0) return;
    nodes.push(renderList([...listItems], `ul-${nodes.length}`));
    listItems.length = 0;
  };

  const lines = String(content || "").replace(/\r\n/g, "\n").split("\n");

  lines.forEach((rawLine) => {
    const line = rawLine.trimEnd();
    const trimmed = line.trim();

    if (trimmed.startsWith("```")) {
      if (inCodeBlock) {
        nodes.push(
          <pre key={`code-${nodes.length}`} className="overflow-x-auto rounded-lg bg-bg-grad-a/75 p-3 text-xs">
            <code>{codeLines.join("\n")}</code>
          </pre>,
        );
        codeLines.length = 0;
        inCodeBlock = false;
      } else {
        flushParagraph();
        flushList();
        inCodeBlock = true;
      }
      return;
    }

    if (inCodeBlock) {
      codeLines.push(rawLine);
      return;
    }

    if (!trimmed) {
      flushParagraph();
      flushList();
      return;
    }

    const heading = /^(#{1,4})\s+(.+)$/.exec(trimmed);
    if (heading) {
      flushParagraph();
      flushList();
      const level = heading[1].length;
      const text = heading[2];
      const className = level <= 2 ? "mt-3 text-base font-semibold" : "mt-2 text-sm font-semibold";
      nodes.push(
        <div key={`h-${nodes.length}`} className={className}>
          {inlineMarkdown(text, `h-${nodes.length}`)}
        </div>,
      );
      return;
    }

    const listItem = /^[-*]\s+(.+)$/.exec(trimmed);
    if (listItem) {
      flushParagraph();
      listItems.push(listItem[1]);
      return;
    }

    flushList();
    paragraph.push(trimmed);
  });

  if (inCodeBlock) {
    nodes.push(
      <pre key={`code-${nodes.length}`} className="overflow-x-auto rounded-lg bg-bg-grad-a/75 p-3 text-xs">
        <code>{codeLines.join("\n")}</code>
      </pre>,
    );
  }

  flushParagraph();
  flushList();

  return nodes;
}

export function StreamMarkdown({ content }: StreamMarkdownProps) {
  const nodes = renderMarkdown(content);

  if (nodes.length === 0) {
    return <div className="whitespace-pre-wrap break-words" />;
  }

  return (
    <div className="markdown-body space-y-2 text-sm leading-6">
      {nodes.map((node, index) => (
        <Fragment key={index}>{node}</Fragment>
      ))}
    </div>
  );
}
