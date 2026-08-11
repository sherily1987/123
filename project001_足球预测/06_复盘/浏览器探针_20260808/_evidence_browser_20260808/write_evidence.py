# -*- coding: utf-8 -*-
from pathlib import Path
from datetime import datetime

ED = Path(r"C:/Users/Administrator/football-llm-predictor/data/evidence_2026-08-08")
ED.mkdir(parents=True, exist_ok=True)
OUT = Path(__file__).resolve().parent
OUT.mkdir(parents=True, exist_ok=True)

now = datetime.now().strftime("%Y-%m-%d %H:%M")
today = datetime.now().strftime("%Y-%m-%d")

def w(name: str, content: str) -> None:
    p = ED / name
    p.write_text(content, encoding="utf-8")
    print("wrote", p.name, len(content))

files = {}

files["evidence_004_前进之鹰_威廉二世.md"] = f"""# 证据: 前进之鹰 vs 威廉二世 (荷甲 2026-08-09 00:45)

> 采集时间: {now} | 销售日 2026-08-08 | 体彩 周六016 | 工具: Hermes browser + 官网/维基

## 1. 伤停/阵容
- 截至采集时点，未从俱乐部官网首页读到当场伤停名单/预计首发完整列表 | source(https://www.ga-eagles.nl/) | collected_at({today})
- 官网展示焦点球员/队长为 Joris Kramer（SELECTIE 轮播） | source(https://www.ga-eagles.nl/) | collected_at({today})
- 维基赛季页：Go Ahead Eagles 队长 Joris Kramer、主帅 Joseph Oosting；Willem II 队长 Jari Schuurman、主帅 John Stegeman | source(https://en.wikipedia.org/wiki/2026–27_Eredivisie) | collected_at({today})

## 2. 战意/动机
- 2026–27 荷甲 8月7日开赛；本场为揭幕轮窗口赛程（维基赛程表 GAE 主场对 Willem II 标注 8 Aug） | source(https://en.wikipedia.org/wiki/2026–27_Eredivisie) | collected_at({today})
- Willem II 上季荷乙第3，升班一年后重返顶级（promoted after a one-year absence） | source(同上 Team changes) | collected_at({today})
- Go Ahead Eagles 季前主帅更迭：Melvin Boel 2026-06-03 下课，Joseph Oosting 2026-06-11 上任 | source(同上 Managerial changes) | collected_at({today})
- 官网标注下一场：周六 08 AUG 18:45（当地）主场 vs Willem II，Matchday 杂志当晚发放 | source(https://www.ga-eagles.nl/) | collected_at({today})

## 3. 近况/状态
- Go Ahead Eagles 官宣热身赛客场 0-1 胜 Luton Town（2026-08-02） | source(https://www.ga-eagles.nl/ 新闻「Go Ahead Eagles wint oefenwedstrijd bij Luton Town: 0-1」) | collected_at({today})
- 联赛截至 2026-08-07：仅 Cambuur 0-4 Excelsior 完赛；GAE 与 Willem II 均为 0 场 0 分 | source(https://en.wikipedia.org/wiki/2026–27_Eredivisie) | collected_at({today})

## 4. 主客/旅行/天气
- 主队主场 De Adelaarshorst（Deventer），容量约 10,000 | source(维基 Stadiums and locations) | collected_at({today})
- 客队 Willem II 主场 Koning Willem II Stadion（Tilburg）约 15,220 | source(同上) | collected_at({today})
- 开球当地约 18:45（对应体彩北京时间 08-09 00:45） | source(ga-eagles.nl + 体彩 raw) | collected_at({today})

## 5. 赔率异动（体彩官方）
- 体彩 HAD: 主 1.44 / 平 4.15 / 客 5.15（市场明显倾向主胜） | source(sporttery raw 周六016) | collected_at({today})

## 6. 身份核验
- 前进之鹰 = Go Ahead Eagles（Deventer） | source(维基/ga-eagles.nl) | collected_at({today})
- 威廉二世 = Willem II Tilburg | source(维基/willem-ii.nl) | collected_at({today})

## 证据缺口
- 具体伤停球员名单未双源交叉确认
- 天气预报未拉
- 国际盘多家赔率未采
"""

files["evidence_006_埃因霍温_福图纳.md"] = f"""# 证据: 埃因霍温 vs 福图纳 (荷甲 2026-08-09 02:00)

> 采集时间: {now} | 销售日 2026-08-08 | 体彩 周六018 | 工具: Hermes browser + 维基

## 1. 伤停/阵容
- 未检索到当场官方伤停名单（PSV 英文 news 路径曾返回 404） | source(https://www.psv.nl/en/news) | collected_at({today})
- 维基：PSV 主帅 Peter Bosz，队长 Jerdy Schouten；Fortuna Sittard 主帅 Danny Buijs，队长 Ivo Pinto | source(https://en.wikipedia.org/wiki/2026–27_Eredivisie) | collected_at({today})

## 2. 战意/动机
- PSV 为三连冠卫冕冠军（three-time defending champions） | source(https://en.wikipedia.org/wiki/2026–27_Eredivisie) | collected_at({today})
- 赛程表标注 PSV 主场 vs Fortuna Sittard 为 8 Aug 场次（揭幕轮窗口） | source(同上 Results) | collected_at({today})
- 体彩本场未开售胜平负 HAD（odds_eligible=false） | source(sporttery raw 周六018) | collected_at({today})

## 3. 近况/状态
- 截至 2026-08-07 积分榜 PSV 与 Fortuna 均 0 场；联赛仅 1 场完赛（Cambuur 0-4 Excelsior） | source(维基) | collected_at({today})

## 4. 主客/旅行/天气
- PSV 主场 Philips Stadion（Eindhoven）约 35,000 | source(维基 Stadiums) | collected_at({today})
- Fortuna 主场 Fortuna Sittard Stadion 约 12,000 | source(同上) | collected_at({today})

## 5. 赔率异动
- 体彩无 HAD 可引用 | source(sporttery) | collected_at({today})

## 6. 身份核验
- 埃因霍温 = PSV Eindhoven | source(维基/psv.com) | collected_at({today})
- 福图纳 = Fortuna Sittard | source(维基) | collected_at({today})

## 证据缺口
- 伤停/预计首发双源缺失；无体彩胜平负；天气未采
"""

files["evidence_010_阿尔克马_海牙.md"] = f"""# 证据: 阿尔克马 vs 海牙 (荷甲 2026-08-09 03:00)

> 采集时间: {now} | 销售日 2026-08-08 | 体彩 周六022 | 工具: Hermes browser + 维基

## 1. 伤停/阵容
- 未拿到当场伤停名单 | source(local) | collected_at({today})
- 维基：AZ 主帅 Lee-Roy Echteld（interim 代理），队长 Jordy Clasie；ADO Den Haag 主帅 Robin Peter，队长 Juho Kilo | source(https://en.wikipedia.org/wiki/2026–27_Eredivisie) | collected_at({today})

## 2. 战意/动机
- ADO Den Haag 时隔五年重返荷甲（promoted after a five-year absence，上季荷乙第1） | source(维基 Team changes) | collected_at({today})
- AZ 上季联赛第7；赛程表标注 AZ 主场 vs ADO 为 8 Aug | source(维基 Results) | collected_at({today})
- AZ 以代理主帅开局 | source(维基 Personnel) | collected_at({today})

## 3. 近况/状态
- 双方联赛截至 8/7 均为 0 场；揭幕轮阶段 | source(维基积分榜) | collected_at({today})

## 4. 主客/旅行/天气
- AZ 主场 AFAS Stadion（Alkmaar）约 19,478 | source(维基 Stadiums) | collected_at({today})
- ADO 主场 Werktalent Stadion（The Hague）约 15,000 | source(同上) | collected_at({today})

## 5. 赔率异动（体彩官方）
- 体彩 HAD: 主 1.28 / 平 4.9 / 客 6.95（极强主胜定价） | source(sporttery raw 周六022) | collected_at({today})

## 6. 身份核验
- 阿尔克马 = AZ Alkmaar | source(维基/az.nl) | collected_at({today})
- 海牙 = ADO Den Haag | source(维基 Team changes) | collected_at({today})

## 证据缺口
- 伤停名单双源缺失；天气/国际盘未采
"""

files["evidence_005_吉马良斯_阿罗卡.md"] = f"""# 证据: 吉马良斯 vs 阿罗卡 (葡超 2026-08-09 01:00)

> 采集时间: {now} | 销售日 2026-08-08 | 体彩 周六017 | 工具: 维基 2026–27 Primeira Liga

## 1. 伤停/阵容
- 未检索到当场伤停/预计首发双源 | source(local) | collected_at({today})
- Vitória de Guimarães 现任主帅 Tiago Margarido（2026-06-24 上任；前任 Gil Lameiras 降级 B 队） | source(https://en.wikipedia.org/wiki/2026–27_Primeira_Liga) | collected_at({today})

## 2. 战意/动机
- 上季联赛名次：Guimarães 第9；Arouca 第8 | source(维基 stadiums 表 2025–26 position) | collected_at({today})
- 新帅上任后的联赛初期场次 | source(维基 managerial) | collected_at({today})

## 3. 近况/状态
- 积分榜更新至 2026-08-07：多数球队 0 场（赛季初） | source(维基 standings) | collected_at({today})

## 4. 主客/旅行/天气
- Guimarães 主场 Estádio D. Afonso Henriques 约 30,029 | source(维基) | collected_at({today})
- Arouca 主场 Estádio Municipal de Arouca 约 5,000 | source(维基) | collected_at({today})

## 5. 赔率异动（体彩官方）
- 体彩 HAD: 主 1.75 / 平 3.35 / 客 3.85 | source(sporttery raw 周六017) | collected_at({today})

## 6. 身份核验
- 吉马良斯 = Vitória S.C. / Vitória de Guimarães | source(维基) | collected_at({today})
- 阿罗卡 = F.C. Arouca | source(维基) | collected_at({today})

## 证据缺口
- 伤停/近5场具体比分未交叉验证；天气/国际盘未采
"""

files["evidence_012_阿马多拉_里斯本.md"] = f"""# 证据: 阿马多拉 vs 里斯本 (葡超 2026-08-09 03:30)

> 采集时间: {now} | 销售日 2026-08-08 | 体彩 周六024 | 工具: 维基 2026–27 Primeira Liga

## 1. 伤停/阵容
- 未拿到当场伤停名单 | source(local) | collected_at({today})
- Benfica：2026-06-09 José Mourinho 离任加盟皇马，同日 Marco Silva 上任 | source(维基 Managerial changes) | collected_at({today})
- Estrela Amadora：Cristiano Bacci 于 2026-06-12 离任（estrelamadora.pt 引用） | source(维基 managerial) | collected_at({today})

## 2. 战意/动机
- 上季：Estrela da Amadora 第15；Benfica 第3 | source(维基 stadiums 表) | collected_at({today})
- 体彩本场无 HAD（强弱悬殊常见） | source(sporttery raw) | collected_at({today})

## 3. 近况/状态
- 联赛截至 8/7 多为 0 场开局 | source(维基 standings) | collected_at({today})

## 4. 主客/旅行/天气
- Estrela Amadora 主场 Estádio José Gomes 约 9,288 | source(维基) | collected_at({today})
- Benfica 主场 Estádio da Luz 约 68,100 | source(维基) | collected_at({today})

## 5. 赔率异动
- 体彩无 HAD；让球盘以 raw.json HHAD 为准 | source(sporttery) | collected_at({today})

## 6. 身份核验
- 阿马多拉 = C.F. Estrela da Amadora | source(维基) | collected_at({today})
- 里斯本（本场客队）= S.L. Benfica（勿与 Sporting CP 混淆） | source(维基) | collected_at({today})

## 证据缺口
- 伤停双源、首发、国际盘均缺
"""

files["evidence_011_格雷米奥_圣保罗.md"] = f"""# 证据: 格雷米奥 vs 圣保罗 (巴甲 2026-08-09 03:00)

> 采集时间: {now} | 销售日 2026-08-08 | 体彩 周六023 | 工具: 维基 2026 Série A

## 1. 伤停/阵容
- 未检索到本场官方伤停名单 | source(local) | collected_at({today})

## 2. 战意/动机
- 2026 巴甲进行中（维基统计更新至 2026-07-30） | source(https://en.wikipedia.org/wiki/2026_Campeonato_Brasileiro_Série_A) | collected_at({today})
- 赛季高比分纪录含 Grêmio 5–3 Botafogo（2026-02-04） | source(同上) | collected_at({today})

## 3. 近况/状态
- 射手榜示例：Pedro 与 Kevin Viveros 各 12 球（截至条目更新） | source(同上) | collected_at({today})
- 具体两队近5场 W/D/L 未第二源交叉 | source(local) | collected_at({today})

## 4. 主客/旅行/天气
- 主队 Grêmio（Porto Alegre）主场对阵 São Paulo FC | source(维基/体彩) | collected_at({today})
- 天气未采

## 5. 赔率异动（体彩官方）
- 体彩 HAD: 主 2.30 / 平 2.75 / 客 3.02 | source(sporttery raw 周六023) | collected_at({today})

## 6. 身份核验
- 格雷米奥 = Grêmio FBPA；圣保罗 = São Paulo FC | source(维基) | collected_at({today})

## 证据缺口
- 伤停/首发、近5场、天气、国际盘
"""

files["evidence_013_博塔弗戈_弗鲁米嫩.md"] = f"""# 证据: 博塔弗戈 vs 弗鲁米嫩 (巴甲 2026-08-09 08:00)

> 采集时间: {now} | 销售日 2026-08-08 | 体彩 周六025 | 工具: 维基 2026 Série A

## 1. 伤停/阵容
- 未检索到本场伤停名单 | source(local) | collected_at({today})

## 2. 战意/动机
- 里约德比（Botafogo vs Fluminense 同城） | source(维基 teams by state) | collected_at({today})
- 赛季已有 Botafogo 4–0 Cruzeiro（1月29日）；亦有 Grêmio 5–3 Botafogo（2月4日） | source(维基) | collected_at({today})

## 3. 近况/状态
- 联赛进行至 7 月底统计口径；具体近5场未双源交叉 | source(维基 updated 30 July 2026) | collected_at({today})

## 4. 主客/旅行/天气
- 同城德比，旅行负担小 | source(维基) | collected_at({today})
- 天气未采

## 5. 赔率异动（体彩官方）
- 体彩 HAD: 主 2.35 / 平 3.00 / 客 2.70 | source(sporttery raw 周六025) | collected_at({today})

## 6. 身份核验
- 博塔弗戈 = Botafogo FR；弗鲁米嫩 = Fluminense FC | source(维基) | collected_at({today})

## 证据缺口
- 伤停/首发/近5场/天气/国际盘
"""

files["evidence_003_雅罗_瓦萨.md"] = f"""# 证据: 雅罗 vs 瓦萨 (芬超 2026-08-09 00:00)

> 采集时间: {now} | 销售日 2026-08-08 | 体彩 周六015 | 工具: 体彩 + 搜索（Bing RSS 污染）

## 1. 伤停/阵容
- Bing RSS 查询被游戏/无关结果污染，未获得可用伤停新闻 | source(bing RSS) | collected_at({today})

## 2. 战意/动机
- 芬超常规联赛场次；具体名次本轮未深挖 | source(local) | collected_at({today})

## 3. 近况/状态
- 未完成近5场交叉验证 | source(local) | collected_at({today})

## 4. 主客/旅行/天气
- 主队雅罗（FF Jaro）主场 | source(体彩) | collected_at({today})
- 天气未采

## 5. 赔率异动（体彩官方）
- 体彩 HAD: 主 4.00 / 平 3.55 / 客 1.68（市场明显倾向客胜） | source(sporttery raw 周六015) | collected_at({today})

## 6. 身份核验
- 雅罗 = FF Jaro；瓦萨 = VPS Vaasa | source(体彩译名常规对应) | collected_at({today})

## 证据缺口
- 伤停、近况、天气、国际盘均不足；主要依赖体彩盘口结构
"""

for name, content in files.items():
    w(name, content)

rep = OUT / "EVIDENCE_UPDATE_REPORT.md"
rep.write_text(
    f"""# Browser 证据补强报告 {today}

## 方法
- 主工具：**Hermes 内置 browser_navigate / browser_console**（非 agent-browser / dev-browser CLI）
- 辅源：俱乐部官网 curl、维基赛季页

## 抓到的硬事实
1. 荷甲 2026–27 已于 8/7 开赛；PSV 三连冠卫冕；升班马 ADO / Cambuur / Willem II
2. 周六016 GAE–Willem II：官网确认当地 8/8 18:45 主场；热身胜 Luton 0-1；Oosting 新帅
3. 周六022 AZ–ADO：ADO 五年升级；AZ 代理主帅；体彩主胜 1.28
4. 周六018 PSV–Fortuna：Bosz 卫冕冠军；体彩无 HAD
5. 葡超：Guimarães 新帅 Margarido；Benfica Mourinho→Silva；Estrela Bacci 离任
6. 巴甲：赛季中后段；里约德比等背景

## 仍缺
- 多数场次具体伤停球员名单
- 法乙三场未深挖
- 芬超几乎只有盘口

## 已更新文件
"""
    + "\n".join(f"- {n}" for n in files)
    + """

## 结论
以前 curl 抓不到的荷甲结构/官网赛程，用 **browser + 维基** 已能补上战意/身份/主帅/主场层；**伤停名单层仍难**，需赛前官方大名单。
""",
    encoding="utf-8",
)
print("report", rep)
print("total evidence md", len(list(ED.glob("evidence_*.md"))))
