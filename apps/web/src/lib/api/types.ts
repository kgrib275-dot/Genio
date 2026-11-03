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

export interface Preferences {
  theme: "light" | "dark" | "system";
  font_size: "normal" | "large";
  default_workspace_id: string | null;
  enter_to_send: boolean;
}

export const DEFAULT_PREFERENCES: Preferences = {
  theme: "system",
  font_size: "normal",
  default_workspace_id: null,
  enter_to_send: true,
};

export interface Me {
  id: string;
  email: string;
  name: string;
  workspaces: WorkspaceRef[];
  preferences?: Partial<Preferences>;
}

export type ProjectColor = "indigo" | "sky" | "emerald" | "amber" | "rose" | "violet" | "slate";

export interface Project {
  id: string;
  workspace_id: string;
  name: string;
  description: string;
  color: ProjectColor;
  visibility: "workspace" | "private";
  created_by: string | null;
  created_by_name: string;
  created_at: string;
  app_count: number;
  knowledge_base_count: number;
  members: { user_id: string; name: string; email: string }[];
  can_manage: boolean;
}

export interface Member {
  id: string;
  user_id: string;
  email: string;
  name: string;
  role: Role;
  /** 이 워크스페이스에만 속한 계정(관리자가 비밀번호를 재설정할 수 있음) */
  only_here?: boolean;
}

export interface CreatedAccount {
  member: Member;
  /** 자동으로 만든 임시 비밀번호. 이번 한 번만 보여 준다(직접 정했으면 null). */
  temporary_password: string | null;
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
  project_id?: string | null;
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
  project_id?: string | null;
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

// ---------------- v0.2 ----------------
export interface AppFeatures {
  opening_statement: string;
  suggested_questions: string[];
  follow_up: { enabled: boolean };
  citations: { enabled: boolean };
  moderation: { enabled: boolean; keywords: string[]; preset_reply: string; check_output: boolean };
  annotation_reply: { enabled: boolean; score_threshold: number };
  speech: { stt: boolean; tts: boolean };
  file_upload: { enabled: boolean; max_files: number };
  memory: { window: number };
}

export const DEFAULT_FEATURES: AppFeatures = {
  opening_statement: "",
  suggested_questions: [],
  follow_up: { enabled: false },
  citations: { enabled: false },
  moderation: { enabled: false, keywords: [], preset_reply: "", check_output: false },
  annotation_reply: { enabled: false, score_threshold: 0.85 },
  speech: { stt: false, tts: false },
  file_upload: { enabled: false, max_files: 3 },
  memory: { window: 0 },
};

/** 서버가 일부 키를 빠뜨려도 화면이 깨지지 않게 기본값과 합친다. */
export function normalizeFeatures(f: Partial<AppFeatures> | null | undefined): AppFeatures {
  const src = f ?? {};
  return {
    opening_statement: src.opening_statement ?? "",
    suggested_questions: src.suggested_questions ?? [],
    follow_up: { ...DEFAULT_FEATURES.follow_up, ...src.follow_up },
    citations: { ...DEFAULT_FEATURES.citations, ...src.citations },
    moderation: { ...DEFAULT_FEATURES.moderation, ...src.moderation },
    annotation_reply: { ...DEFAULT_FEATURES.annotation_reply, ...src.annotation_reply },
    speech: { ...DEFAULT_FEATURES.speech, ...src.speech },
    file_upload: { ...DEFAULT_FEATURES.file_upload, ...src.file_upload },
    memory: { ...DEFAULT_FEATURES.memory, ...src.memory },
  };
}

export interface EnvVar {
  key: string;
  value: string;
  secret: boolean;
}

export interface AppDetailV2 extends AppDetail {
  features?: Partial<AppFeatures> | null;
  env_vars?: EnvVar[] | null;
}

export interface AppExport {
  genio_version: string;
  app: { name: string; type: AppType; description: string; icon: string; features?: unknown };
  graph: unknown;
  env_vars?: EnvVar[];
}

export interface StoredFile {
  id: string;
  filename: string;
  mime: string;
  size: number;
  created_at: string;
}

export interface ConversationSummary {
  id: string;
  user_name: string | null;
  external_session_id: string | null;
  message_count: number;
  likes: number;
  dislikes: number;
  created_at: string;
  last_message_at: string | null;
  first_question: string | null;
}

export type Rating = "like" | "dislike";

export interface ConversationMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  run_id: string | null;
  feedback: Rating | null | { rating?: Rating | null; comment?: string | null };
  created_at: string;
  annotated?: boolean;
  moderated?: boolean;
}

export interface Annotation {
  id: string;
  question: string;
  answer: string;
  hit_count: number;
  created_at: string;
}

export interface StatPoint {
  date?: string;
  runs: number;
  conversations: number;
  messages: number;
  input_tokens: number;
  output_tokens: number;
  cost: number | string;
  avg_latency_ms: number;
  success_rate: number;
  likes: number;
  dislikes: number;
}

export interface AppStats {
  days: (StatPoint & { date: string })[];
  totals: StatPoint;
}

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  app_id?: string;
  app_name?: string;
}

export interface NewApiKey extends ApiKey {
  key: string;
}

export type ChunkMode = "general" | "parent_child";
export type RetrievalMethod = "vector" | "keyword" | "hybrid";

export interface KbSettings {
  chunk_mode: ChunkMode;
  separator: string;
  chunk_size: number;
  chunk_overlap: number;
  child_chunk_size: number;
  retrieval: {
    method: RetrievalMethod;
    top_k: number;
    score_threshold: number;
    vector_weight: number;
    rerank: boolean;
  };
}

export const DEFAULT_KB_SETTINGS: KbSettings = {
  chunk_mode: "general",
  separator: "\n\n",
  chunk_size: 800,
  chunk_overlap: 100,
  child_chunk_size: 200,
  retrieval: { method: "vector", top_k: 4, score_threshold: 0, vector_weight: 0.7, rerank: false },
};

export function normalizeKbSettings(s: Partial<KbSettings> | null | undefined): KbSettings {
  const src = s ?? {};
  return {
    ...DEFAULT_KB_SETTINGS,
    ...src,
    retrieval: { ...DEFAULT_KB_SETTINGS.retrieval, ...(src.retrieval ?? {}) },
  };
}

export interface KnowledgeBaseV2 extends KnowledgeBase {
  settings?: Partial<KbSettings> | null;
}

export interface KbDocumentV2 extends KbDocument {
  metadata?: Record<string, string> | null;
  source?: "upload" | "url";
  url?: string | null;
}

export interface KbChunk {
  id: string;
  index: number;
  content: string;
  parent_content: string | null;
  enabled: boolean;
  char_count: number;
}

export interface SearchHitV2 extends SearchHit {
  metadata?: Record<string, string> | null;
}

export interface Citation {
  index: number;
  filename: string;
  content: string;
  score: number;
}

export interface PublicFeatures {
  opening_statement?: string;
  suggested_questions?: string[];
  follow_up?: { enabled: boolean };
  citations?: { enabled: boolean };
  speech?: { stt: boolean; tts: boolean };
  file_upload?: { enabled: boolean; max_files: number };
}

export interface PublicAppV2 extends PublicApp {
  features?: PublicFeatures | null;
}

export interface AdminOverview {
  counts: {
    members: number;
    apps: number;
    published_apps: number;
    knowledge_bases: number;
    documents: number;
    api_keys: number;
  };
  days: {
    date: string;
    runs: number;
    tokens: number;
    cost: number | string;
    active_users: number;
    conversations: number;
  }[];
  top_apps: { app_id: string; app_name: string; runs: number; cost: number | string }[];
}

export interface WorkspaceSettings {
  default_models?: { chat?: string | null; embedding?: string | null };
  public_rate_limit_per_minute?: number;
  [k: string]: unknown;
}

export interface WorkspaceInfo {
  id: string;
  name: string;
  settings: WorkspaceSettings | null;
}

export interface SystemSettings {
  is_instance_admin: boolean;
  allow_signup: boolean;
}

/** 프로젝트 현황판: 프로젝트(또는 '프로젝트 없음') 하나의 기간 통계 */
export interface ProjectStats {
  apps: number;
  published_apps: number;
  knowledge_bases: number;
  documents: number;
  runs: number;
  succeeded: number;
  failed: number;
  waiting_approval: number;
  input_tokens: number;
  output_tokens: number;
  cost: number;
  conversations: number;
  last_activity_at: string | null;
  success_rate: number | null;
  series: { date: string; runs: number }[];
}

export interface ProjectsOverview {
  days: number;
  totals: {
    projects: number;
    apps: number;
    published_apps: number;
    runs: number;
    succeeded: number;
    failed: number;
    waiting_approval: number;
    cost: number;
    conversations: number;
    success_rate: number | null;
  };
  projects: (ProjectStats & { project: Project })[];
  unassigned: ProjectStats;
}
