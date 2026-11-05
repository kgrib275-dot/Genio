# 솔라피(Solapi) 커넥터

솔라피로 문자(SMS·LMS)와 카카오 알림톡을 보내요.

## 준비
1. https://console.solapi.com 에서 **API Key/Secret**을 만들고 **발신번호**를 등록해요.
2. 알림톡은 카카오 채널 연동과 템플릿 승인이 필요해요.

## 동작
- **문자 보내기**: `to`, `text`
- **알림톡 보내기**: `to`, `pf_id`, `template_id`, `variables`

서명(HMAC-SHA256)은 제니오가 자동으로 만들어서, 키와 Secret만 넣으면 돼요.
