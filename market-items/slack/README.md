# Slack 커넥터

흐름에서 슬랙 채널로 메시지를 보낼 수 있어요.

## 준비
1. https://api.slack.com/apps 에서 앱을 만들고 `chat:write` 권한을 줍니다.
2. 워크스페이스에 설치한 뒤 **Bot User OAuth Token**(`xoxb-…`)을 복사합니다.
3. Genio의 **연결 정보** 화면에서 Slack을 고르고 토큰을 붙여 넣습니다.
4. 메시지를 받을 채널에 봇을 초대합니다(`/invite @봇이름`).

## 동작
- **메시지 보내기**: `channel`(예: `#billing`), `text`
