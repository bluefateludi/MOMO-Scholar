import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Link } from "react-router-dom";

const safeUrl = (url: string) => /^(https?:|mailto:|\/)/i.test(url) ? defaultUrlTransform(url) : "";
export function SafeMarkdown({ markdown, runId, evidenceIds }: { markdown: string; runId: string; evidenceIds: string[] }) {
  const linked = evidenceIds.reduce((text, id) => text.replaceAll(`[${id}]`, `[Evidence](/runs/${encodeURIComponent(runId)}/evidence/${encodeURIComponent(id)})`), markdown);
  const rewritten = linked.replace(/\[([^\]\n]+:ev_\d+)\]/g, "**Unresolved Evidence: `$1`**");
  return <article className="markdown"><ReactMarkdown skipHtml remarkPlugins={[remarkGfm]} urlTransform={safeUrl} components={{
    a: ({ href = "", children }) => href.startsWith("/runs/") ? <Link to={href}>{children}</Link> : <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
    img: () => null,
  }}>{rewritten}</ReactMarkdown></article>;
}
