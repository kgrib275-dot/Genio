// docs/api.md 응답 형식. 그래프 타입만 백엔드 JSON Schema에서 생성한다(generated/graph.ts).
import type {
  Graph as GeneratedGraph,
  GraphEdge as GeneratedEdge,
  GraphNode as GeneratedNode,
} from "@/lib/api/generated/graph";

export type GraphNode = Required<Pick<GeneratedNode, "id" | "type">> & {
  position: { x: number; y: number };
  data: Record<string, unknown>;
};
export type GraphEdge = Omit<GeneratedEdge, "sourceHandle" | "targetHandle"> & {
  sourceHandle?: string | null;
  targetHandle?: string | null;
};
export interface Graph {
  version: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
  variables: Record<string, unknown>;
}

/** 서버에서 받은 그래프(선택 필드가 빠져 있을 수 있음)를 화면용 형태로 맞춘다. */
export function normalizeGraph(g: GeneratedGraph | null | undefined): Graph {
  return {
    version: g?.version ?? 1,
    nodes: (g?.nodes ?? []).map((n) => ({
      id: n.id,
      type: n.type,
      position: { x: n.position?.x ?? 0, y: n.position?.y ?? 0 },
      data: (n.data ?? {}) as Record<string, unknown>,
    })),
    edges: (g?.edges ?? []).map((e) => ({ ...e })),
    variables: (g?.variables ?? {}) as Record<string, unknown>,
  };
}

export type Role = "owner" | "admin" | "builder" | "operator" | "member";
export const ROLES: Role[] = ["owner", "admin", "builder", "operator", "member"];

export interface GraphError {
  node_id?: string | null;
  field?: string | null;
  message: string;
}

export interface ApiErrorDetail {
  message: string;
  hint?: string;
  errors?: GraphError[];
}

export interface Tokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface WorkspaceRef {
  id: string;
  name: string;
  slug: string;
  role: Role;
}

export interface Me {
  id: string;
  email: string;
  name: string;
  workspaces: WorkspaceRef[];
}

export interface Member {
  id: string;
  user_id: string;
  email: string;
  name: string;
  role: Role;
}

export interface Invitation {
  id: string;
  email: string;
  role: Role;
  token: string;
  expires_at: string;
  accept_url: string;
  accepted_at?: string | null;
}

export interface InvitationInfo {
  email: string;
  role: Role;
  workspace_name: string;
  expired: boolean;
  accepted: boolean;
}

export type ProviderKind = "openai" | "anthropic" | "google" | "openai-compatible";

export interface LlmProvider {
  id: string;
  provider: ProviderKind;
  label: string;
  base_url: string | null;
  default_model: string;
  is_default: boolean;
  api_key_masked: string;
}

export interface ConnectorAction {
  key: string;
  label: string;
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
}

export interface ConnectorManifest {
  key: string;
  name: string;
  requires?: { credentials?: { key: string; label: string; secret?: boolean }[] };
  actions?: ConnectorAction[];
  [k: string]: unknown;
}

export interface ConnectorDefinition {
  id: string;
  key: string;
  name: string;
  version: string;
  source: string;
  manifest: ConnectorManifest;
}

export interface ConnectorCredential {
  id: string;
  definition_id: string;
  connector_key: string;
  connector_name: string;
  name: string;
  created_at: string;
  secrets_masked: Record<string, string>;
}

export interface NodeType {
  type: string;
  label: string;
  category: string;
  description: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  ui_schema: Record<string, unknown>;
  source: "builtin" | "market";
}

export type AppType = "chat" | "workflow" | "form";

export interface App {
  id: string;
  workspace_id: string;
  name: string;
  slug: string;
  type: AppType;
  description: string;
  icon: string;
  status: "draft" | "published";
  created_by: string | null;
  updated_at: string;
  latest_version: number | null;
}

export interface AppDetail extends App {
  draft_graph: GeneratedGraph;
}

export interface VersionSummary {
  id: string;
  version: number;
  note: string;
  created_at: string;
  created_by: string | null;
}

export interface VersionDetail extends VersionSummary {
  graph: GeneratedGraph;
}

export interface ValidationResult {
  valid: boolean;
  errors: GraphError[];
}

export type RunStatus = "queued" | "running" | "succeeded" | "failed" | "waiting_approval";

export interface Run {
  id: string;
  app_id: string;
  version_id: string | null;
  trigger: string;
  status: RunStatus;
  input: Record<string, unknown>;
  output: { text?: string; outputs?: Record<string, unknown> } | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  token_usage: { input_tokens?: number; output_tokens?: number };
  cost: number | string;
  app_name?: string;
}

export interface RunStep {
  id: string;
  node_id: string;
  status: "running" | "succeeded" | "failed" | "skipped" | "waiting_approval";
  input: Record<string, unknown>;
  output: Record<string, unknown> | null;
  logs: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface RunApproval {
  node_id: string;
  message: string;
  approver_roles: Role[];
  decided_by?: string | null;
  approved?: boolean | null;
  comment?: string | null;
}

export interface RunDetail extends Run {
  steps: RunStep[];
  approval: RunApproval | null;
  graph: GeneratedGraph;
}

export interface BuilderSession {
  id: string;
  app_id: string;
  user_id: string;
  created_at: string;
}

export type PatchOp =
  | { op: "add_node"; node: GraphNode }
  | { op: "update_node"; id: string; data: Record<string, unknown> }
  | { op: "remove_node"; id: string }
  | { op: "add_edge"; edge: GraphEdge }
  | { op: "remove_edge"; id: string };

export interface ToolCallRecord {
  id: string;
  name: string;
  input?: Record<string, unknown>;
  ok?: boolean;
  summary?: string;
}

export interface AskUser {
  question: string;
  options: string[];
}

export interface MarketSuggestion {
  item: MarketItem;
  reason: string;
}

export interface TestResult {
  run_id: string;
  status: RunStatus;
  output: Run["output"];
  error: string | null;
}

export interface TurnRecord {
  ops?: PatchOp[];
  tool_calls?: ToolCallRecord[];
  ask_user?: AskUser;
  market_suggestion?: MarketSuggestion;
  test_result?: TestResult;
}

export interface BuilderMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  graph_patch: TurnRecord | null;
  created_at: string;
}

export interface KnowledgeBase {
  id: string;
  name: string;
  embedding_model: string;
  chunk_size: number;
  created_at: string;
  document_count: number;
}

export interface KbDocument {
  id: string;
  kb_id: string;
  filename: string;
  mime: string;
  size: number;
  status: "uploaded" | "processing" | "ready" | "failed";
  error: string | null;
  created_at: string;
  chunk_count: number;
}

export interface SearchHit {
  chunk_id: string;
  document_id: string;
  filename: string;
  content: string;
  score: number;
}

export type Channel = "web_widget" | "share_link" | "api";
export type Access = "workspace" | "roles" | "public";

export interface Deployment {
  id: string;
  app_id: string;
  version_id: string;
  version: number;
  channel: Channel;
  public_token: string;
  access: Access;
  allowed_roles: Role[];
  created_at: string;
  share_url: string;
  widget_snippet: string;
  api_url: string;
}

export interface PublicApp {
  name: string;
  description: string;
  icon: string;
  type: AppType;
  access: Access;
  requires_login: boolean;
  can_use: boolean;
  input_fields: { key: string; label?: string; type?: string; required?: boolean }[];
}

export type MarketType = "template" | "node" | "connector" | "prompt_pack";

export interface MarketItem {
  key: string;
  type: MarketType;
  name: string;
  summary: string;
  version: string;
  publisher: string;
  price: number;
  tags: string[];
  installs: number;
  installed: boolean | null;
}

export interface MarketItemDetail extends MarketItem {
  description_md: string;
  manifest: Record<string, unknown>;
}

export interface Installation {
  id: string;
  item_key: string;
  item_name: string;
  type: MarketType;
  version: string;
  status: string;
  installed_at: string;
}

export interface Template {
  key: string;
  name: string;
  summary: string;
  graph: GeneratedGraph;
}

export interface PromptPack {
  key: string;
  name: string;
  prompts: { key: string; title: string; system: string; prompt: string }[];
}

export interface Usage {
  total_runs: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost: number | string;
  by_app: {
    app_id: string;
    app_name: string;
    runs: number;
    input_tokens: number;
    output_tokens: number;
    cost: number | string;
  }[];
}

export interface AuditLog {
  id: string;
  user_id: string | null;
  user_email: string | null;
  action: string;
  target_type: string;
  target_id: string | null;
  meta: Record<string, unknown>;
  created_at: string;
}
