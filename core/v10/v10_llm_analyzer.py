#!/usr/bin/env python3
"""
V10 LLM深度分析器 - 对V10候选股进行多维度定性分析

定位：质量把关层（非替代量化解）。量化解产出TOP3后，LLM做：
  1. 叙事分析：技术面+资金面的定性解读
  2. 红旗检测：量化解可能遗漏的风险
  3. 信心调整：对每只票输出 +10~-10 的调整分

调用 DeepSeek API (api.deepseek.com)，单次接口批量分析所有候选。

用法：
  python3 v10_llm_analyzer.py --input /path/to/candidates.json
  python3 v10_llm_analyzer.py --code 600203 --name 福日电子 --signal 全买入 --price 43.50 ...

也可作为模块导入：
  from v10_llm_analyzer import analyze_candidates
"""
import json, os, sys, time, urllib.request, urllib.error
from datetime import datetime

# DeepSeek API 配置
DEEPSEEK_BASE = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = os.environ.get("LLM_ANALYSIS_MODEL", "deepseek-v4-flash")
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
MAX_TOKENS = 2000
TIMEOUT = 20

# ── 提示词模板 ─────────────────────────────────────────────
SYSTEM_PROMPT = """你是A股短线交易分析专家。请对候选股做技术面+资金面定性分析。

**分析框架：**
1. 技术形态（V10信号+均线排列+量价配合）→ 多/空/中性评估
2. 资金博弈（主力净流入+内盘外盘比+换手率）→ 主力意图判断
3. 风险点（追高风险+振幅异常+板块拖累）→ 红旗/黄旗/绿旗
4. 综合信心 → +10到-10调整分

**评分原则：**
- +10：强烈看好，形态+资金面共振
- +5：偏好看，信号有效但有小瑕疵
- 0：中性，没有明显亮点也没有明显风险
- -5：偏谨慎，有值得注意的风险点
- -10：明确看空，存在重大红旗

**红旗规则（发现即扣分，但Vibe≥+2强趋势豁免）：**
- 尾盘急拉(14:50后拉升>3%) → -5
- 主力净流入为负且量能萎缩 → -3
- 距EMA20偏离>8%：
  - Vibe≥+2强 + V10全买入/强庄买 → 不扣分，强趋势完全豁免（趋势加速≠追高）
  - Vibe+1中 + 偏离>15% → -2，标注"等回调"
  - Vibe≤0 或 趋势无确认(缩量/板块退潮) → -3
- 高位放量滞涨(换手>10%但涨幅<2%) → -5

**输出格式：必须是合法JSON，不要添加```json```标记**
{
  "market_overview": "一句话大盘环境判断",
  "candidates": [
    {
      "code": "600203",
      "name": "福日电子",
      "technical_read": "技术面定性分析(1-2句)",
      "capital_read": "资金面定性分析(1-2句)",
      "risk_flags": ["红旗1", "黄旗1"],
      "confidence_adj": 5,
      "verdict": "看好/中性/谨慎/回避",
      "one_liner": "一句话结论(≤20字)"
    }
  ]
}"""


def build_candidate_context(candidates: list, market_overview: str = "") -> str:
    """构建发送给LLM的候选股上下文"""
    lines = []
    if market_overview:
        lines.append(f"## 大盘环境\n{market_overview}\n")
    lines.append("## 候选股清单")
    for i, c in enumerate(candidates, 1):
        lines.append(f"### {i}. {c.get('name','')}({c.get('code','')})")
        lines.append(f"- V10信号: {c.get('signal','')} | 量化评分: {c.get('score','N/A')}分")
        lines.append(f"- 现价: {c.get('price',0):.2f} | 涨幅: {c.get('change_pct',0):+.1f}%")
        kl = c.get('key_levels', {})
        if kl:
            lines.append(f"- EMA20: {kl.get('ema20','N/A')} | EMA60: {kl.get('ema60','N/A')} | EMA200: {kl.get('ema200','N/A')}")
        rt = c.get('real_time_quote', {})
        if rt:
            lines.append(f"- 量比: {rt.get('volume_ratio','N/A')} | 换手: {rt.get('turnover_rate','N/A')}%")
            lines.append(f"- 振幅: {rt.get('amplitude','N/A')}% | 内外盘比: {rt.get('buy_volume',0)/max(rt.get('sell_volume',1),1):.1f}" if rt.get('sell_volume', 0) > 0 else "")
            if rt.get('latest_change'):
                lines.append(f"- 日内走势: {rt['latest_change']}")
        cf = c.get('capital_flow', {})
        if cf:
            inflow = cf.get('value', cf.get('net_inflow', 0))
            lines.append(f"- 主力资金: {'净流入' if inflow > 0 else '净流出'} {abs(inflow):.0f}万")
        if c.get('sector'):
            lines.append(f"- 所属板块: {c['sector']}")
        details = c.get('details', {})
        if details:
            for dim, (sc, max_sc, desc) in details.items():
                lines.append(f"- {dim}: {sc}/{max_sc} ({desc})")
        lines.append("")
    return "\n".join(lines)


def call_deepseek(system_prompt: str, user_message: str) -> dict:
    """调用DeepSeek API，返回解析后的JSON"""
    if not DEEPSEEK_KEY:
        return {"error": "DEEPSEEK_API_KEY not set", "candidates": []}

    payload = json.dumps({
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.3,
        "max_tokens": MAX_TOKENS,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")

    req = urllib.request.Request(
        DEEPSEEK_BASE,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_KEY}",
        },
        method="POST"
    )

    content = None
    try:
        resp = urllib.request.urlopen(req, timeout=TIMEOUT)
        body = json.loads(resp.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        return json.loads(content)
    except (json.JSONDecodeError, KeyError) as e:
        return {"error": f"JSON/Key error: {e}", "raw": str(content)[:500] if content else "<no content>"}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        return {"error": f"HTTP {e.code}: {err_body[:200]}"}
    except Exception as e:
        return {"error": str(e)}


def analyze_candidates(candidates: list, market_overview: str = "") -> dict:
    """
    对候选股列表进行LLM深度分析。

    参数:
        candidates: [{
            "code": "600203",
            "name": "福日电子",
            "signal": "全买入",
            "score": 72,
            "price": 43.50,
            "change_pct": 2.3,
            "key_levels": {"ema20": 41.2, "ema60": 38.5, ...},
            "real_time_quote": {...},
            "capital_flow": {...},
            "sector": "消费电子",
            "details": {"V10信号": (30,30,"全买入"), ...}
        }, ...]
        market_overview: "上证+0.3% 创指-0.5% 两市缩量7000亿"

    返回:
        {
            "market_overview": "LLM对大盘的判断",
            "candidates": [
                {
                    "code": "600203",
                    "name": "福日电子",
                    "technical_read": "...",
                    "capital_read": "...",
                    "risk_flags": [...],
                    "confidence_adj": 5,
                    "verdict": "看好/中性/谨慎/回避",
                    "one_liner": "..."
                }, ...
            ],
            "error": null 或 错误信息
        }
    """
    if not candidates:
        return {"error": "no candidates", "candidates": []}

    user_msg = build_candidate_context(candidates, market_overview)
    print(f"🤖 LLM分析: {len(candidates)}只候选 | 模型: {DEEPSEEK_MODEL}", file=sys.stderr)

    result = call_deepseek(SYSTEM_PROMPT, user_msg)

    if "error" in result and result["error"]:
        # 降级：给所有候选0分调整
        print(f"⚠️ LLM分析失败，降级为0调整: {result['error']}", file=sys.stderr)
        return {
            "error": result["error"],
            "market_overview": market_overview,
            "candidates": [
                {
                    "code": c["code"],
                    "name": c.get("name", ""),
                    "technical_read": "LLM不可用，跳过分析",
                    "capital_read": "",
                    "risk_flags": [],
                    "confidence_adj": 0,
                    "verdict": "中性",
                    "one_liner": "LLM分析不可用"
                }
                for c in candidates
            ]
        }

    # 校验返回的候选数量
    llm_candidates = result.get("candidates", [])
    if len(llm_candidates) != len(candidates):
        print(f"⚠️ LLM返回候选数({len(llm_candidates)})与输入({len(candidates)})不匹配，部分结果可能缺失",
              file=sys.stderr)

    return result


def merge_with_quant(quant_results: list, llm_analysis: dict) -> list:
    """
    将LLM分析结果合并到量化评分中。

    返回增强后的候选列表，每项增加：
      - llm_verdict: 看好/中性/谨慎/回避
      - llm_confidence_adj: +10到-10
      - llm_risk_flags: 红旗列表
      - final_score: 量化分 + LLM调整
      - one_liner: LLM一句话结论
    """
    llm_map = {}
    for la in llm_analysis.get("candidates", []):
        llm_map[la["code"]] = la

    enhanced = []
    for qr in quant_results:
        code = qr.get("code", "")
        llm = llm_map.get(code, {})
        adj = llm.get("confidence_adj", 0)
        # 限定调整范围
        adj = max(-10, min(10, adj))

        enhanced.append({
            **qr,
            "llm_verdict": llm.get("verdict", "中性"),
            "llm_confidence_adj": adj,
            "llm_risk_flags": llm.get("risk_flags", []),
            "llm_technical_read": llm.get("technical_read", ""),
            "llm_capital_read": llm.get("capital_read", ""),
            "llm_one_liner": llm.get("one_liner", ""),
            "final_score": qr.get("score", 0) + adj,
        })

    # 按最终分重排
    enhanced.sort(key=lambda x: x["final_score"], reverse=True)
    return enhanced


def format_llm_analysis(enhanced: list) -> str:
    """将LLM增强结果格式化为Markdown报告"""
    lines = []
    lines.append("")
    lines.append("🤖 **LLM深度分析**")
    lines.append("")

    market = enhanced[0].get("_market_overview", "") if enhanced else ""
    if market:
        lines.append(f"📊 大盘: {market}")
        lines.append("")

    for i, e in enumerate(enhanced[:3], 1):
        verdict_emoji = {"看好": "🟢", "中性": "⚪", "谨慎": "🟡", "回避": "🔴"}.get(e.get("llm_verdict", ""), "⚪")
        adj = e.get("llm_confidence_adj", 0)
        adj_str = f"+{adj}" if adj > 0 else str(adj)

        lines.append(f"**{i}. {verdict_emoji} {e['name']}({e['code']})** | "
                     f"量化解{e.get('score',0)}分 + LLM调整{adj_str} = **{e.get('final_score',0)}分**")
        lines.append(f"> {e.get('llm_one_liner', '')}")
        lines.append("")

        if e.get("llm_technical_read"):
            lines.append(f"📈 技术面: {e['llm_technical_read']}")
        if e.get("llm_capital_read"):
            lines.append(f"💰 资金面: {e['llm_capital_read']}")

        flags = e.get("llm_risk_flags", [])
        if flags:
            lines.append(f"🚩 风险: {' | '.join(flags)}")
        lines.append("")

    return "\n".join(lines)


# ── CLI入口 ────────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser(description="V10 LLM深度分析器")
    parser.add_argument("--input", help="候选股JSON文件路径")
    parser.add_argument("--code", nargs="*", help="候选股代码列表")
    parser.add_argument("--name", nargs="*", help="候选股名称列表")
    parser.add_argument("--signal", nargs="*", help="V10信号等级")
    parser.add_argument("--price", nargs="*", type=float, help="现价")
    parser.add_argument("--change", nargs="*", type=float, help="涨幅")
    parser.add_argument("--score", nargs="*", type=int, help="量化评分")
    parser.add_argument("--market", default="", help="大盘环境描述")
    parser.add_argument("--output", help="输出JSON路径")
    parser.add_argument("--format", choices=["json", "markdown"], default="json", help="输出格式")
    args = parser.parse_args()

    candidates = []

    if args.input:
        with open(args.input) as f:
            data = json.load(f)
        # 支持两种格式：直接数组 或 {candidates: [...]}
        candidates = data if isinstance(data, list) else data.get("candidates", data.get("stocks", []))
    elif args.code:
        n = len(args.code)
        for i in range(n):
            c = {
                "code": args.code[i],
                "name": args.name[i] if args.name and i < len(args.name) else "",
                "signal": args.signal[i] if args.signal and i < len(args.signal) else "基础买",
                "price": args.price[i] if args.price and i < len(args.price) else 0,
                "change_pct": args.change[i] if args.change and i < len(args.change) else 0,
                "score": args.score[i] if args.score and i < len(args.score) else 0,
            }
            candidates.append(c)

    if not candidates:
        print("⛔ 无候选股数据。使用 --input 或 --code/--name 指定", file=sys.stderr)
        sys.exit(1)

    result = analyze_candidates(candidates, args.market)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"✅ 分析结果已写入 {args.output}")

    if args.format == "markdown":
        # 需要量化数据才能格式化
        quant = [
            {**c, "details": c.get("details", {})}
            for c in candidates
        ]
        enhanced = merge_with_quant(quant, result)
        print(format_llm_analysis(enhanced))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
