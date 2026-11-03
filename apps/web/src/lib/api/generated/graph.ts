/* 자동 생성 파일: scripts/gen_types.py + npm run gen:types. 직접 고치지 마세요. */

export type Version = number;
export type Id = string;
export type Type = string;
export type X = number;
export type Y = number;
export type Nodes = GraphNode[];
export type Id1 = string;
export type Source = string;
export type Target = string;
export type Sourcehandle = string | null;
export type Targethandle = string | null;
export type Edges = GraphEdge[];

export interface Graph {
  version?: Version;
  nodes?: Nodes;
  edges?: Edges;
  variables?: Variables;
}
export interface GraphNode {
  id: Id;
  type: Type;
  position?: Position;
  data?: Data;
}
export interface Position {
  x?: X;
  y?: Y;
  [k: string]: unknown;
}
export interface Data {
  [k: string]: unknown;
}
export interface GraphEdge {
  id: Id1;
  source: Source;
  target: Target;
  sourceHandle?: Sourcehandle;
  targetHandle?: Targethandle;
}
export interface Variables {
  [k: string]: unknown;
}
