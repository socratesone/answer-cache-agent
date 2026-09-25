import type { Event } from "../generated/Event";
import type { Result } from "../generated/Result";
export type { Event, Result };
export type Constraint = {
  max_length?: number;
  max_words?: number;
  required?: boolean;
};
export type Field = {
  id: string;
  formId: string;
  question: string;
  constraints: Constraint;
  prefilled: boolean;
  version: number;
  signature: string;
  kind?: "text" | "select" | "radio" | "checkbox" | "combobox" | "file";
  options?: string[];
};
export type Page = {
  scanSeq?: number;
  intent?: { id: string; mode: "saved" | "ai"; fieldId: string };
  documentToken: string;
  url: string;
  title: string;
  fields: Field[];
  activeId?: string;
  tabId?: number;
  documentId?: string;
};
export type Hint = { dimension: string; value: string; source: "user" };
export type FormState = {
  sessionId: string;
  revision: string | null;
  prepared: boolean;
  formId: string;
  hints: Hint[];
  prepareKey?: string;
};
export type HostInfo = {
  version: string;
  configured: boolean;
  generationReady: boolean;
  settings: {
    roles?: Record<"routine" | "advanced", { provider: string; model: string }>;
  };
  budget: { max_session_cost_usd: number };
  capabilities: Record<string, boolean>;
};
export type Match = {
  id: string;
  body: string;
  intent: string;
  status: string;
  similarity: number;
  version?: number;
  applies: Record<string, string[]>;
};
export type Target = Pick<Field, "id" | "formId" | "version" | "signature"> & {
  documentToken: string;
  tabId: number;
  documentId: string;
};
export type Pending = {
  id: string;
  operation: string;
  data: Record<string, unknown>;
  stopped?: boolean;
};
