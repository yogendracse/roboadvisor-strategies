"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface Props {
  children: string;
  className?: string;
}

export function Markdown({ children, className = "" }: Props) {
  return (
    <div className={`prose-sm ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => (
            <p className="mb-2 text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">
              {children}
            </p>
          ),
          strong: ({ children }) => (
            <strong className="font-semibold text-zinc-900 dark:text-zinc-100">
              {children}
            </strong>
          ),
          em: ({ children }) => (
            <em className="italic text-zinc-700 dark:text-zinc-300">
              {children}
            </em>
          ),
          code: ({ children }) => (
            <code className="rounded bg-zinc-100 px-1 py-0.5 font-mono text-[0.85em] text-zinc-800 dark:bg-zinc-800 dark:text-zinc-200">
              {children}
            </code>
          ),
          blockquote: ({ children }) => (
            <blockquote className="my-2 border-l-2 border-zinc-300 pl-3 italic text-zinc-600 dark:border-zinc-700 dark:text-zinc-400">
              {children}
            </blockquote>
          ),
          ul: ({ children }) => (
            <ul className="mb-2 ml-5 list-disc space-y-1 text-sm text-zinc-700 dark:text-zinc-300">
              {children}
            </ul>
          ),
          ol: ({ children }) => (
            <ol className="mb-2 ml-5 list-decimal space-y-1 text-sm text-zinc-700 dark:text-zinc-300">
              {children}
            </ol>
          ),
          hr: () => (
            <hr className="my-3 border-zinc-200 dark:border-zinc-800" />
          ),
          h2: ({ children }) => (
            <h2 className="mb-2 mt-3 text-base font-semibold text-zinc-900 dark:text-zinc-100">
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="mb-1.5 mt-2 text-sm font-semibold text-zinc-900 dark:text-zinc-100">
              {children}
            </h3>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
