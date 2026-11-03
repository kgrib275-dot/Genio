# Google Sheets 커넥터

구글 시트의 표를 읽어 AI에게 넘기거나, 결과를 새 행으로 추가해요.

## 준비
- **공개 시트를 읽기만** 할 때: Google Cloud 콘솔에서 Sheets API를 켜고 API 키를 만들어 연결 정보에 넣습니다.
- **비공개 시트·행 추가**: OAuth 액세스 토큰이 필요해요(프로토타입은 토큰을 직접 붙여 넣는 방식, 토큰은 약 1시간 뒤 만료).

## 동작
- **범위 읽기**: `spreadsheet_id`, `range` → `values`(2차원 배열), `text`(탭으로 구분한 글)
- **행 추가**: `spreadsheet_id`, `range`, `values`
