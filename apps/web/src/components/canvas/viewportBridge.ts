// 캔버스(React Flow) 밖의 화면(단계 추가 패널 등)이 '지금 보이는 캔버스의 한가운데' 좌표를 알 수 있게
// 캔버스가 안내 함수를 등록해 둔다. 스니펫을 끼워 넣을 때 화면 한가운데에 놓는 데 쓴다.
type Getter = () => { x: number; y: number };

let getter: Getter | null = null;

export function registerViewportCenter(fn: Getter | null): void {
  getter = fn;
}

/** 캔버스가 보여 주는 영역의 한가운데(흐름 좌표). 등록된 캔버스가 없으면 기본 자리. */
export function viewportCenter(): { x: number; y: number } {
  return getter ? getter() : { x: 200, y: 160 };
}
