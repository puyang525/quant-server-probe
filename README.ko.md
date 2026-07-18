# 퀀트 트레이딩 서버 프로브

[English](README.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md) | [日本語](README.ja.md) | [한국어](README.ko.md)

클라우드 공급자, 리전 및 인스턴스 유형을 비교하기 위한 의존성 없는 읽기 전용 저부하 Linux 프로브입니다. IBKR, Futu OpenAPI/FutuOpenD, Binance/OKX 무기한 선물, 디지털 자산 거래소, Polymarket, 시세 데이터 공급자의 REST/WebSocket 연결과 CPU, 메모리, 디스크, `fsync`, NTP 상태를 측정합니다.

> **커뮤니티 순위 데이터 제공은 완전한 선택 사항이며 기본적으로 꺼져 있습니다.** 일반 `probe`는 데이터를 수집하거나 원격 측정 또는 업로드하지 않습니다. 별도로 `public`을 실행하고 익명화된 JSON을 직접 검토한 뒤 GitHub Pull Request를 제출한 경우에만 참여합니다. 전체 프로브 보고서는 제출하지 마십시오.

```bash
curl -fsSL https://raw.githubusercontent.com/puyang525/quant-server-probe/main/run.sh | bash
```

실행 언어는 `LC_ALL`, `LC_MESSAGES`, `LANG`에서 자동 감지합니다. 지원되지 않는 로캘이고 대화형 터미널이 있으면 언어를 묻고, 비대화형 실행에서는 영어로 안전하게 전환합니다. 전체 명령, 평가 방식, 지역 제한 및 익명화 데이터 규격은 [영문 문서](README.md)를 참조하십시오.

공개 샘플의 공급자, 리전 및 플랜 이름은 어떤 언어로도 작성할 수 있습니다. 집계는 고정 JSON 키, ISO 국가 코드 및 숫자 측정값을 사용하므로 표시 언어와 무관합니다.
