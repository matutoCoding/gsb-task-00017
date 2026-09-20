#!/usr/bin/env python3
"""标签段落库与拼版服务 — 仅依赖 Python 标准库。"""
import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(BASE, "web")
DB_FILE = os.path.join(BASE, "data", "db.json")

_LOCK = threading.RLock()

# 市场规则：配料排序 / 过敏原呈现方式
MARKET_RULES = {
    "CN": {"name": "中国大陆", "lang": "zh", "ingredient_order": "desc",
           "allergen_style": "parentheses",
           "allergen_note": "过敏原用括号标注，如：燕麦片（含麸质谷物）"},
    "EU": {"name": "欧盟", "lang": "en", "ingredient_order": "desc",
           "allergen_style": "bold",
           "allergen_note": "Reg.(EU)1169/2011：配料按重量降序，过敏原加粗"},
    "US": {"name": "美国", "lang": "en", "ingredient_order": "desc",
           "allergen_style": "contains",
           "allergen_note": "FALCPA：配料按重量降序，过敏原以 Contains 声明列出"},
}

TYPE_ORDER = ["product_name", "ingredients", "allergen", "origin",
              "storage", "manufacturer", "claim", "warning", "other"]
TYPE_LABELS = {
    "product_name": "产品名称", "ingredients": "配料表", "allergen": "过敏原声明",
    "origin": "原产地", "storage": "储存条件", "manufacturer": "生产商信息",
    "claim": "声称/声明", "warning": "警示语", "other": "其他",
}
REQUIRED_TYPES = ["product_name", "ingredients", "storage", "manufacturer"]
MULTI_TYPES = {"warning", "claim", "other"}


def normalize_map(raw):
    """segment_map 的值允许 sid 或 [sid...]，统一为标准结构。"""
    out = {}
    for stype, val in (raw or {}).items():
        if isinstance(val, list):
            out[stype] = val
        elif val:
            out[stype] = [val] if stype in MULTI_TYPES else val
    return out


def label_uses(label, sid):
    for val in label["segment_map"].values():
        if isinstance(val, list):
            if sid in val:
                return True
        elif val == sid:
            return True
    return False


def label_picked_types(label):
    return set(label["segment_map"].keys())

# 过敏原词库：key -> {市场: 展示词}
ALLERGENS = {
    "gluten": {"CN": "含麸质的谷物", "EU": "gluten", "US": "wheat/gluten"},
    "nut": {"CN": "坚果", "EU": "nuts", "US": "tree nuts"},
    "peanut": {"CN": "花生", "EU": "peanuts", "US": "peanuts"},
    "milk": {"CN": "乳", "EU": "milk", "US": "milk"},
    "soy": {"CN": "大豆", "EU": "soy", "US": "soy"},
}


def seed_db():
    now = int(time.time())
    segments = [
        dict(sid="S-PN-MUESLI", type="product_name", title="什锦燕麦片 品名",
             countries=["CN"], categories=["麦片"], specs=[],
             products=["P1", "P3"], text="什锦燕麦片",
             lang="zh", status="final", mutex_group=None,
             version=1, created_at=now - 30 * 86400, updated_at=now - 5 * 86400),
        dict(sid="S-ING-MUESLI", type="ingredients", title="什锦燕麦片 配料",
             countries=["CN"], categories=["麦片"], specs=[],
             products=["P1", "P3"],
             text="燕麦片（含麸质谷物）、扁桃仁（坚果）、全脂乳粉（乳）、白砂糖、食用盐",
             ingredients=[
                 {"name": "燕麦片", "pct": 55, "allergens": ["gluten"]},
                 {"name": "扁桃仁", "pct": 18, "allergens": ["nut"]},
                 {"name": "全脂乳粉", "pct": 12, "allergens": ["milk"]},
                 {"name": "白砂糖", "pct": 14, "allergens": []},
                 {"name": "食用盐", "pct": 1, "allergens": []}],
             lang="zh", status="final", mutex_group=None,
             version=1, created_at=now - 30 * 86400, updated_at=now - 5 * 86400),
        dict(sid="S-WARN-NUT-CN", type="warning", title="坚果过敏警示(中)",
             countries=["CN"], categories=[], specs=[],
             products=["P1", "P3"],
             text="本品含有坚果，对此过敏者请勿食用。生产线同时加工花生制品。",
             lang="zh", status="final", mutex_group="nut_warning",
             allergens=["nut", "peanut"],
             version=1, created_at=now - 20 * 86400, updated_at=now - 5 * 86400),
        dict(sid="S-WARN-PEANUT-CN", type="warning", title="花生过敏警示(中)",
             countries=["CN"], categories=[], specs=[],
             products=[],
             text="本品含有花生，花生过敏者严禁食用。",
             lang="zh", status="final", mutex_group="peanut_warning",
             allergens=["peanut"],
             version=1, created_at=now - 20 * 86400, updated_at=now - 2 * 86400),
        dict(sid="S-WARN-NUT-CN-STRICT", type="warning", title="坚果过敏严禁(中·旧口径)",
             countries=["CN"], categories=[], specs=[],
             products=["P1", "P3"],
             text="本品含有坚果，坚果过敏者严禁食用。",
             lang="zh", status="final", mutex_group="strict_warning",
             allergens=["nut"],
             version=1, created_at=now - 40 * 86400, updated_at=now - 40 * 86400),
        dict(sid="S-WARN-MILK-US", type="allergen", title="FALCPA Contains 声明",
             countries=["US"], categories=[], specs=[],
             products=["P1", "P2"],
             text="Contains: Wheat, Tree Nuts, Milk.",
             lang="en", status="final", mutex_group=None,
             allergens=["gluten", "nut", "milk"],
             version=1, created_at=now - 25 * 86400, updated_at=now - 25 * 86400),
        dict(sid="S-WARN-NUT-CN-2027", type="warning", title="坚果过敏警示(2027新规草案)",
             countries=["CN"], categories=[], specs=[],
             products=["P1", "P3"],
             text="本品含坚果及花生，对坚果或花生过敏者禁止食用。（依据2027标识新规草案）",
             lang="zh", status="draft", mutex_group="nut_warning_v2",
             allergens=["nut", "peanut"],
             version=1, created_at=now - 86400, updated_at=now - 86400),
        dict(sid="S-ORIGIN-CN", type="origin", title="原产地：中国",
             countries=["CN"], categories=[], specs=[],
             products=["P1", "P2", "P3"], text="原产地：中国河北",
             lang="zh", status="final", mutex_group=None,
             version=1, created_at=now - 30 * 86400, updated_at=now - 10 * 86400),
        dict(sid="S-STORE-DRY", type="storage", title="阴凉干燥储存",
             countries=[], categories=[], specs=[],
             products=["P1", "P2", "P3"],
             text="置于阴凉干燥处，避免阳光直射。开封后请密封并尽快食用。",
             lang="zh", status="final", mutex_group=None,
             version=1, created_at=now - 30 * 86400, updated_at=now - 10 * 86400),
        dict(sid="S-MFR-CN", type="manufacturer", title="生产商信息(华北)",
             countries=["CN"], categories=[], specs=[],
             products=["P1", "P3"],
             text="生产商：华北谷物食品有限公司；地址：河北省石家庄市工业园8号；电话：0311-88888888",
             lang="zh", status="final", mutex_group=None,
             version=1, created_at=now - 30 * 86400, updated_at=now - 10 * 86400),
        dict(sid="S-PN-MUESLI-EU", type="product_name", title="Muesli Product Name",
             countries=["EU", "US"], categories=["cereal"], specs=[],
             products=["P1"], text="Classic Muesli",
             lang="en", status="final", mutex_group=None,
             version=1, created_at=now - 25 * 86400, updated_at=now - 5 * 86400),
        dict(sid="S-ING-MUESLI-EU", type="ingredients", title="Muesli Ingredients",
             countries=["EU", "US"], categories=["cereal"], specs=[],
             products=["P1"],
             text="oat flakes 55%, sugar 14%, almonds 18%, whole milk powder 12%, salt",
             ingredients=[
                 {"name": "oat flakes", "pct": 55, "allergens": ["gluten"]},
                 {"name": "sugar", "pct": 14, "allergens": []},
                 {"name": "almonds", "pct": 18, "allergens": ["nut"]},
                 {"name": "whole milk powder", "pct": 12, "allergens": ["milk"]},
                 {"name": "salt", "pct": None, "allergens": []}],
             lang="en", status="final", mutex_group=None,
             version=1, created_at=now - 25 * 86400, updated_at=now - 5 * 86400),
        dict(sid="S-WARN-NUT-EU", type="warning", title="Nut Warning EN",
             countries=["EU", "US"], categories=[], specs=[],
             products=["P1"],
             text="May contain traces of peanuts. Contains nuts and milk.",
             lang="en", status="final", mutex_group="nut_warning",
             allergens=["nut", "milk", "peanut"],
             version=1, created_at=now - 25 * 86400, updated_at=now - 5 * 86400),
        dict(sid="S-ORIGIN-EU", type="origin", title="Origin CN (EN)",
             countries=["EU", "US"], categories=[], specs=[],
             products=["P1"], text="Origin: China",
             lang="en", status="final", mutex_group=None,
             version=1, created_at=now - 25 * 86400, updated_at=now - 5 * 86400),
        dict(sid="S-MFR-EU", type="manufacturer", title="Manufacturer EN",
             countries=["EU", "US"], categories=[], specs=[],
             products=["P1"],
             text="Manufactured for: Global Foods Trading GmbH, Hamburg, Germany",
             lang="en", status="final", mutex_group=None,
             version=1, created_at=now - 25 * 86400, updated_at=now - 5 * 86400),
        dict(sid="S-CLAIM-NONGMO", type="claim", title="非转基因声明(中)",
             countries=["CN"], categories=[], specs=[],
             products=["P1", "P3"], text="本产品未使用转基因原料。",
             lang="zh", status="final", mutex_group="gmo_claim",
             version=1, created_at=now - 15 * 86400, updated_at=now - 15 * 86400),
        dict(sid="S-CLAIM-GMO", type="claim", title="含转基因原料声明(中)",
             countries=["CN"], categories=[], specs=[],
             products=[], text="本产品加工原料中有转基因大豆。",
             lang="zh", status="final", mutex_group="gmo_claim",
             version=1, created_at=now - 15 * 86400, updated_at=now - 15 * 86400),
    ]

    products = [
        dict(pid="P1", name="经典什锦燕麦片", category="麦片", spec="500g 袋装",
             category_en="cereal", spec_en="500g bag",
             printed_qty=120000, intransit_qty=35000, unit_cost=0.12),
        dict(pid="P2", name="原味纯燕麦片", category="麦片", spec="1kg 袋装",
             category_en="cereal", spec_en="1kg bag",
             printed_qty=80000, intransit_qty=12000, unit_cost=0.18),
        dict(pid="P3", name="坚果燕麦片(家庭装)", category="麦片", spec="800g 盒装",
             category_en="cereal", spec_en="800g box",
             printed_qty=46000, intransit_qty=9000, unit_cost=0.21),
    ]

    labels = [
        dict(lid="L1", product_id="P1", country="CN",
             segment_map={"product_name": "S-PN-MUESLI", "ingredients": "S-ING-MUESLI",
                          "warning": "S-WARN-NUT-CN", "origin": "S-ORIGIN-CN",
                          "storage": "S-STORE-DRY", "manufacturer": "S-MFR-CN",
                          "claim": "S-CLAIM-NONGMO"},
             versions={"S-ING-MUESLI": 1, "S-WARN-NUT-CN": 1},
             status="final",
             rendered=[],
             created_at=now - 4 * 86400, updated_at=now - 4 * 86400),
        dict(lid="L2", product_id="P1", country="EU",
             segment_map={"product_name": "S-PN-MUESLI-EU", "ingredients": "S-ING-MUESLI-EU",
                          "warning": "S-WARN-NUT-EU", "origin": "S-ORIGIN-EU",
                          "storage": "S-STORE-DRY", "manufacturer": "S-MFR-EU"},
             versions={"S-ING-MUESLI-EU": 1, "S-WARN-NUT-EU": 1},
             status="final",
             rendered=[],
             created_at=now - 3 * 86400, updated_at=now - 3 * 86400),
        dict(lid="L4", product_id="P3", country="CN",
             segment_map={"product_name": "S-PN-MUESLI", "ingredients": "S-ING-MUESLI",
                          "warning": "S-WARN-NUT-CN", "origin": "S-ORIGIN-CN",
                          "storage": "S-STORE-DRY", "manufacturer": "S-MFR-CN",
                          "claim": "S-CLAIM-NONGMO"},
             versions={"S-ING-MUESLI": 1, "S-WARN-NUT-CN": 1},
             status="final",
             rendered=[],
             created_at=now - 2 * 86400, updated_at=now - 2 * 86400),
        dict(lid="L3", product_id="P2", country="US",
             segment_map={},
             versions={},
             status="draft",
             rendered=[],
             created_at=now - 86400, updated_at=now - 86400),
    ]

    db = {
        "segments": segments,
        "products": products,
        "labels": labels,
        "label_versions": [],
        "audit": [
            dict(id="A0", ts=now - 5 * 86400, actor="system", action="segments_reviewed",
                 sid=None, lid=None, reason="初始审核定稿", impact=[], detail={})
        ],
        "counters": {"segment": 20, "label": 4, "audit": 1},
    }
    save_db(db)
    return db


def load_db():
    if not os.path.exists(DB_FILE):
        return seed_db()
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_db(db):
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    tmp = DB_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DB_FILE)


DB = load_db()


def reset_db():
    global DB
    DB = seed_db()
    return DB


def get_product(db, pid):
    return next((p for p in db["products"] if p["pid"] == pid), None)


def get_segment(db, sid):
    return next((s for s in db["segments"] if s["sid"] == sid), None)


def get_label(db, lid):
    return next((l for l in db["labels"] if l["lid"] == lid), None)


def applicable(seg, country, category, spec, pid):
    if seg["countries"] and country not in seg["countries"]:
        return False
    if seg["categories"] and category not in seg["categories"]:
        return False
    if seg["specs"] and spec not in seg["specs"]:
        return False
    if seg["products"] and pid not in seg["products"]:
        return False
    return True


def specificity(seg):
    return (1 if seg["products"] else 0, 1 if seg["specs"] else 0,
            1 if seg["categories"] else 0, 1 if seg["countries"] else 0)


def render_ingredients(seg, country):
    """按市场规则对配料排序并标注过敏原。"""
    ings = [dict(i) for i in seg.get("ingredients", [])]
    rule = MARKET_RULES[country]
    ings.sort(key=lambda i: (i.get("pct") is None, -(i.get("pct") or 0)))
    style = rule["allergen_style"]
    parts = []
    for ing in ings:
        name = ing["name"]
        if ing.get("allergens"):
            labels = [ALLERGENS[a][country] for a in ing["allergens"]]
            if style == "bold":
                name = name.upper() if country == "EU" else name
                name = "**%s**" % name
            elif style == "parentheses":
                name = "%s（%s）" % (name, "、".join(labels))
        if ing.get("pct") is not None and country != "US":
            pct = ing["pct"]
            pct_s = "%g" % pct
            parts.append("%s %s%%" % (name, pct_s))
        else:
            parts.append(name)
    if country == "US":
        joiner = ", "
    else:
        joiner = "、" if country == "CN" else ", "
    return joiner.join(parts)


def render_allergen_statement(seg, country):
    if not seg.get("allergens"):
        return seg["text"]
    labels = [ALLERGENS[a][country] for a in seg["allergens"]]
    if country == "US":
        return "Contains: " + ", ".join(s.capitalize() for s in labels) + "."
    if country == "CN":
        return "过敏原：" + "、".join(labels)
    return "Allergens: " + ", ".join(s.capitalize() for s in labels) + "."


def render_segment(seg, country, stype):
    if stype == "ingredients" and seg.get("ingredients"):
        return render_ingredients(seg, country)
    if stype == "allergen":
        return render_allergen_statement(seg, country)
    return seg["text"]


def candidate_segments(db, country, category, spec, pid, stype):
    out = []
    for seg in db["segments"]:
        if seg["type"] != stype:
            continue
        if applicable(seg, country, category, spec, pid):
            out.append(seg)
    out.sort(key=lambda s: (s["status"] == "final", specificity(s), s["updated_at"]),
              reverse=True)
    return out


def validate_map(db, product, country, segment_map):
    """返回 (blocks, warnings, rows)。blocks 非空则禁止拼版。"""
    segment_map = normalize_map(segment_map)
    blocks, warnings, rows = [], [], []
    category = product["category_en"] if MARKET_RULES[country]["lang"] == "en" else product["category"]
    spec = product["spec_en"] if MARKET_RULES[country]["lang"] == "en" else product["spec"]
    picked = {}  # type -> [seg]
    for stype, val in segment_map.items():
        if stype not in TYPE_LABELS:
            blocks.append("未知段落类型：%s" % stype)
            continue
        sids = val if isinstance(val, list) else [val]
        if not isinstance(val, list) and stype in MULTI_TYPES:
            pass
        segs = []
        for sid in sids:
            seg = get_segment(db, sid)
            if not seg:
                blocks.append("段落 %s 不存在" % sid)
                continue
            if seg["type"] != stype:
                blocks.append("段落 %s 类型不是 %s" % (sid, TYPE_LABELS[stype]))
            if not applicable(seg, country, category, spec, product["pid"]):
                blocks.append("段落《%s》不适用于 %s / %s / %s" %
                              (seg["title"], MARKET_RULES[country]["name"], category, spec))
            if seg["status"] == "draft":
                warnings.append("段落《%s》尚未定稿" % seg["title"])
            segs.append(seg)
        picked[stype] = segs

    for stype in REQUIRED_TYPES:
        if stype not in picked:
            warnings.append("缺少建议段落：%s" % TYPE_LABELS[stype])

    # 互斥组冲突：同一互斥组的段落不能出现两段
    seen_groups = {}
    for stype, segs in picked.items():
        for seg in segs:
            g = seg.get("mutex_group")
            if not g:
                continue
            if g in seen_groups:
                blocks.append("两段说法打架：《%s》与《%s》同属互斥组 %s，不能同时上标签" %
                              (seen_groups[g]["title"], seg["title"], g))
            else:
                seen_groups[g] = seg

    # 警示语口径冲突：一条强制禁用（严禁/禁止），一条只是提示（请勿/可能）
    # 只看“对过敏者的核心指令”，不把“可能含有微量…”这类交叉污染提示算进去
    hard_words = ("严禁食用", "禁止食用")
    soft_words = ("请勿食用", "谨慎食用")
    warns = [s for segs in picked.values() for s in segs if s["type"] == "warning"]
    def tone(text):
        if any(w in text for w in hard_words):
            return "hard"
        if any(w in text for w in soft_words):
            return "soft"
        return "mid"
    for i, a in enumerate(warns):
        for b in warns[i + 1:]:
            ta, tb = tone(a["text"]), tone(b["text"])
            if "hard" in (ta, tb) and "soft" in (ta, tb):
                blocks.append("警示语力度冲突：《%s》与《%s》一条强制禁用、一条仅提示，需先统一口径" %
                              (a["title"], b["title"]))

    # 美国 FALPCA 要求 Contains 声明覆盖配料中的全部过敏原
    ings = picked.get("ingredients", [])
    if ings and ings[0].get("ingredients") and country == "US":
        ing_allergens = set()
        for item in ings[0]["ingredients"]:
            ing_allergens.update(item.get("allergens", []))
        covered = set()
        for w in warns:
            covered.update(w.get("allergens", []))
        for s in picked.get("allergen", []):
            covered.update(s.get("allergens", []))
        missing = ing_allergens - covered
        if missing:
            names = [ALLERGENS[a][country] for a in missing]
            warnings.append("FALCPA：配料含 %s，需在 Contains 声明中列出" % "、".join(names))

    for stype in TYPE_ORDER:
        for seg in picked.get(stype, []):
            rows.append(dict(type=stype, type_label=TYPE_LABELS[stype], sid=seg["sid"],
                             title=seg["title"], status=seg["status"],
                             version=seg["version"],
                             rendered=render_segment(seg, country, stype)))
    return blocks, warnings, rows


def build_label(db, product, country, segment_map):
    blocks, warnings, rows = validate_map(db, product, country, segment_map)
    return blocks, warnings, rows


def analyze_impact(db, sid):
    """找出引用该段落的所有已定稿标签 -> 产品与库存，给出处置建议。"""
    seg = get_segment(db, sid)
    items = []
    affected_pids = set()
    for label in db["labels"]:
        if label["status"] != "final":
            continue
        used_sid = label_uses(label, sid)
        if not used_sid:
            continue
        product = get_product(db, label["product_id"])
        if not product:
            continue
        affected_pids.add(product["pid"])
        printed = product["printed_qty"]
        intransit = product["intransit_qty"]
        # 处置规则：安全相关(警示语/过敏原/配料)必须召回；
        # 事实性信息(产地/生产商)贴补丁；措辞性信息(声称/储存/品名)改印
        t = seg["type"]
        if t in ("warning", "allergen", "ingredients"):
            action, reason = "recall", "涉及安全/强制信息（%s），已印标签必须召回" % TYPE_LABELS[t]
        elif t in ("origin", "manufacturer"):
            action, reason = "patch", "事实性信息变更（%s），可加贴补丁覆盖" % TYPE_LABELS[t]
        else:
            action, reason = "reprint", "非强制信息（%s），下次印刷时改印即可" % TYPE_LABELS[t]
        cost = {"recall": 0.55, "patch": 0.08, "reprint": 0.0}[action]
        est = round((printed + intransit) * cost + (0 if action != "reprint" else 0), 2)
        items.append(dict(lid=label["lid"], pid=product["pid"], product=product["name"],
                          country=label["country"], printed_qty=printed,
                          intransit_qty=intransit, action=action,
                          action_reason=reason, est_cost=est))
    totals = dict(printed=sum(i["printed_qty"] for i in items),
                  intransit=sum(i["intransit_qty"] for i in items),
                  est_cost=round(sum(i["est_cost"] for i in items), 2),
                  labels=len(items), products=len(affected_pids))
    return dict(sid=sid, title=seg["title"], type=seg["type"],
                type_label=TYPE_LABELS[seg["type"]], version=seg["version"],
                status=seg["status"], items=items, totals=totals,
                affected_products=sorted(affected_pids))


def snapshot_label(db, label):
    product = get_product(db, label["product_id"])
    blocks, warnings, rows = validate_map(db, product, label["country"], label["segment_map"])
    return dict(lid=label["lid"], product_id=label["pid"] if False else label["product_id"],
                product=product["name"], country=label["country"],
                market=MARKET_RULES[label["country"]]["name"],
                status=label["status"], blocks=blocks, warnings=warnings,
                rows=rows, updated_at=label["updated_at"])


def add_audit(db, actor, action, sid, lid, reason, impact, detail=None):
    aid = "A%d" % db["counters"]["audit"]
    db["counters"]["audit"] += 1
    db["audit"].insert(0, dict(id=aid, ts=int(time.time()), actor=actor or "合规员",
                               action=action, sid=sid, lid=lid, reason=reason or "",
                               impact=impact or [], detail=detail or {}))
    return aid


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _err(self, code, msg, extra=None):
        payload = {"error": msg if isinstance(msg, str) else "请求被拒绝"}
        if isinstance(msg, dict):
            payload.update(msg)
        if extra:
            payload.update(extra)
        self._send(code, payload)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        if not n:
            return {}
        raw = self.rfile.read(n).decode("utf-8")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def do_GET(self):
        parsed = urlparse(self.path)
        path, qs = parsed.path, parse_qs(parsed.query)
        try:
            with _LOCK:
                if path == "/api/meta":
                    return self._send(200, dict(markets=MARKET_RULES, types=TYPE_ORDER,
                                                type_labels=TYPE_LABELS,
                                                required=REQUIRED_TYPES, allergens=ALLERGENS))
                if path == "/api/products":
                    return self._send(200, DB["products"])
                if path == "/api/segments":
                    segs = DB["segments"]
                    country = qs.get("country", [None])[0]
                    stype = qs.get("type", [None])[0]
                    pid = qs.get("product", [None])[0]
                    if country or stype or pid:
                        segs = [s for s in segs
                                if (not country or not s["countries"] or country in s["countries"])
                                and (not stype or s["type"] == stype)
                                and (not pid or not s["products"] or pid in s["products"])]
                    return self._send(200, segs)
                if path.startswith("/api/segments/"):
                    sid = path.rsplit("/", 1)[-1]
                    seg = get_segment(DB, sid)
                    if not seg:
                        return self._err(404, "段落不存在")
                    versions = [v for v in DB["label_versions"] if v["sid"] == sid]
                    return self._send(200, dict(segment=seg, versions=versions))
                if path == "/api/labels":
                    return self._send(200, [snapshot_label(DB, l) for l in DB["labels"]])
                if path.startswith("/api/labels/"):
                    tail = path.rsplit("/", 1)[-1]
                    if tail == "candidates":
                        return self._candidates(qs)
                    label = get_label(DB, tail)
                    if not label:
                        return self._err(404, "标签不存在")
                    return self._send(200, snapshot_label(DB, label))
                if path.startswith("/api/impact/"):
                    sid = path.rsplit("/", 1)[-1]
                    if not get_segment(DB, sid):
                        return self._err(404, "段落不存在")
                    return self._send(200, analyze_impact(DB, sid))
                if path == "/api/audit":
                    return self._send(200, DB["audit"])
                if path == "/api/reset":
                    reset_db()
                    return self._send(200, {"ok": True})
                return self._static(path)
        except Exception as exc:  # noqa: BLE001
            return self._err(500, str(exc))

    def _candidates(self, qs):
        pid = qs.get("product", [None])[0]
        country = qs.get("country", [None])[0]
        stype = qs.get("type", [None])[0]
        product = get_product(DB, pid) if pid else None
        if not product or country not in MARKET_RULES or stype not in TYPE_LABELS:
            return self._err(400, "参数 product/country/type 不合法")
        category = product["category_en"] if MARKET_RULES[country]["lang"] == "en" else product["category"]
        spec = product["spec_en"] if MARKET_RULES[country]["lang"] == "en" else product["spec"]
        cands = candidate_segments(DB, country, category, spec, pid, stype)
        return self._send(200, [dict(sid=s["sid"], title=s["title"], text=s["text"],
                                     status=s["status"], version=s["version"],
                                     rendered=render_segment(s, country, stype),
                                     specificity=specificity(s)) for s in cands])

    def _static(self, path):
        if path == "/":
            path = "/index.html"
        rel = os.path.normpath(path.lstrip("/"))
        if rel.startswith(".."):
            return self._err(403, "forbidden")
        fp = os.path.join(WEB, rel)
        if not os.path.isfile(fp):
            return self._err(404, "not found")
        ctype = {"html": "text/html; charset=utf-8", "js": "text/javascript; charset=utf-8",
                 "css": "text/css; charset=utf-8"}.get(rel.rsplit(".", 1)[-1], "application/octet-stream")
        with open(fp, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        data = self._body()
        if data is None:
            return self._err(400, "请求体不是合法 JSON")
        try:
            with _LOCK:
                if path == "/api/segments":
                    return self._create_segment(data)
                if path == "/api/labels":
                    return self._create_label(data)
                if path == "/api/labels/preview":
                    return self._preview(data)
                if path.startswith("/api/labels/") and path.endswith("/finalize"):
                    return self._finalize(path.split("/")[3], data)
                if path.startswith("/api/segments/") and path.endswith("/revise"):
                    return self._revise(path.split("/")[3], data)
                if path == "/api/products":
                    return self._create_product(data)
                return self._err(404, "未知接口")
        except Exception as exc:  # noqa: BLE001
            return self._err(500, str(exc))

    def _create_segment(self, data):
        for k in ("type", "title", "text"):
            if not data.get(k):
                return self._err(400, "缺少字段 %s" % k)
        if data["type"] not in TYPE_LABELS:
            return self._err(400, "段落类型不合法")
        sid = data.get("sid") or ("S-%d" % DB["counters"]["segment"])
        if data.get("sid") and get_segment(DB, sid):
            return self._err(409, "段落编号已存在")
        DB["counters"]["segment"] += 1
        now = int(time.time())
        seg = dict(sid=sid, type=data["type"], title=data["title"],
                   countries=data.get("countries", []),
                   categories=data.get("categories", []),
                   specs=data.get("specs", []),
                   products=data.get("products", []),
                   text=data["text"], ingredients=data.get("ingredients"),
                   allergens=data.get("allergens", []),
                   lang=data.get("lang", "zh"),
                   status=data.get("status", "draft"),
                   mutex_group=data.get("mutex_group"),
                   version=1, created_at=now, updated_at=now)
        DB["segments"].append(seg)
        add_audit(DB, data.get("actor"), "segment_create", sid, None,
                  data.get("reason", "新建段落"), [])
        save_db(DB)
        return self._send(200, seg)

    def _create_product(self, data):
        for k in ("name", "category", "spec"):
            if not data.get(k):
                return self._err(400, "缺少字段 %s" % k)
        pid = "P%d" % (max([int(p["pid"][1:]) for p in DB["products"]] + [0]) + 1)
        product = dict(pid=pid, name=data["name"], category=data["category"], spec=data["spec"],
                       category_en=data.get("category_en", data["category"]),
                       spec_en=data.get("spec_en", data["spec"]),
                       printed_qty=int(data.get("printed_qty", 0)),
                       intransit_qty=int(data.get("intransit_qty", 0)),
                       unit_cost=float(data.get("unit_cost", 0.1)))
        DB["products"].append(product)
        save_db(DB)
        return self._send(200, product)

    def _preview(self, data):
        product = get_product(DB, data.get("product_id", ""))
        country = data.get("country", "")
        if not product or country not in MARKET_RULES:
            return self._err(400, "产品或市场不合法")
        blocks, warnings, rows = build_label(DB, product, country, data.get("segment_map", {}))
        return self._send(200, dict(blocks=blocks, warnings=warnings, rows=rows,
                                    can_finalize=not any(r["status"] == "draft" for r in rows)
                                    and not blocks))

    def _create_label(self, data):
        product = get_product(DB, data.get("product_id", ""))
        country = data.get("country", "")
        if not product or country not in MARKET_RULES:
            return self._err(400, "产品或市场不合法")
        smap = data.get("segment_map", {})
        blocks, warnings, rows = build_label(DB, product, country, smap)
        if blocks:
            return self._err(409, "存在冲突，拼版被拦下", {"blocks": blocks, "warnings": warnings})
        lid = "L%d" % DB["counters"]["label"]
        DB["counters"]["label"] += 1
        now = int(time.time())
        status = "final" if not any(r["status"] == "draft" for r in rows) else "draft"
        label = dict(lid=lid, product_id=product["pid"], country=country,
                     segment_map=smap,
                     versions={s["sid"]: s["version"]
                               for val in smap.values()
                               for s in [get_segment(DB, x) for x in
                                         (val if isinstance(val, list) else [val])] if s},
                     status=status, rendered=[], created_at=now, updated_at=now)
        DB["labels"].append(label)
        add_audit(DB, data.get("actor"), "label_create", None, lid,
                  data.get("reason", "拼版新标签"),
                  [dict(product=product["pid"], country=country, status=status)],
                  dict(warnings=warnings))
        save_db(DB)
        return self._send(200, snapshot_label(DB, label))

    def _finalize(self, lid, data):
        label = get_label(DB, lid)
        if not label:
            return self._err(404, "标签不存在")
        product = get_product(DB, label["product_id"])
        blocks, warnings, rows = build_label(DB, product, label["country"], label["segment_map"])
        missing = [w for w in warnings if w.startswith("缺少建议段落")]
        if missing:
            return self._err(409, "必备段落不全，不能定稿", {"missing": missing})
        if blocks:
            return self._err(409, "冲突未解决，不能定稿", {"blocks": blocks})
        if any(r["status"] == "draft" for r in rows):
            return self._err(409, "仍含未定稿段落，不能定稿",
                                      {"drafts": [r["title"] for r in rows if r["status"] == "draft"]})
        label["status"] = "final"
        label["updated_at"] = int(time.time())
        add_audit(DB, (data or {}).get("actor"), "label_finalize", None, lid,
                  (data or {}).get("reason", "标签定稿"), [], dict(warnings=warnings))
        save_db(DB)
        return self._send(200, snapshot_label(DB, label))

    def _revise(self, sid, data):
        seg = get_segment(DB, sid)
        if not seg:
            return self._err(404, "段落不存在")
        impact = analyze_impact(DB, sid)
        # 必须先确认看过影响清单
        if not data.get("confirmed"):
            return self._send(202, dict(need_confirmation=True, impact=impact))
        now = int(time.time())
        old_copy = dict(seg)
        DB["label_versions"].insert(0, dict(
            sid=sid, version=seg["version"], archived_at=now,
            title=seg["title"], text=seg["text"],
            ingredients=seg.get("ingredients"), type=seg["type"],
            reason=data.get("reason", ""), actor=data.get("actor", "合规员")))
        new_text = data.get("text")
        if new_text is not None:
            seg["text"] = new_text
        if data.get("ingredients") is not None:
            seg["ingredients"] = data["ingredients"]
        if data.get("status") in ("draft", "final"):
            seg["status"] = data["status"]
        if "mutex_group" in data:
            seg["mutex_group"] = data["mutex_group"] or None
        if "countries" in data:
            seg["countries"] = data["countries"]
        if "products" in data:
            seg["products"] = data["products"]
        seg["version"] += 1
        seg["updated_at"] = now

        propagated, demoted = [], []
        # 传播：引用该段落的定稿标签。默认只同步版本号；若内容变更涉及安全，
        # 由前端结合 impact 决定召回/贴补/改印。段落退回草稿时相关标签一并转草稿。
        for label in DB["labels"]:
            if label_uses(label, sid):
                label["versions"][sid] = seg["version"]
                label["updated_at"] = now
                if seg["status"] == "draft" and label["status"] == "final":
                    label["status"] = "draft"
                    demoted.append(label["lid"])
                propagated.append(label["lid"])

        decisions = data.get("decisions", {})  # {lid: "recall|patch|reprint|none"}
        add_audit(DB, data.get("actor"), "segment_revise", sid, None,
                  data.get("reason", ""),
                  [dict(lid=i["lid"], product=i["product"], country=i["country"],
                        printed_qty=i["printed_qty"], intransit_qty=i["intransit_qty"],
                        recommended=i["action"], chosen=decisions.get(i["lid"], i["action"]))
                   for i in impact["items"]],
                  dict(old_version=old_copy["version"], new_version=seg["version"],
                       propagated=propagated, demoted=demoted,
                       totals=impact["totals"], decisions=decisions))
        save_db(DB)
        return self._send(200, dict(segment=seg, impact=impact,
                                    propagated=propagated, demoted=demoted))


def main():
    port = int(os.environ.get("PORT", "8088"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print("标签拼版服务已启动: http://localhost:%d" % port)
    server.serve_forever()


if __name__ == "__main__":
    main()
