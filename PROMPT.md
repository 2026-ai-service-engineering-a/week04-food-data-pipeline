# 지시 프롬프트 기록

라이브 시연에서 사용한 지시 프롬프트를 회전별로 누적합니다.
브랜치가 지시 단위라면, 커밋은 그 안의 작업 단위입니다 — 재현자는
`git log`와 이 파일을 나란히 놓고 diff로 만들어진 순서를 따라갈 수 있습니다.

- 1회전 `feature/clean` → v0.2 — 정제 + 섭취참고량 파싱: 아래
- 2회전 `feature/pg-service` → v0.3 — PostgreSQL 적재와 검색 API: (예정)
- 3회전 `feature/rag-search` → v1.0 — 임베딩 인덱스와 RAG 질의응답: (예정)

---

## 1회전 `feature/clean` → v0.2

```plaintext
가공식품 데이터 정제 파이프라인을 만들어줘.

[1단계 — 정제]
- 입력: data/raw/*.xlsx 또는 data/sample/raw_sample.csv (같은 166열 스키마)
- pandas 기반. 처리 내용:
  - 문자열 컬럼의 BOM·제어문자 제거, 앞뒤 공백 정리, 유니코드 NFC 정규화
    (제어문자는 지우지 말고 공백으로 바꿔라 — 지우면 단어가 붙는다)
  - 식품명에 대체불가 깨진 문자(？ U+FF1F, U+FFFD)가 포함된 행은 별도 목록으로
    분리 저장 (버리지 말고 reports/rejected.csv로 — 사유 컬럼 포함)
  - 컬럼 슬림: 166열 중 17열만 남김
    식별·분류 6 (식품코드·식품명·대분류·중분류·소분류·제조사명)
    + 라벨 의무 표시 9 (에너지·탄수화물·당류·지방·트랜스지방·포화지방·
      콜레스테롤·단백질·나트륨)
    + 1회 섭취참고량(원문 유지)·식품중량(원문 유지 — '500g' 꼴 문자열이다)
  - 영양 수치 결측은 NULL 유지 (0으로 채우지 마 — 0과 모름은 다르다)
  - 정제 후 빈 문자열은 NULL로 되돌려라. 라이브러리가 None을 ""로 바꾸면
    결측이 "값 있음"으로 둔갑한다

[2단계 — 섭취참고량 파싱]
- 파싱하기 전에 df["1회 섭취참고량"].nunique()를 찍고 그 수를 리포트에 남겨라.
- 파싱은 행이 아니라 **고유값 단위**로 한다. 고유값별로 한 번만 풀고
  결과를 map으로 되붙여라.
- 1차 규칙 파서(정규식): '30g', '1회 40g' 같은 숫자+g. 순수 함수 + 유닛테스트
- 2차 규칙 확장: '200ml', '5g(ml)', '250ml(g)'처럼 다른 단위와 단위 병기.
  ml을 g으로 보는 것은 가정이므로 note에 남겨라
- 3차 LLM: 규칙이 못 푼 고유값만. LiteLLM 경유(PARSER_MODEL), instructor 사용.
  출력 스키마 ServingInfo — serving_g(int|None), variants(형태별 g 목록),
  confidence(high/low), note
- 숫자로 환산할 수 없으면 serving_g는 NULL — 지어내지 마
- 대표값 선택은 코드가 한다. LLM이 형태를 갈라내면 첫 형태를 대표로 삼아라
  (모델이 대표를 못 고를 때 정보를 버리지 않기 위해)
- 각 고유값에 파싱 방법(rule_g/rule_unit/llm/none)을 기록해라
- 배치 안전장치: 고유값 캐시(재실행 시 이미 푼 값 건너뜀), --llm-limit, 진행 로그
- --show-residual: 규칙이 못 푼 고유값을 전부 출력 (몇 개 안 되니 눈으로 본다)
- 디버그 로그: --debug일 때 LLM 프롬프트 전문·원출력·건별 토큰

- 출력: data/clean/foods_parsed.parquet
  + reports/clean_report.txt (입력·출력 행수, 제외 사유별, 열별 결측률,
    입력=출력+제외 검산)
  + reports/parse_report.txt (고유값 수, 방법별 커버리지 — 고유값 기준과 행 기준
    둘 다, LLM 호출 수·비용, 순진한 행 단위 배치였다면 들었을 비용 추정)
- 스팟 체크 도구: 방법별로 원문과 결과를 나란히 출력 (pipeline.spot_check)
- compose에 data-restore 서비스 추가: 릴리즈에서 받은 foods_parsed.parquet를
  data/dist/에 두면 data/clean/으로 옮긴다. 멱등하게, 없어도 조용히 나가게
- 작업 단위마다 커밋 — 문자 정리 → 분리·슬림 → 규칙 파서 → LLM 잔여 → 복원 서비스
```

### 이 지시가 실제로 만든 것

| 커밋 | 무엇 |
| --- | --- |
| `feat(pipeline): 문자 정리 순수 함수 + 유닛테스트` | `textclean.py` |
| `feat(pipeline): 정제 본체 — 분리·슬림·결측 정책 + 리포트` | `clean.py` · `report.py` |
| `feat(pipeline): 섭취참고량 파싱 — 세고, 접고, 남은 것만 LLM` | `serving*.py` · `spot_check.py` |
| `feat: data-restore — 받은 산출물을 제자리에` | `scripts/restore.sh` · compose |

### 전량 실행 결과 (306,307건)

```plaintext
[clean] 입력: 306,307행 · 166열 → 출력: 306,301행 · 17열 · 제외 6행
[count] 고유값 34개
[rule ] 1차 16개 → 166,991행 · 2차 12개 → 60,291행
[llm  ] 5개 호출 → 19,909행 · $0.0045
[none ] 1개('1식') + 빈 값 → 59,110행
[cost ] 행 단위였다면 $16.13 (23,047회) — 3,560배
```
