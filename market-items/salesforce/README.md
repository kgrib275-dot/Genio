# Salesforce 커넥터

Salesforce에 리드를 만들거나 SOQL로 조회해요(액세스 토큰 방식).

## 준비
1. Salesforce에서 API 접근이 가능한 사용자와 **연결된 앱**(OAuth)을 준비해요.
2. 발급한 **액세스 토큰**과 **인스턴스 주소**를 연결 정보에 넣어요(토큰은 만료되면 새로 넣어요).

## 동작
- **리드 만들기**: `last_name`, `company`
- **SOQL로 조회**: SELECT만 가능해요.
