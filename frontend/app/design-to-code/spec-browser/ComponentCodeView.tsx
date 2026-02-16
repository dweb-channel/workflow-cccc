"use client";

import { useState } from "react";
import type { CodeGenResult } from "@/lib/types/design-spec";
import { Copy, Check, Package, AlertCircle } from "lucide-react";

// ================================================================
// ComponentCodeView — Displays generated code for a single component
//
// States:
// - No code data: "not yet generated" placeholder
// - Error: error message display
// - Success: syntax-highlighted code with line numbers + metadata
// ================================================================

interface ComponentCodeViewProps {
  componentName: string;
  codeResult: CodeGenResult | null;
}

export function ComponentCodeView({
  componentName,
  codeResult,
}: ComponentCodeViewProps) {
  if (!codeResult) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-slate-500">
        <div className="rounded-full bg-slate-700/30 p-3">
          <Package className="h-5 w-5" />
        </div>
        <div className="text-center">
          <p className="text-xs font-medium text-slate-400">
            Code not yet generated
          </p>
          <p className="mt-1 text-[11px] text-slate-600">
            Run the codegen pipeline to generate code for{" "}
            <span className="font-mono text-slate-400">{componentName}</span>
          </p>
        </div>
      </div>
    );
  }

  if (codeResult.error) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-6">
        <div className="rounded-full bg-red-500/10 p-3">
          <AlertCircle className="h-5 w-5 text-red-400" />
        </div>
        <div className="text-center">
          <p className="text-xs font-medium text-red-400">
            Code generation failed
          </p>
          <p className="mt-1 text-[11px] text-slate-500">
            {codeResult.error}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* File header */}
      <CodeFileHeader codeResult={codeResult} />

      {/* Code body with line numbers */}
      <div className="flex-1 overflow-auto bg-[#0d1117]">
        <CodeBlock code={codeResult.code} />
      </div>

      {/* Footer: dependencies + tailwind classes */}
      {(codeResult.dependencies?.length || codeResult.tailwind_classes_used?.length) && (
        <CodeFooter codeResult={codeResult} />
      )}
    </div>
  );
}

// ================================================================
// CodeFileHeader — File name, line count, copy button
// ================================================================

function CodeFileHeader({ codeResult }: { codeResult: CodeGenResult }) {
  const [copied, setCopied] = useState(false);
  const lineCount = codeResult.code.split("\n").length;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(codeResult.code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard not available in non-HTTPS contexts
    }
  };

  return (
    <div className="flex items-center justify-between border-b border-slate-700 bg-slate-900 px-4 py-2 shrink-0">
      <div className="flex items-center gap-2">
        <span className="text-xs font-mono text-slate-300">
          {codeResult.file_name}
        </span>
        <span className="text-[10px] text-slate-600">
          {lineCount} lines
        </span>
      </div>
      <button
        onClick={handleCopy}
        className="flex items-center gap-1 rounded-md border border-slate-600 bg-slate-800 px-2 py-1 text-[10px] text-slate-400 hover:text-white hover:border-slate-500 transition-colors"
      >
        {copied ? (
          <>
            <Check className="h-3 w-3 text-green-400" /> Copied
          </>
        ) : (
          <>
            <Copy className="h-3 w-3" /> Copy
          </>
        )}
      </button>
    </div>
  );
}

// ================================================================
// CodeBlock — Code with line numbers and basic syntax highlighting
// ================================================================

function CodeBlock({ code }: { code: string }) {
  const lines = code.split("\n");

  return (
    <pre className="p-0 m-0 text-[13px] leading-[1.6] font-mono">
      <table className="border-collapse w-full">
        <tbody>
          {lines.map((line, i) => (
            <tr key={i} className="hover:bg-slate-800/50">
              <td className="select-none text-right pr-4 pl-4 text-slate-600 text-[12px] w-[1%] whitespace-nowrap align-top">
                {i + 1}
              </td>
              <td className="pr-4 whitespace-pre">
                <HighlightedLine line={line} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </pre>
  );
}

// ================================================================
// HighlightedLine — Basic JSX/TSX syntax highlighting via regex
// No external dependency — handles keywords, strings, comments,
// JSX tags, and numbers for readable code display.
// ================================================================

const KEYWORDS = new Set([
  "import", "export", "from", "default", "function", "return",
  "const", "let", "var", "if", "else", "for", "while",
  "class", "extends", "new", "this", "typeof", "instanceof",
  "interface", "type", "enum", "as", "async", "await",
  "try", "catch", "finally", "throw", "switch", "case",
  "break", "continue", "null", "undefined", "true", "false",
]);

const JSX_KEYWORDS = new Set([
  "className", "onClick", "onChange", "onSubmit", "href", "src",
  "alt", "style", "key", "ref", "children", "disabled", "placeholder",
]);

// Token types for highlighting
type TokenType = "keyword" | "string" | "comment" | "tag" | "number" | "attr" | "text";

interface Token {
  type: TokenType;
  value: string;
}

function tokenizeLine(line: string): Token[] {
  const tokens: Token[] = [];
  let i = 0;

  while (i < line.length) {
    // Single-line comment
    if (line[i] === "/" && line[i + 1] === "/") {
      tokens.push({ type: "comment", value: line.slice(i) });
      break;
    }

    // Block comment start (simplified — doesn't handle multiline)
    if (line[i] === "/" && line[i + 1] === "*") {
      const end = line.indexOf("*/", i + 2);
      const commentEnd = end !== -1 ? end + 2 : line.length;
      tokens.push({ type: "comment", value: line.slice(i, commentEnd) });
      i = commentEnd;
      continue;
    }

    // Strings (double quote)
    if (line[i] === '"') {
      let j = i + 1;
      while (j < line.length && line[j] !== '"') {
        if (line[j] === "\\") j++;
        j++;
      }
      tokens.push({ type: "string", value: line.slice(i, j + 1) });
      i = j + 1;
      continue;
    }

    // Strings (single quote)
    if (line[i] === "'") {
      let j = i + 1;
      while (j < line.length && line[j] !== "'") {
        if (line[j] === "\\") j++;
        j++;
      }
      tokens.push({ type: "string", value: line.slice(i, j + 1) });
      i = j + 1;
      continue;
    }

    // Template literal
    if (line[i] === "`") {
      let j = i + 1;
      while (j < line.length && line[j] !== "`") {
        if (line[j] === "\\") j++;
        j++;
      }
      tokens.push({ type: "string", value: line.slice(i, j + 1) });
      i = j + 1;
      continue;
    }

    // JSX tags: <ComponentName or </div>
    if (line[i] === "<" && (line[i + 1] === "/" || /[A-Za-z]/.test(line[i + 1] || ""))) {
      let j = i + 1;
      if (line[j] === "/") j++;
      while (j < line.length && /[A-Za-z0-9._-]/.test(line[j])) j++;
      tokens.push({ type: "tag", value: line.slice(i, j) });
      i = j;
      continue;
    }

    // Numbers
    if (/[0-9]/.test(line[i]) && (i === 0 || !/[A-Za-z_]/.test(line[i - 1]))) {
      let j = i;
      while (j < line.length && /[0-9.xXa-fA-F]/.test(line[j])) j++;
      tokens.push({ type: "number", value: line.slice(i, j) });
      i = j;
      continue;
    }

    // Words (keywords, identifiers, JSX attributes)
    if (/[A-Za-z_$]/.test(line[i])) {
      let j = i;
      while (j < line.length && /[A-Za-z0-9_$]/.test(line[j])) j++;
      const word = line.slice(i, j);
      if (KEYWORDS.has(word)) {
        tokens.push({ type: "keyword", value: word });
      } else if (JSX_KEYWORDS.has(word)) {
        tokens.push({ type: "attr", value: word });
      } else {
        tokens.push({ type: "text", value: word });
      }
      i = j;
      continue;
    }

    // Other characters (operators, punctuation, whitespace)
    tokens.push({ type: "text", value: line[i] });
    i++;
  }

  return tokens;
}

const TOKEN_COLORS: Record<TokenType, string> = {
  keyword: "text-purple-400",
  string: "text-green-400",
  comment: "text-slate-500 italic",
  tag: "text-red-400",
  number: "text-amber-400",
  attr: "text-cyan-400",
  text: "text-slate-300",
};

function HighlightedLine({ line }: { line: string }) {
  if (!line) return <span>{"\n"}</span>;

  const tokens = tokenizeLine(line);
  return (
    <span>
      {tokens.map((token, i) => (
        <span key={i} className={TOKEN_COLORS[token.type]}>
          {token.value}
        </span>
      ))}
    </span>
  );
}

// ================================================================
// CodeFooter — Dependencies and Tailwind classes summary
// ================================================================

function CodeFooter({ codeResult }: { codeResult: CodeGenResult }) {
  return (
    <div className="border-t border-slate-700 bg-slate-900 px-4 py-2 shrink-0 space-y-1.5">
      {codeResult.dependencies && codeResult.dependencies.length > 0 && (
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-[10px] text-slate-500">deps:</span>
          {codeResult.dependencies.map((dep) => (
            <span
              key={dep}
              className="rounded bg-violet-500/10 px-1.5 py-0.5 text-[10px] text-violet-400 font-mono"
            >
              {dep}
            </span>
          ))}
        </div>
      )}
      {codeResult.tailwind_classes_used && codeResult.tailwind_classes_used.length > 0 && (
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-[10px] text-slate-500">tw:</span>
          {codeResult.tailwind_classes_used.slice(0, 15).map((cls) => (
            <span
              key={cls}
              className="rounded bg-cyan-500/10 px-1.5 py-0.5 text-[10px] text-cyan-400 font-mono"
            >
              {cls}
            </span>
          ))}
          {codeResult.tailwind_classes_used.length > 15 && (
            <span className="text-[10px] text-slate-600">
              +{codeResult.tailwind_classes_used.length - 15} more
            </span>
          )}
        </div>
      )}
    </div>
  );
}
