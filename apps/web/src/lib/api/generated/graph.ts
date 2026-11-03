/* 자동 생성 파일: scripts/gen_types.py + npm run gen:types. 직접 고치지 마세요. */

export type Version = number;
export type Id = string;
export type Type = string;
export type X = number;
export type Y = number;
export type Disabled = boolean | null;
export type Nodes = GraphNode[];
export type Id1 = string;
export type Source = string;
export type Target = string;
export type Sourcehandle = string | null;
export type Targethandle = string | null;
export type Edges = GraphEdge[];
export type Notes = GraphNote[] | null;
export type Id2 = string;
export type Text = string;
export type Width = number;
export type Height = number;
export type Color = "yellow" | "blue" | "green" | "pink" | "gray";

export interface Graph {
  version?: Version;
  nodes?: Nodes;
  edges?: Edges;
  variables?: Variables;
  notes?: Notes;
}
export interface GraphNode {
  id: Id;
  type: Type;
  position?: Position;
  data?: Data;
  disabled?: Disabled;
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
/**
 * 캔버스 메모(실행과 무관). n8n의 스티커 메모.
 */
export interface GraphNote {
  id: Id2;
  text?: Text;
  position?: Position;
  width?: Width;
  height?: Height;
  color?: Color;
}
