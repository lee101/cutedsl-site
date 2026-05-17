import hljs from 'highlight.js/lib/core';
import bash from 'highlight.js/lib/languages/bash';
import c from 'highlight.js/lib/languages/c';
import cpp from 'highlight.js/lib/languages/cpp';
import go from 'highlight.js/lib/languages/go';
import javascript from 'highlight.js/lib/languages/javascript';
import json from 'highlight.js/lib/languages/json';
import plaintext from 'highlight.js/lib/languages/plaintext';
import python from 'highlight.js/lib/languages/python';
import rust from 'highlight.js/lib/languages/rust';
import typescript from 'highlight.js/lib/languages/typescript';

hljs.registerLanguage('bash', bash);
hljs.registerLanguage('sh', bash);
hljs.registerLanguage('shell', bash);
hljs.registerLanguage('c', c);
hljs.registerLanguage('cpp', cpp);
hljs.registerLanguage('go', go);
hljs.registerLanguage('javascript', javascript);
hljs.registerLanguage('js', javascript);
hljs.registerLanguage('json', json);
hljs.registerLanguage('plaintext', plaintext);
hljs.registerLanguage('text', plaintext);
hljs.registerLanguage('python', python);
hljs.registerLanguage('py', python);
hljs.registerLanguage('rust', rust);
hljs.registerLanguage('rs', rust);
hljs.registerLanguage('typescript', typescript);
hljs.registerLanguage('ts', typescript);

const aliases: Record<string, string> = {
  curl: 'bash',
  tsx: 'typescript',
  jsx: 'javascript',
};

function normalizeLanguage(language?: string) {
  const normalized = language?.trim().toLowerCase();
  if (!normalized) return 'plaintext';
  return aliases[normalized] || normalized;
}

function highlightedCode(code: string, language?: string) {
  const normalized = normalizeLanguage(language);

  if (hljs.getLanguage(normalized)) {
    return {
      language: normalized,
      value: hljs.highlight(code, { language: normalized, ignoreIllegals: true }).value,
    };
  }

  return {
    language: 'plaintext',
    value: hljs.highlight(code, { language: 'plaintext', ignoreIllegals: true }).value,
  };
}

export function CodeBlock({
  code,
  language,
  className = '',
}: {
  code: string;
  language?: string;
  className?: string;
}) {
  const highlighted = highlightedCode(code.trim(), language);

  return (
    <pre className={`hljs rounded-xl p-5 text-sm overflow-x-auto leading-relaxed shadow-sm ${className}`}>
      <code
        className={`language-${highlighted.language}`}
        dangerouslySetInnerHTML={{ __html: highlighted.value }}
      />
    </pre>
  );
}
