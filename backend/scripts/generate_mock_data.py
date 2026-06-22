import argparse
import json
import random
import uuid
import time
from datetime import datetime

# ==========================================
# 事件池定义与分布权重 (Event Pool)
# ==========================================
EVENTS = [
    {
        "code": "goose",
        "weight": 40,
        "title_prefix": "【鹅腿风波】",
        "title_suffixes": ["清北学生集体维权", "监管部门已介入", "阿姨回应争议", "鸭腿充当鹅腿引不满", "相关方致歉"],
        "subjects": ["鹅腿", "网红烤鸭腿", "陈阿姨"],
        "negative_status": ["以次充好", "发霉发绿", "其实是鸭腿"],
        "neutral_status": ["真假难辨", "口感一般", "价格偏贵"],
        "positive_status": ["味道还可以", "大家要求太高了", "阿姨也不容易"],
        "neg_templates": [
            "以为吃的是[Subject]，今天爆出来是[Negative_Status]，当年排队买的大学生真是把心错付了！",
            "[Subject]居然[Negative_Status]，强烈要求退钱退赔！",
            "看到热搜气死了，一直在买的[Subject]竟然[Negative_Status]，简直是欺诈消费。"
        ],
        "neu_templates": [
            "吃瓜群众路过，感觉[Subject][Neutral_Status]，等官方的抽检通报吧。",
            "事情还没定论，先看看[Subject]到底是不是[Neutral_Status]，不盲目站队。"
        ],
        "pos_templates": [
            "作为老顾客，我觉得[Subject][Positive_Status]，大家不要被网暴带节奏了。",
            "别听网上的瞎说，[Subject]明明[Positive_Status]，反正我还会继续支持！"
        ]
    },
    {
        "code": "ev_fire",
        "weight": 35,
        "title_prefix": "【电车自燃】",
        "title_suffixes": ["某品牌底盘磕碰起火", "官方紧急回应", "车主家属发声", "安全性遭质疑", "隐藏式门把手成隐患"],
        "subjects": ["那辆电车", "某品牌新车", "隐藏式门把手"],
        "negative_status": ["烧成空壳了", "门打不开", "刹车失灵"],
        "neutral_status": ["起火原因未明", "等待消防鉴定结果", "属于小概率事件"],
        "positive_status": ["售后态度非常好", "车身结构其实很坚固", "系统预警很及时"],
        "neg_templates": [
            "太可怕了，[Subject]撞击后居然[Negative_Status]，这品控谁还敢买？坚决避雷！",
            "生命安全第一，买个代步车[Subject]竟然[Negative_Status]，必须严查厂家！"
        ],
        "neu_templates": [
            "理性分析一波，[Subject]可能只是[Neutral_Status]，大家不要盲目恐慌制造焦虑。",
            "电车出事容易放大，先别急着下定论，[Subject]也有可能是[Neutral_Status]。"
        ],
        "pos_templates": [
            "水军别黑了，事发时[Subject]表现不错，[Positive_Status]！不要为了黑而黑。",
            "作为老车主，证明[Subject]真的[Positive_Status]，不要信谣传谣自己吓自己。"
        ]
    },
    {
        "code": "milktea",
        "weight": 25,
        "title_prefix": "【奶茶过期】",
        "title_suffixes": ["知名连锁店被曝篡改效期", "消费者疯狂吐槽", "门店停业整顿", "道歉声明发布", "记者暗访后厨"],
        "subjects": ["A牌奶茶", "果茶底料", "后厨"],
        "negative_status": ["全是过期原料", "偷偷换标签", "喝出异物"],
        "neutral_status": ["员工操作不规范", "只是偶发事件", "门店管理有疏漏"],
        "positive_status": ["平时一直很干净", "味道没变依然好喝", "整改态度很积极"],
        "neg_templates": [
            "昨天刚喝了[Subject]，今天就看到[Negative_Status]的热搜，令人作呕，建议直接查封门店！",
            "太恶心了，经常点的[Subject]居然[Negative_Status]，再也不去了，避坑避坑！"
        ],
        "neu_templates": [
            "餐饮行业通病了，[Subject]可能[Neutral_Status]，等市监局的调查结果吧。",
            "客观来说，[Subject]出现[Neutral_Status]情况，希望能借此机会好好改善流程。"
        ],
        "pos_templates": [
            "我常去那家店，[Subject]其实[Positive_Status]，肯定是离职员工故意黑。",
            "出事后[Subject][Positive_Status]，还是愿意给个机会的，毕竟产品好喝。"
        ]
    }
]

AUTHORS_NEG = ["愤怒的消费者", "维权斗士", "看不下去的路人", "正义之眼", "被坑的苦主", "打假先锋"]
AUTHORS_NEU = ["理中客", "吃瓜一线", "新闻观察员", "路过看看", "等官方通报", "深夜吃瓜人"]
AUTHORS_POS = ["铁粉编号1024", "永远支持", "不信谣不传谣", "真实体验者", "死忠粉", "岁月静好"]

def generate_record(now_timestamp):
    # 1. 根据权重随机选择事件
    event = random.choices(EVENTS, weights=[e["weight"] for e in EVENTS], k=1)[0]
    
    # 2. 根据比例随机决定情感极性 (负面 60%, 中性 30%, 正面 10%)
    sentiment = random.choices(["neg", "neu", "pos"], weights=[60, 30, 10], k=1)[0]
    
    # 3. 构造外部 ID 和标题
    external_id = f"{event['code']}-{uuid.uuid4().hex[:8]}"
    title_suffix = random.choice(event["title_suffixes"])
    title = f"{event['title_prefix']} {title_suffix}"
    
    # 4. 根据情感匹配内容和作者
    subject = random.choice(event["subjects"])
    if sentiment == "neg":
        status = random.choice(event["negative_status"])
        template = random.choice(event["neg_templates"])
        author_pool = AUTHORS_NEG
    elif sentiment == "neu":
        status = random.choice(event["neutral_status"])
        template = random.choice(event["neu_templates"])
        author_pool = AUTHORS_NEU
    else:
        status = random.choice(event["positive_status"])
        template = random.choice(event["pos_templates"])
        author_pool = AUTHORS_POS
        
    # 模板替换
    content = template.replace("[Subject]", subject).replace("[Negative_Status]", status)\
                      .replace("[Neutral_Status]", status).replace("[Positive_Status]", status)
    
    # 增加唯一防伪标记，防止后端根据内容 Hash 触发系统级去重
    content += f" (唯一码: {external_id})"
    
    # 随机生成作者名附加后缀增加真实感
    author = f"{random.choice(author_pool)}_{random.randint(100, 9999)}"
    
    # 原贴链接
    url = f"https://example.com/post/{external_id}"
    
    # 随机时间 (过去 7 天内)
    random_seconds = random.randint(0, 7 * 24 * 3600)
    published_at_dt = datetime.fromtimestamp(now_timestamp - random_seconds)
    published_at = published_at_dt.strftime("%Y-%m-%dT%H:%M:%S")
    
    return {
        "external_id": external_id,
        "title": title,
        "content": content,
        "url": url,
        "author": author,
        "language": "zh",
        "published_at": published_at
    }

def main():
    parser = argparse.ArgumentParser(description="舆情模拟数据生成脚本 (Spec v3.0 多事件混合版)")
    parser.add_argument("--count", type=int, default=10000, help="要生成的数据总条数 (默认 10000)")
    parser.add_argument("--format", type=str, choices=["json", "jsonl"], default="json", help="输出格式: json 或 jsonl (默认 json)")
    parser.add_argument("--output", type=str, default="mock_opinions_v3", help="输出文件名前缀 (不需要扩展名，默认 mock_opinions_v3)")
    
    args = parser.parse_args()
    count = args.count
    out_format = args.format
    out_file = f"{args.output}.{out_format}"
    
    print(f"[*] 开始生成 {count} 条多事件混合舆情数据...")
    print(f"[*] 输出格式: {out_format.upper()}, 目标文件: {out_file}")
    
    start_time = time.time()
    now_timestamp = time.time()
    
    # 采用流式写入，防止生成十万甚至百万条数据时内存溢出 (OOM)
    with open(out_file, "w", encoding="utf-8") as f:
        if out_format == "json":
            f.write('{\n  "records": [\n')
            
        for i in range(count):
            record = generate_record(now_timestamp)
            if out_format == "jsonl":
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            else:
                record_str = json.dumps(record, ensure_ascii=False)
                if i < count - 1:
                    f.write(f"    {record_str},\n")
                else:
                    f.write(f"    {record_str}\n")
                    
        if out_format == "json":
            f.write('  ]\n}\n')
            
    cost = time.time() - start_time
    print(f"[*] 生成完成！共耗时: {cost:.2f} 秒。")
    print(f"[*] 文件已保存至当前目录: {out_file}")

if __name__ == "__main__":
    main()
