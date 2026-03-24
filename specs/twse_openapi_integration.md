# TWSE OpenAPI 整合計畫

## 現狀
- 使用 5/143 endpoints
- Swagger: `data/twse_swagger_20260325.json`
- 官方: `https://openapi.twse.com.tw/v1/swagger.json`
- Rate Limit: ~3 req/5s

## 目前使用
| Endpoint | 用途 | 程式 |
|----------|------|------|
| STOCK_DAY_ALL | 個股日成交 | fetcher.py |
| BWIBBU_ALL | PER/殖利率/PBR | twse_fetcher.py |
| MI_INDEX | 大盤指數 | fetcher.py |
| t187ap03_L | EPS | twse_fetcher.py |
| t187ap14_L | 月營收 | twse_fetcher.py |

## Phase 1 — 高價值快速整合（本週）
| 優先 | Endpoint | 用途 | 預估 |
|------|----------|------|------|
| P0 | holidaySchedule | 自動跳過休市日 | 15min |
| P0 | MI_MARGN | 融資融券（散戶情緒） | 30min |
| P1 | MI_QFIIS_sort_20 | 外資持股 Top 20 | 30min |
| P1 | announcement/notice | 注意股票 | 20min |
| P1 | announcement/punish | 處置股票 | 20min |

## Phase 2 — 策略增強（下週）
| Endpoint | 用途 |
|----------|------|
| TWT48U_ALL | 全市場 PER/殖利率/PBR |
| FMNPTK_ALL | 三大法人年度 |
| MI_QFIIS_cat | 外資持股類股比率 |
| TWT96U | 借券賣出（放空指標） |
| STOCK_DAY_AVG_ALL | 月均價 |

## Phase 3 — ESG + 公司治理（5月 M4P 64G）
- t187ap46 系列: 21 個 ESG 指標 endpoint
- t187ap45_L: 股利分派
- t187ap06/07 系列: 財報明細（資產/負債/損益/現金流）

## 整合方式
所有新 endpoint 加入 `data/twse_fetcher.py`：
1. 共用 rate limit 控制（3 req/5s）
2. 共用 DB 存儲（trades.db 新表）
3. 加入 daily_update.sh 排程
4. 加入 TG alert（異常通知）
