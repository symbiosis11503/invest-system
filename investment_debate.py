#!/usr/bin/env python3
"""投資辯論系統 — 多角色 AI 辯論分析個股

Phase 2: 看多/看空/仲裁三角色辯論
用 Gemini 2.0 Flash（免費）驅動

用法：
  python investment_debate.py 2330          # 辯論台積電
  python investment_debate.py 2330 --json   # 輸出 JSON
"""
import json
import os
import sys
import requests
from datetime import datetime
from investment_analyst import analyze_stock

# Gemini API 設定
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# 角色系統 prompt
ROLES = {
    "bull": {
        "name": "看多研究員",
        "emoji": "🐂",
        "prompt": """你是看多研究員。從以下分析數據中找出所有支持買進的理由：
1. 基本面優勢（EPS 成長、低 PER、高殖利率）
2. 技術面訊號（量價配合、近期走勢）
3. 籌碼面（外資/投信連續買超、融資減少）
4. 營收動能

有理有據，引用具體數據。不是盲目看多，而是找到真正的投資價值。
輸出：250 字以內繁體中文看多論述，最後附「信心指數：X/10」。"""
    },
    "bear": {
        "name": "看空研究員",
        "emoji": "🐻",
        "prompt": """你是看空研究員（魔鬼代言人）。從以下分析數據中找出所有風險和看空理由：
1. 估值風險（PER 過高、EPS 衰退、股價超漲）
2. 技術面警訊（量縮價漲、近期走弱）
3. 籌碼面風險（外資賣超、融資暴增）
4. 營收衰退、產業逆風

你的存在是為了保護投資人。寧可錯過機會，不可忽視風險。
輸出：250 字以內繁體中文看空論述，最後附「風險指數：X/10」。"""
    },
    "arbiter": {
        "name": "仲裁分析師",
        "emoji": "⚖️",
        "prompt": """你是中立仲裁分析師。綜合看多和看空研究員的論點：
1. 客觀評估雙方論點的強度和可信度
2. 指出哪些論點有數據支撐，哪些是推測
3. 給出最終綜合評分（1-10，1=強烈看空，10=強烈看多）
4. 建議操作：買進/觀望/賣出
5. 建議倉位比例和停損策略

你不偏向任何一方，只看證據。
輸出：300 字以內繁體中文仲裁報告。"""
    }
}


_gemini_key_index = 0

def _get_all_gemini_keys():
    """收集所有 GEMINI_API_KEY* 環境變數"""
    keys = []
    for suffix in ['', '2', '3', '4', '5', '6', '7', '_APEX', '_ECHO']:
        key = os.environ.get(f'GEMINI_API_KEY{suffix}')
        if key:
            keys.append(key)
    return keys


def _call_gemini(system_prompt, user_prompt):
    """呼叫 Gemini API（自動輪替 key 避開 rate limit）"""
    global _gemini_key_index
    keys = _get_all_gemini_keys()
    if not keys:
        return "[錯誤: 未設定 GEMINI_API_KEY]"

    import time
    for attempt in range(len(keys)):
        api_key = keys[_gemini_key_index % len(keys)]
        _gemini_key_index += 1
        try:
            resp = requests.post(
                f"{GEMINI_URL}?key={api_key}",
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": user_prompt}]}],
                    "systemInstruction": {"parts": [{"text": system_prompt}]},
                    "generationConfig": {
                        "temperature": 0.7,
                        "maxOutputTokens": 800,
                    }
                },
                timeout=30,
            )
            if resp.status_code == 429:
                time.sleep(2)
                continue  # 換下一個 key
            resp.raise_for_status()
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        except requests.exceptions.HTTPError:
            continue
        except Exception as e:
            return f"[API 錯誤: {e}]"
    return "[所有 API key 都被限流，請稍後再試]"


def format_data_for_ai(report):
    """將分析報告格式化為 AI 可讀的文字"""
    name = report.get("name", {}).get("name_zh", report["symbol"])
    lines = [f"股票: {name} ({report['symbol']})"]

    # 估值
    v = report.get("valuation", {})
    if v:
        lines.append(f"PER: {v.get('per', 'N/A')} | PBR: {v.get('pbr', 'N/A')} | 殖利率: {v.get('dividend_yield', 'N/A')}%")

    # EPS
    eps = report.get("eps", [])
    if eps:
        eps_str = ", ".join([f"Q{e.get('quarter','?')}: {e.get('eps','N/A')}" for e in eps[:4]])
        lines.append(f"近四季 EPS: {eps_str}")
        if report.get("annual_eps"):
            lines.append(f"年化 EPS: {report['annual_eps']}")

    # 法人
    inst = report.get("institutional", [])
    if inst:
        latest = inst[0]
        lines.append(f"最近法人: 外資 {latest.get('foreign_net', 0):+,} | 投信 {latest.get('trust_net', 0):+,} | 自營 {latest.get('dealer_net', 0):+,}")
    streak = report.get("foreign_buy_streak", {})
    if streak.get("days", 0) > 0:
        lines.append(f"外資連買 {streak['days']} 天（累計 {streak.get('total', 0):+,} 張）")

    # 融資券
    m = report.get("margin", {})
    if m:
        lines.append(f"融資餘額: {m.get('margin_balance', 'N/A')} | 融券餘額: {m.get('short_balance', 'N/A')}")

    # 營收
    rev = report.get("revenue", [])
    if rev:
        latest_rev = rev[0]
        lines.append(f"最近月營收 YoY: {latest_rev.get('revenue_yoy', 'N/A')}% | MoM: {latest_rev.get('revenue_mom', 'N/A')}%")
    if report.get("revenue_growth_streak", 0) > 0:
        lines.append(f"營收連續成長 {report['revenue_growth_streak']} 個月")

    # 股價
    prices = report.get("recent_prices", [])
    if prices:
        lines.append(f"最近收盤: {prices[0].get('close', 'N/A')} | 成交量: {prices[0].get('volume', 'N/A'):,}")

    # 系統評分
    lines.append(f"系統綜合評分: {report.get('score', 'N/A')}/10")

    return "\n".join(lines)


def run_debate(symbol, max_rounds=1):
    """對一檔股票執行完整辯論流程

    Args:
        symbol: 股票代號
        max_rounds: 辯論輪數 (1=標準, 2+=多輪深度辯論)
    """
    # Step 1: 取得分析數據
    report = analyze_stock(symbol)
    data_text = format_data_for_ai(report)
    name = report.get("name", {}).get("name_zh", symbol)

    result = {
        "symbol": symbol,
        "name": name,
        "timestamp": datetime.now().isoformat(),
        "max_rounds": max_rounds,
        "data": report,
        "debate": {"rounds": []}
    }

    bull_response = None
    bear_response = None

    for round_num in range(1, max_rounds + 1):
        round_data = {"round": round_num}

        # 看多研究員
        if round_num == 1:
            bull_prompt = f"以下是 {name}({symbol}) 的最新分析數據：\n\n{data_text}\n\n請給出你的看多分析。"
        else:
            bull_prompt = f"""以下是 {name}({symbol}) 第 {round_num} 輪辯論。

【原始數據】
{data_text}

【上一輪你的看多觀點】
{bull_response}

【對手的看空觀點】
{bear_response}

請針對對手的論點進行反駁，並強化你的看多立場。聚焦在具體數據和邏輯漏洞。"""
        bull_response = _call_gemini(ROLES["bull"]["prompt"], bull_prompt)
        round_data["bull"] = {"role": ROLES["bull"]["name"], "response": bull_response}

        # 看空研究員
        if round_num == 1:
            bear_prompt = f"以下是 {name}({symbol}) 的最新分析數據：\n\n{data_text}\n\n請給出你的看空分析。"
        else:
            bear_prompt = f"""以下是 {name}({symbol}) 第 {round_num} 輪辯論。

【原始數據】
{data_text}

【上一輪你的看空觀點】
{bear_response}

【對手的看多觀點】
{bull_response}

請針對對手的論點進行反駁，並強化你的看空立場。聚焦在具體數據和邏輯漏洞。"""
        bear_response = _call_gemini(ROLES["bear"]["prompt"], bear_prompt)
        round_data["bear"] = {"role": ROLES["bear"]["name"], "response": bear_response}

        result["debate"]["rounds"].append(round_data)

    # 向下相容：保留 debate.bull / debate.bear 欄位
    result["debate"]["bull"] = result["debate"]["rounds"][-1]["bull"]
    result["debate"]["bear"] = result["debate"]["rounds"][-1]["bear"]

    # 仲裁分析師（讀最終輪多空論述）
    rounds_summary = ""
    if max_rounds > 1:
        for r in result["debate"]["rounds"]:
            rounds_summary += f"\n--- 第 {r['round']} 輪 ---\n"
            rounds_summary += f"【🐂 看多】{r['bull']['response'][:500]}\n"
            rounds_summary += f"【🐻 看空】{r['bear']['response'][:500]}\n"

    arbiter_prompt = f"""以下是 {name}({symbol}) 的分析數據和多空辯論：

【原始數據】
{data_text}

{"【辯論歷程 (" + str(max_rounds) + " 輪)】" + rounds_summary if max_rounds > 1 else ""}
【🐂 看多研究員 (最終立場)】
{bull_response}

【🐻 看空研究員 (最終立場)】
{bear_response}

請綜合雙方觀點，給出你的仲裁報告。{"注意：這是 " + str(max_rounds) + " 輪深度辯論，請特別關注各輪論點的演變和最終共識。" if max_rounds > 1 else ""}"""
    arbiter_response = _call_gemini(ROLES["arbiter"]["prompt"], arbiter_prompt)
    result["debate"]["arbiter"] = {
        "role": ROLES["arbiter"]["name"],
        "response": arbiter_response
    }

    return result


def format_debate_report(result):
    """格式化辯論報告為人類可讀格式"""
    name = result.get("name", result["symbol"])
    max_rounds = result.get("max_rounds", 1)
    lines = [
        f"{'='*50}",
        f"  📊 {name} ({result['symbol']}) 投資辯論報告",
        f"  {result['timestamp'][:16]}  ({max_rounds} 輪辯論)",
        f"{'='*50}",
    ]

    rounds = result.get("debate", {}).get("rounds", [])
    if rounds and max_rounds > 1:
        for r in rounds:
            lines.append(f"\n--- 第 {r['round']} 輪 ---")
            lines.append(f"🐂 【看多】")
            lines.append(r["bull"]["response"] or "(無回應)")
            lines.append(f"🐻 【看空】")
            lines.append(r["bear"]["response"] or "(無回應)")
    else:
        lines.append("")
        lines.append(f"🐂 【看多研究員】")
        lines.append(result["debate"]["bull"]["response"] or "(無回應)")
        lines.append("")
        lines.append(f"🐻 【看空研究員】")
        lines.append(result["debate"]["bear"]["response"] or "(無回應)")

    lines.extend([
        "",
        f"⚖️ 【仲裁分析師】",
        result["debate"]["arbiter"]["response"] or "(無回應)",
        "",
        f"{'='*50}",
        f"  系統評分: {result['data'].get('score', 'N/A')}/10",
        f"{'='*50}",
    ])
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("用法: python investment_debate.py <symbol> [--json] [--rounds N]")
        return

    symbol = sys.argv[1]
    as_json = "--json" in sys.argv
    max_rounds = 1
    if "--rounds" in sys.argv:
        idx = sys.argv.index("--rounds")
        if idx + 1 < len(sys.argv):
            max_rounds = min(int(sys.argv[idx + 1]), 3)

    print(f"分析 {symbol} 中... (辯論 {max_rounds} 輪)")
    result = run_debate(symbol, max_rounds=max_rounds)

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(format_debate_report(result))

    # 存檔
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"debate_{symbol}_{datetime.now().strftime('%Y%m%d_%H%M')}.json")
    with open(out_path, "w") as f:
        json.dump(result, ensure_ascii=False, indent=2, default=str, fp=f)
    print(f"\n報告已存: {out_path}")


if __name__ == "__main__":
    main()
