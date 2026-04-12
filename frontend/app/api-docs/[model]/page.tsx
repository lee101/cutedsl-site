import { MODEL_SLUGS } from '@/lib/models';
import ModelDocsClient from '../../docs/[model]/model-docs-client';

export function generateStaticParams() {
  return MODEL_SLUGS.map(model => ({ model }));
}

export default async function ApiDocsModelPage({ params }: { params: Promise<{ model: string }> }) {
  const { model } = await params;
  return <ModelDocsClient slug={model} />;
}
