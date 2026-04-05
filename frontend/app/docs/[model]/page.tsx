import { MODEL_SLUGS } from '@/lib/models';
import ModelDocsClient from './model-docs-client';

export function generateStaticParams() {
  return MODEL_SLUGS.map(model => ({ model }));
}

export default async function ModelDocsPage({ params }: { params: Promise<{ model: string }> }) {
  const { model } = await params;
  return <ModelDocsClient slug={model} />;
}
