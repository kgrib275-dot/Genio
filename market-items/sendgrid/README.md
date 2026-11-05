# SendGrid 커넥터

SendGrid로 메일을 보내요(대량·알림 메일에 알맞아요).

## 준비
1. https://app.sendgrid.com 에서 **API 키**를 만들어요(Mail Send 권한).
2. **Sender Authentication**에서 보내는 주소를 인증해요.
3. 연결 정보 화면에서 SendGrid를 고르고 API 키와 보내는 주소를 넣어요.

## 동작
- **메일 보내기**: `to`, `subject`, `text`(+선택 `html`)
