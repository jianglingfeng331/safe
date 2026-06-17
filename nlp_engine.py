"""
NLP 规则引擎 —— 纯正则 + 关键词匹配，零外部依赖（除 jieba 分词辅助）。
核心思路：判断用户意图 → 提取抽屉/物品/期限。
"""

import re
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import jieba


# ── 意图判断 ──────────────────────────────────────────

# 登记类关键词
RECORD_PATTERNS = [
    re.compile(r"(放|存|收|登记)(到|在|入|进)"),
    re.compile(r"(在|放|存).*(里|里面|里边|中)"),
    re.compile(r"(有|买了|新买了|刚买).*放"),
    re.compile(r"记(一下|一笔|录)"),
    re.compile(r"保质期"),
]

# 查询类关键词
QUERY_PATTERNS = [
    re.compile(r"(在哪|哪里|什么地方|哪个位置)"),
    re.compile(r"(有没有|有没|有不有|是否有)"),
    re.compile(r"(有什么|有啥|有哪些|什么东西)"),
    re.compile(r"(找|查|搜)(一下|找|寻)"),
]

# 删除/移动类
DELETE_PATTERNS = [
    re.compile(r"(扔了|丢了|没了|不要了|处理了|吃完|用完|过期)"),
    re.compile(r"(删|去掉|清除|移除)"),
]

MOVE_PATTERNS = [
    re.compile(r"(移到|搬到|挪到|改放|换到|移到)"),
]


def classify_intent(text: str) -> str:
    """返回: record | query | delete | move | unknown"""
    # 先判断移动（含位置变更）
    for p in MOVE_PATTERNS:
        if p.search(text):
            return "move"
    # 再判断删除
    for p in DELETE_PATTERNS:
        if p.search(text):
            return "delete"
    # 查询优先判断（问句特征）
    if text.endswith("?") or text.endswith("？") or text.endswith("吗"):
        return "query"
    for p in QUERY_PATTERNS:
        if p.search(text):
            return "query"
    # 登记
    for p in RECORD_PATTERNS:
        if p.search(text):
            return "record"
    # 兜底：有位置词+物品词 → 登记；否则查询
    if _has_location_word(text) and _has_item_word(text):
        return "record"
    return "query"


# ── 位置词 & 物品词词典 ──────────────────────────────

LOCATION_KEYWORDS = [
    "抽屉", "柜子", "柜", "隔层", "箱子", "盒", "盒子", "药箱",
    "衣柜", "床头柜", "书柜", "鞋柜", "储物间", "储藏室", "阳台",
    "阁楼", "地下室", "车库", "次卧", "主卧", "客厅", "厨房", "卫生间",
    "冰箱", "冷冻", "冷藏", "架子", "层", "房间", "书房", "杂物间",
]

ITEM_INDICATORS = [
    "枕头", "被子", "床单", "被套", "套", "药品", "药", "工具",
    "螺丝刀", "扳手", "胶带", "剪刀", "充电器", "数据线", "遥控器",
    "说明书", "发票", "证件", "卡", "钥匙", "电池", "灯泡", "针线",
    "头孢", "感冒", "退烧", "消炎", "止痛", "创可贴", "棉签",
    "书", "本", "笔", "文具", "玩具", "装饰", "摆件", "相框",
    "行李箱", "背包", "袋子", "收纳", "盒子", "密封", "罐", "瓶",
]


def _has_location_word(text: str) -> bool:
    for kw in LOCATION_KEYWORDS:
        if kw in text:
            return True
    return False


def _has_item_word(text: str) -> bool:
    for kw in ITEM_INDICATORS:
        if kw in text:
            return True
    # 分词兜底：名词短语
    words = jieba.lcut(text)
    return len([w for w in words if len(w) >= 2]) >= 2


# ── 信息提取 ──────────────────────────────────────────

def extract_record(text: str) -> dict:
    """从登记语句中提取 { drawer, item, expiry }"""
    result = {"drawer": "", "item": "", "expiry": None}

    # Step 1: 提取期限/保质期
    result["expiry"] = _extract_expiry(text)
    # 去掉期限相关片段，减少干扰
    text_clean = _remove_expiry_text(text)

    # Step 2: 提取抽屉（位置词 + 前后修饰）
    result["drawer"] = _extract_drawer(text_clean)

    # Step 3: 提取物品（剩余部分中识别）
    result["item"] = _extract_item(text_clean, result["drawer"])

    return result


def extract_query(text: str) -> dict:
    """从查询语句中提取 { query_type, drawer, item }"""
    result = {"query_type": "find_item", "drawer": "", "item": ""}

    # 「XX在哪」→ 只查物品
    if re.search(r"(在哪|哪里|什么地方)", text):
        result["query_type"] = "find_item"
        result["item"] = _extract_item(text, "")

    # 「XX里有没有YY」→ 查物品在抽屉
    elif re.search(r"(有没有|有不有|有没|是否有)", text):
        result["query_type"] = "check_in_drawer"
        result["drawer"] = _extract_drawer(text)
        result["item"] = _extract_item(text, result["drawer"])

    # 「XX里有什么」→ 列抽屉
    elif re.search(r"(有什么|有啥|有哪些)", text):
        result["query_type"] = "list_drawer"
        result["drawer"] = _extract_drawer(text)

    # 默认：全文搜索
    else:
        result["query_type"] = "search"
        result["item"] = text.strip()

    return result


def extract_move(text: str) -> dict:
    """从移动语句中提取 { item, new_drawer }"""
    result = {"item": "", "new_drawer": ""}
    # 移到XX
    m = re.search(r"(移到|搬到|挪到|改放|换到)(.+)", text)
    if m:
        result["new_drawer"] = _extract_drawer(m.group(2))
    result["item"] = _extract_item(text, result["new_drawer"])
    return result


def extract_delete(text: str) -> dict:
    """从删除语句中提取 { item }"""
    return {"item": _extract_item(text, "")}


# ── 提取辅助函数 ──────────────────────────────────────

def _extract_drawer(text: str) -> str:
    """从文本中提取抽屉/位置名"""
    # 模式0: 「XX里放了」「XX里有」「XX放了」→ XX 是抽屉（最高优先级）
    m = re.search(r"^(.{1,15}?)(?:里放了|里有|里面放了|里面存了|放了|存了|里有|里存了)", text)
    if m:
        candidate = m.group(1).strip()
        if candidate and _has_location_word(candidate):
            return candidate

    # 模式1: 「在/放 + 位置词相关短语」
    m = re.search(r"(?:在|放|存|收|到|进)(.{1,15}?)(?:里|里面|中|的|了|，|。|$)", text)
    if m:
        candidate = m.group(1).strip()
        if candidate and _has_location_word(candidate):
            return candidate

    # 模式2: 直接匹配位置关键词，往前取修饰往后截到分隔词
    for kw in sorted(LOCATION_KEYWORDS, key=lambda x: -len(x)):
        idx = text.find(kw)
        if idx >= 0:
            start = max(0, idx - 6)
            # 往后截到第一个分隔词（里/放/存/了/的/，/。）
            end = idx + len(kw)
            tail = text[end:]
            sep = re.search(r"[里放存了的，。\s]", tail)
            if sep:
                end += sep.start()
            else:
                end = min(len(text), end + 6)
            segment = text[start:end]
            # 只清理首尾的分隔符
            cleaned = segment.strip("的放了在到进里中，。 ")
            if cleaned:
                return cleaned

    # 模式3: 「XX放了」→ XX 是抽屉（兜底）
    m = re.search(r"^(.{1,12}?)(?:放|存|里|里面)", text)
    if m and m.group(1).strip():
        return m.group(1).strip()

    return ""


def _extract_item(text: str, drawer: str) -> str:
    """从文本中提取物品名（排除抽屉名）"""
    # 去掉抽屉名
    remaining = text.replace(drawer, " ") if drawer else text

    # 去掉常见动词/介词
    for word in ["放了", "放在", "存了", "存在", "登记", "记录", "记一下",
                 "里面有", "里有", "里面有", "有个", "买了", "新买了",
                 "里", "的", "在", "有", "到", "了", "没", "不"]:
        remaining = remaining.replace(word, " ")

    # 提取名词短语（jieba 分词取名词）
    words = list(jieba.cut(remaining))
    # 过滤单字和纯标点
    meaningful = [w.strip() for w in words if len(w.strip()) >= 2]
    if meaningful:
        return "".join(meaningful[:4])  # 取前4个词拼接

    return remaining.strip(" ，。！？、 ")[:30]


def _extract_expiry(text: str) -> str | None:
    """提取保质期/期限，返回 YYYY-MM-DD 格式字符串或 None"""
    # 模式1: 「保质期到2027年3月」
    m = re.search(r"(?:保质期|有效期|过期|到期)[^\d]*(\d{4})\s*[年./-]\s*(\d{1,2})", text)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        return f"{year:04d}-{month:02d}-01"

    # 模式2: 独立日期 2027-03-15 或 2027/03/15
    m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            d = datetime(year, month, day)
            return d.strftime("%Y-%m-%d")
        except ValueError:
            return None

    # 模式3: 「明年3月」「下个月」「半年后」
    now = datetime.now()
    m = re.search(r"(明年)(\d{1,2})月", text)
    if m:
        return f"{now.year + 1:04d}-{int(m.group(2)):02d}-01"

    m = re.search(r"(下个月)", text)
    if m:
        d = now + relativedelta(months=1)
        return d.strftime("%Y-%m-01")

    m = re.search(r"(\d+)个?月后", text)
    if m:
        d = now + relativedelta(months=int(m.group(1)))
        return d.strftime("%Y-%m-%d")

    m = re.search(r"(半年后)", text)
    if m:
        d = now + relativedelta(months=6)
        return d.strftime("%Y-%m-%d")

    return None


def _remove_expiry_text(text: str) -> str:
    """去除期限相关文本片段"""
    expiry_phrases = [
        r"保质期[^\d]*\d{4}\s*[年./-]\s*\d{1,2}[月日]?[^\d]*",
        r"有效期[^\d]*\d{4}\s*[年./-]\s*\d{1,2}[月日]?[^\d]*",
        r"过期[^\d]*\d{4}\s*[年./-]\s*\d{1,2}[月日]?[^\d]*",
        r"到期[^\d]*\d{4}\s*[年./-]\s*\d{1,2}[月日]?[^\d]*",
        r"\d{4}[-/]\d{1,2}[-/]\d{1,2}",
        r"(明年|下个月|半年后|\d+个?月后)",
    ]
    for pat in expiry_phrases:
        text = re.sub(pat, "", text)
    return text.strip()


# ── 过期检查 ──────────────────────────────────────────

def check_expiring(days: int = 90) -> list[dict]:
    """返回未来 days 天内过期的物品列表"""
    from db import list_all
    now = datetime.now()
    deadline = now + timedelta(days=days)
    items = list_all(limit=9999)
    result = []
    for item in items:
        if item.get("expiry"):
            try:
                exp = datetime.strptime(item["expiry"], "%Y-%m-%d")
                if now <= exp <= deadline:
                    result.append(item)
            except ValueError:
                pass
    return result


# ── 自动判断入口 ──────────────────────────────────────

def parse(text: str) -> dict:
    """统一入口：根据意图分类 + 信息提取，返回结构化结果"""
    intent = classify_intent(text)
    result = {"intent": intent}

    if intent == "record":
        info = extract_record(text)
        result.update(info)
    elif intent == "query":
        info = extract_query(text)
        result.update(info)
    elif intent == "move":
        info = extract_move(text)
        result.update(info)
    elif intent == "delete":
        info = extract_delete(text)
        result.update(info)

    return result
