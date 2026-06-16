"""Generate the 500-row sentiment evaluation dataset.

Why a generator script (rather than a hand-written jsonl)?
  - Diversity: 500 rows need enough variety that the providers can't game
    the benchmark by memorising a few specific phrases.
  - Reproducibility: the script is deterministic; re-running it produces
    the same dataset so the eval report is comparable across runs.
  - Maintainability: tuning the mix (e.g. add more edge cases) is a
    one-line change to a list, not a 500-row edit.

Composition (target):
  - 200 positive  (40%)
  - 150 negative  (30%)
  - 100 neutral   (20%)
  -  50 edge-case (10%, mostly labeled outside the obvious 3-way)

Run from repo root:
    cd backend && python scripts/build_eval_dataset.py

Output:
    backend/scripts/data/sentiment_eval.jsonl  (~500 rows, ~120 KB)
"""
from __future__ import annotations

import json
import random
from pathlib import Path

random.seed(20260616)  # deterministic generation

OUT = Path(__file__).resolve().parent / "data" / "sentiment_eval.jsonl"


# ---------- helpers ----------------------------------------------------------

def _row(id_: str, text: str, label: str, source: str, notes: str = "") -> dict:
    return {
        "id": id_,
        "text": text,
        "label": label,
        "source": source,
        "notes": notes,
    }


# ---------- positive templates (200) ---------------------------------------
# Hotel/product/corporate praise in the style of ChnSentiCorp Chinese reviews.

_POS_TEMPLATES_HOTEL = [
    "房间非常{adj},卫生做得{adj2},{svc}态度热情,下次还会再来",
    "{loc}位置优越,交通便利,{facility}{adj},价格实惠,推荐入住",
    "入住体验{adj},{svc}响应{adj2},{facility}完善,{pos_word}",
    "早餐品种丰富,味道可口,{svc}态度友善,推荐",
    "房间{adj},{svc}{adj2},整体性价比高,会推荐朋友来",
    "酒店环境{adj},{loc}便利,前台{adj2},值得推荐",
    "{facility}{adj},{svc}专业,入住感受{adj2},下次还会选择",
    "床品舒适,房间干净,卫生间设施{adj},前台服务{adj2}",
    "周边{loc}便利,购物方便,{svc}热情,房间{adj}",
    "新酒店,装修{adj},{svc}{adj2},值得推荐",
    "{facility}{adj},{svc}周到,入住体验超出预期",
    "价格合理,房间{adj},{svc}{adj2},推荐商务出行",
    "房间景观{adj},{svc}{adj2},早餐{adj2}",
    "整体感受{adj},{svc}响应{adj2},{facility}完善",
    "入住多次,{svc}{adj},{facility}保持水准,推荐",
    "{facility}{adj},{svc}专业热情,{loc}便利",
    "房间{adj},{svc}{adj2},卫生间{adj2}",
    "酒店管理规范,{svc}{adj},值得推荐",
    "装修风格{adj},{facility}齐全,{svc}{adj2}",
    "{loc}繁华,交通便利,{svc}响应{adj2}",
]

_POS_TEMPLATES_PRODUCT = [
    "产品{adj},外观{adj2},手感好,使用体验{adj2}",
    "做工精细,质量{adj},{adj2}耐用,推荐购买",
    "包装精美,产品{adj},{facility}{adj2}",
    "性能强劲,运行流畅,{adj2}满意,推荐",
    "外观{adj},{facility}齐全,使用方便,值得推荐",
    "材质{adj},做工精细,{adj2}耐用,推荐",
    "产品{adj},{facility}{adj2},性价比高,推荐",
    "物流快速,包装完好,产品{adj},使用{adj2}",
    "做工精细,{facility}设计合理,{adj2}满意",
    "产品{adj},{adj2}满意,会回购",
    "外观漂亮,{facility}实用,{adj2}喜欢",
    "性能{adj},{adj2}流畅,推荐购买",
    "材质上乘,{facility}设计{adj2},使用{adj2}",
    "产品{adj},{facility}{adj2},售后服务好",
    "做工精细,{adj2}耐用,值得推荐",
    "产品{adj},{facility}完善,使用体验好",
    "材质{adj},{adj2}耐用,外观漂亮",
    "性能{adj},{facility}齐全,推荐",
    "产品{adj},{facility}实用,{adj2}满意",
    "做工精细,{adj2}喜欢,会回购",
]

_POS_TEMPLATES_CORPORATE = [
    "公司业绩{pos_word},{adj}增长,{adj2}客户好评",
    "公司{pos_word},{adj}突破,{adj2}行业领先",
    "公司治理规范,{adj}合规,{adj2}稳健",
    "财报数据{adj},{pos_word},{adj2}投资者认可",
    "公司{pos_word},{adj}创新,{adj2}市场份额扩大",
    "公司战略{adj},{pos_word},{adj2}可持续发展",
    "公司{pos_word},{adj}盈利,{adj2}股东回报",
    "公司治理{adj},{adj2}合规,经营{adj2}",
    "公司{pos_word},{adj}效率,{adj2}客户满意",
    "公司{pos_word},{adj}发展,{adj2}行业认可",
    "公司{pos_word},{adj}转型,{adj2}新业务突破",
    "公司{pos_word},{adj}回报,{adj2}股东",
    "公司{pos_word},{adj}布局,{adj2}长期价值",
    "公司{pos_word},{adj}投入,{adj2}研发实力",
    "公司{pos_word},{adj}成果,{adj2}市场表现",
    "公司{pos_word},{adj}增长,{adj2}客户认可",
    "公司{pos_word},{adj}创新,{adj2}产业升级",
    "公司{pos_word},{adj}管理,{adj2}行业标杆",
    "公司{pos_word},{adj}运营,{adj2}效率提升",
    "公司{pos_word},{adj}改革,{adj2}活力增强",
]

_POS_WORDS = ["表现亮眼", "成绩喜人", "捷报频传", "创新突破", "业绩稳健", "增长强劲", "快速发展", "稳步推进", "实现增长", "提升明显", "稳健增长", "高速发展"]
_POS_ADJ = ["很好", "非常好", "出色", "优秀", "一流", "完美", "精致", "漂亮", "舒适", "宽敞", "干净", "整洁", "明亮", "温馨"]
_POS_ADJ2 = ["令人满意", "超出预期", "印象深刻", "无可挑剔", "十分满意", "非常满意", "倍感舒适"]
_POS_SVC = ["前台", "服务员", "工作人员", "管家", "客服", "服务"]
_POS_LOC = ["位置", "地段", "周边", "选址"]
_POS_FACILITY = ["设施", "设备", "配套", "硬件", "软装"]

# 40 hotel + 40 product + 40 corporate + 50 mixed/service/lifestyle + 30 ad-hoc = 200
positive_pool = []
for _ in range(40):
    positive_pool.append(_row(
        f"pos-h{random.randint(100,999):03d}",
        random.choice(_POS_TEMPLATES_HOTEL).format(
            adj=random.choice(_POS_ADJ),
            adj2=random.choice(_POS_ADJ2),
            svc=random.choice(_POS_SVC),
            loc=random.choice(_POS_LOC),
            facility=random.choice(_POS_FACILITY),
            pos_word=random.choice(_POS_WORDS),
        ),
        "positive",
        "synthetic",
        "hotel review",
    ))
for _ in range(40):
    positive_pool.append(_row(
        f"pos-p{random.randint(100,999):03d}",
        random.choice(_POS_TEMPLATES_PRODUCT).format(
            adj=random.choice(_POS_ADJ),
            adj2=random.choice(_POS_ADJ2),
            facility=random.choice(_POS_FACILITY),
        ),
        "positive",
        "synthetic",
        "product review",
    ))
for _ in range(40):
    positive_pool.append(_row(
        f"pos-c{random.randint(100,999):03d}",
        random.choice(_POS_TEMPLATES_CORPORATE).format(
            adj=random.choice(_POS_ADJ),
            adj2=random.choice(_POS_ADJ2),
            pos_word=random.choice(_POS_WORDS),
        ),
        "positive",
        "synthetic",
        "corporate news",
    ))

# 80 misc: lifestyle / service / events / digital
for _ in range(2):
    positive_pool.append(_row(
        f"pos-c{random.randint(100,999):03d}",
        random.choice(_POS_TEMPLATES_CORPORATE).format(
            adj=random.choice(_POS_ADJ),
            adj2=random.choice(_POS_ADJ2),
            pos_word=random.choice(_POS_WORDS),
        ),
        "positive",
        "synthetic",
        "corporate news",
    ))
_MISC_POS = [
    "演唱会现场气氛热烈,歌手表现非常专业,观众反响热烈",
    "电影剧情紧凑,演员演技精湛,是一部值得推荐的好作品",
    "餐厅菜品精致,味道可口,服务员态度友善,推荐",
    "新书内容详实,装帧精美,值得收藏",
    "展览策划精心,作品水平很高,观众流连忘返",
    "公共交通便利,司机师傅态度友好,体验很好",
    "快递员服务热情,送货速度快,值得推荐",
    "客服响应及时,问题解决专业,服务态度好",
    "售后服务完善,处理问题高效,推荐这家店",
    "新店开业活动丰富,优惠力度大,值得一去",
    "App界面美观,功能完善,使用体验流畅",
    "新版系统运行稳定,响应速度快,体验好",
    "新版界面设计漂亮,功能强大,推荐升级",
    "新功能实用,体验流畅,开发团队用心",
    "客服小妹服务热情,问题处理及时,推荐",
    "维修师傅技术专业,服务态度好,值得推荐",
    "保姆阿姨经验丰富,做事认真,值得信赖",
    "家教老师教学专业,孩子进步明显,推荐",
    "装修师傅手艺精湛,做工精细,值得推荐",
    "搬家师傅服务热情,做事利索,推荐",
    "司机师傅驾驶平稳,服务周到,推荐",
    "外卖小哥送餐及时,服务态度好,值得推荐",
    "餐厅菜品精致,味道鲜美,服务员热情,推荐",
    "咖啡馆环境优雅,咖啡香醇,值得一去",
    "书店环境安静,书籍种类丰富,值得一去",
    "图书馆环境整洁,藏书丰富,值得推荐",
    "博物馆展览精彩,讲解专业,值得一去",
    "公园景色优美,环境整洁,适合休闲",
    "景区服务到位,风景秀丽,推荐游玩",
    "酒店服务一流,设施完善,值得推荐",
    "民宿主人热情,房间干净,值得推荐",
    "客栈环境古朴,服务周到,值得推荐",
    "青年旅舍氛围好,适合背包客,推荐",
    "露营地环境优美,设施齐全,值得推荐",
    "旅游景点景色秀丽,服务到位,推荐",
    "网红打卡点名副其实,体验很好,推荐",
    "音乐节阵容强大,现场气氛热烈,值得一去",
    "话剧演出精彩,演员专业,推荐观看",
    "相声专场笑点不断,演员功底深厚,推荐",
    "京剧表演精湛,唱念做打俱佳,值得一看",
    "芭蕾舞演出优雅,演员技艺精湛,推荐",
    "交响乐演奏水准高,指挥专业,推荐",
    "民乐演出富有韵味,演奏家技艺精湛,推荐",
    "话剧团表演投入,剧本扎实,推荐",
    "演唱会舞美惊艳,歌手状态好,推荐",
    "体育赛事组织有序,运动员表现出色,值得一看",
    "马拉松赛事组织专业,服务到位,推荐参与",
    "志愿者活动组织有序,参与者热情高,值得参与",
    "公益项目执行到位,受益人群广泛,值得支持",
    "慈善晚会感人至深,嘉宾阵容强大,推荐",
    "扶贫项目落实到位,成效显著,值得支持",
    "乡村振兴项目成效显著,村民受益,值得推广",
    "教育改革稳步推进,学生综合素质提升,值得期待",
    "医疗改革成效显著,患者满意度提升,值得推广",
    "环保政策落实有力,空气质量改善,值得肯定",
    "养老服务不断完善,老年人满意度提升,值得推广",
    "社区治理成效显著,居民幸福感提升,值得推广",
    "基层工作扎实推进,群众满意度高,值得推广",
    "民生工程落实到位,群众获得感增强,值得推广",
    "政务服务效率提升,群众办事方便,值得肯定",
    "惠企政策落实到位,企业发展环境改善,值得推广",
    "营商环境持续优化,企业满意度提升,值得推广",
    "招商引资成效显著,项目落地速度快,值得肯定",
    "重点项目建设进展顺利,质量有保障,值得期待",
    "科技创新成果丰硕,转化效率提升,值得肯定",
    "人才培养计划稳步推进,人才结构优化,值得推广",
    "教育改革举措扎实,教育质量稳步提升,值得期待",
    "医疗技术水平提升,患者满意度高,值得推荐",
    "养老服务质量提升,老年人幸福感增强,值得推广",
    "文化活动丰富多彩,群众参与度高,值得推广",
    "体育事业蓬勃发展,竞技水平提升,值得期待",
    "志愿服务深入开展,志愿者队伍壮大,值得参与",
    "公益事业蓬勃发展,爱心企业涌现,值得支持",
    "绿色发展理念深入人心,生态文明建设成效显著,值得肯定",
    "高质量发展取得新成效,经济结构持续优化,值得期待",
    "乡村振兴战略稳步实施,农村面貌焕然一新,值得肯定",
    "区域协调发展取得新进展,中心城市辐射带动作用增强,值得期待",
    "创新驱动发展战略深入实施,科技创新能力显著增强,值得期待",
]
for i, t in enumerate(_MISC_POS):
    positive_pool.append(_row(f"pos-m{i:03d}", t, "positive", "synthetic", "misc positive"))

# Trim happens later in the assembly block.


# ---------- negative templates (150) ----------------------------------------

_NEG_TEMPLATES_HOTEL = [
    "房间异味严重,卫生差,{svc}态度冷漠,要求退款",
    "{loc}偏僻,交通不便,{facility}陈旧,{neg_word}",
    "入住体验很差,{svc}响应慢,{facility}故障",
    "早餐品种少,味道差,{svc}态度冷淡,不推荐",
    "房间狭小,{svc}态度差,整体性价比低",
    "酒店环境差,{loc}嘈杂,前台态度恶劣",
    "{facility}陈旧,{svc}不专业,入住感受糟糕",
    "床品不舒适,房间不干净,卫生间设施破损",
    "周边环境乱,{svc}态度差,房间陈旧",
    "老旧酒店,装修过时,{svc}冷漠",
    "{facility}缺失,{svc}推诿,入住体验差",
    "价格虚高,房间差,{svc}冷漠,不推荐",
    "房间采光差,{svc}态度恶劣,早餐难吃",
    "整体感受差,{svc}响应慢,{facility}陈旧",
    "入住多次,{svc}态度差,{facility}老化,不推荐",
    "{facility}故障,{svc}不专业,{loc}不便",
    "房间潮湿,{svc}冷漠,卫生间脏",
    "酒店管理混乱,{svc}态度差,不推荐",
    "装修风格过时,{facility}陈旧,{svc}冷漠",
    "{loc}嘈杂,交通拥堵,{svc}态度差",
]

_NEG_TEMPLATES_PRODUCT = [
    "产品质量差,外观有瑕疵,手感差,使用体验糟",
    "做工粗糙,质量差,容易损坏,不推荐",
    "包装简陋,产品有缺陷,功能缺失",
    "性能差,运行卡顿,非常失望,要求退货",
    "外观丑陋,{facility}缺失,使用不便,不推荐",
    "材质差,做工粗糙,容易损坏,要求退款",
    "产品差,{facility}缺失,性价比低,不推荐",
    "物流缓慢,包装破损,产品损坏,要求退货",
    "做工粗糙,{facility}设计不合理,使用不便",
    "产品差,{facility}缺失,会退货",
    "外观丑陋,{facility}不实用,非常失望",
    "性能差,{facility}缺失,要求退款",
    "材质低劣,{facility}设计差,使用不便",
    "产品差,{facility}缺失,售后服务差",
    "做工粗糙,容易损坏,要求退款",
    "产品差,{facility}故障,使用体验糟",
    "材质低劣,容易损坏,外观丑陋",
    "性能差,{facility}缺失,要求退款",
    "产品差,{facility}不实用,非常失望",
    "做工粗糙,{facility}缺失,会退货",
]

_NEG_TEMPLATES_CORPORATE = [
    "公司业绩{neg_word},{neg_adj}下滑,{neg_adj2}客户流失",
    "公司{neg_word},{neg_adj}亏损,{neg_adj2}股价暴跌",
    "公司治理混乱,{neg_adj}违规,{neg_adj2}被监管部门处罚",
    "财报数据{neg_adj},{neg_word},{neg_adj2}投资者质疑",
    "公司{neg_word},{neg_adj}衰退,{neg_adj2}市场份额萎缩",
    "公司战略失误,{neg_word},{neg_adj2}业务下滑",
    "公司{neg_word},{neg_adj}债务违约,{neg_adj2}资金链断裂",
    "公司治理{neg_adj},{neg_adj2}财务造假,经营恶化",
    "公司{neg_word},{neg_adj}效率低下,{neg_adj2}客户投诉",
    "公司{neg_word},{neg_adj}困境,{neg_adj2}行业地位下滑",
    "公司{neg_word},{neg_adj}转型失败,{neg_adj2}新业务夭折",
    "公司{neg_word},{neg_adj}倒退,{neg_adj2}股东失望",
    "公司{neg_word},{neg_adj}投资失误,{neg_adj2}巨亏",
    "公司{neg_word},{neg_adj}投入不足,{neg_adj2}研发停滞",
    "公司{neg_word},{neg_adj}丑闻,{neg_adj2}市场表现糟糕",
    "公司{neg_word},{neg_adj}倒退,{neg_adj2}客户流失",
    "公司{neg_word},{neg_adj}造假,{neg_adj2}产业倒退",
    "公司{neg_word},{neg_adj}管理混乱,{neg_adj2}行业批评",
    "公司{neg_word},{neg_adj}运营困难,{neg_adj2}效率下降",
    "公司{neg_word},{neg_adj}改革失败,{neg_adj2}陷入困境",
]

_NEG_WORDS = ["陷入困境", "业绩暴跌", "亏损扩大", "数据造假", "财务造假", "违规被罚", "债务违约", "破产清算", "业务萎缩", "股价暴跌", "持续亏损", "举步维艰"]
_NEG_ADJ = ["严重", "大幅", "显著", "明显", "急剧", "持续", "不断", "明显"]
_NEG_ADJ2 = ["导致", "引发", "造成", "带来", "引起"]
_NEG_SVC = ["前台", "服务员", "工作人员", "客服", "售后", "管家"]
_NEG_LOC = ["位置", "地段", "周边", "选址"]
_NEG_FACILITY = ["设施", "设备", "配套", "硬件", "功能", "配件"]

negative_pool = []
for _ in range(30):
    negative_pool.append(_row(
        f"neg-h{random.randint(100,999):03d}",
        random.choice(_NEG_TEMPLATES_HOTEL).format(
            neg_word=random.choice(_NEG_WORDS),
            neg_adj=random.choice(_NEG_ADJ),
            neg_adj2=random.choice(_NEG_ADJ2),
            svc=random.choice(_NEG_SVC),
            loc=random.choice(_NEG_LOC),
            facility=random.choice(_NEG_FACILITY),
        ),
        "negative",
        "synthetic",
        "hotel complaint",
    ))
for _ in range(30):
    negative_pool.append(_row(
        f"neg-p{random.randint(100,999):03d}",
        random.choice(_NEG_TEMPLATES_PRODUCT).format(
            neg_word=random.choice(_NEG_WORDS),
            neg_adj=random.choice(_NEG_ADJ),
            neg_adj2=random.choice(_NEG_ADJ2),
            facility=random.choice(_NEG_FACILITY),
        ),
        "negative",
        "synthetic",
        "product complaint",
    ))
for _ in range(30):
    negative_pool.append(_row(
        f"neg-c{random.randint(100,999):03d}",
        random.choice(_NEG_TEMPLATES_CORPORATE).format(
            neg_word=random.choice(_NEG_WORDS),
            neg_adj=random.choice(_NEG_ADJ),
            neg_adj2=random.choice(_NEG_ADJ2),
        ),
        "negative",
        "synthetic",
        "corporate negative",
    ))

_NEG_MISC = [
    "演唱会音响效果差,歌手状态不佳,观众失望",
    "电影剧情混乱,演员演技尴尬,是一部不值得看",
    "餐厅菜品难吃,服务员态度冷漠,不推荐",
    "新书内容空洞,纸张质量差,不值得购买",
    "展览作品水平低,策划粗糙,浪费时间",
    "公共交通拥挤,司机态度差,体验差",
    "快递员服务差,送货速度慢,货物损坏",
    "客服响应慢,问题处理不当,服务态度差",
    "售后服务差,处理问题拖延,不推荐这家店",
    "新店开业活动单调,优惠力度小,不值得去",
    "App界面丑陋,功能缺失,使用卡顿",
    "新版系统运行不稳定,响应慢,体验差",
    "新版界面设计糟糕,功能混乱,不推荐升级",
    "新功能鸡肋,体验糟糕,开发团队不用心",
    "客服态度差,问题处理不及时,差评",
    "维修师傅技术差,服务态度差,不推荐",
    "保姆阿姨经验不足,做事敷衍,不放心",
    "家教老师教学不专业,孩子没有进步,不推荐",
    "装修师傅手艺差,做工粗糙,不推荐",
    "搬家师傅服务差,做事拖沓,差评",
    "司机师傅驾驶不稳,服务态度差,不推荐",
    "外卖小哥送餐慢,服务态度差,差评",
    "餐厅菜品难吃,味道差,服务员冷漠,不推荐",
    "咖啡馆环境嘈杂,咖啡难喝,不推荐",
    "书店环境脏乱,书籍种类少,不推荐",
    "图书馆环境差,藏书陈旧,不推荐",
    "博物馆展览单调,讲解不专业,不值得去",
    "公园环境脏乱,设施损坏,不推荐",
    "景区服务差,风景一般,不值得去",
    "酒店服务差,设施陈旧,不推荐",
    "民宿主人态度差,房间脏,不推荐",
    "客栈环境差,服务差,不推荐",
    "青年旅舍氛围差,不适合住,不推荐",
    "露营地环境差,设施损坏,不推荐",
    "旅游景点景色一般,服务差,不推荐",
    "网红打卡点名不副实,体验差,不推荐",
    "音乐节阵容差,现场混乱,不推荐",
    "话剧演出差,演员不专业,不推荐",
    "相声专场笑点少,演员功力差,不推荐",
    "京剧表演粗糙,唱念做打俱差,不推荐",
    "芭蕾舞演出生硬,演员技艺差,不推荐",
    "交响乐演奏水准低,指挥业余,不推荐",
    "民乐演出乏味,演奏家技艺差,不推荐",
    "话剧团表演敷衍,剧本差,不推荐",
    "演唱会舞美粗糙,歌手状态差,不推荐",
    "体育赛事组织混乱,运动员表现差,不推荐",
    "马拉松赛事组织差,服务差,不推荐",
    "志愿者活动组织混乱,参与者热情低,不推荐",
    "公益项目执行差,受益人群少,不推荐",
    "慈善晚会敷衍,嘉宾阵容差,不推荐",
    "扶贫项目落实差,成效差,不推荐",
    "乡村振兴项目执行差,村民无感,不推荐",
    "教育改革推进缓慢,学生压力大,不推荐",
    "医疗改革成效差,患者不满,不推荐",
    "环保政策落实差,空气污染严重,不推荐",
    "养老服务不完善,老年人满意度低,不推荐",
    "社区治理成效差,居民幸福感低,不推荐",
    "基层工作推进缓慢,群众满意度低,不推荐",
    "民生工程落实差,群众获得感低,不推荐",
    "政务服务效率低,群众办事难,不推荐",
    "惠企政策落实差,企业发展环境差,不推荐",
    "营商环境恶化,企业满意度低,不推荐",
]
for i, t in enumerate(_NEG_MISC):
    negative_pool.append(_row(f"neg-m{i:03d}", t, "negative", "synthetic", "misc negative"))

# Trim happens later in the assembly block.


# ---------- neutral templates (100) ----------------------------------------

_NEUTRAL_TEMPLATES = [
    "公司今日召开年度股东大会,审议年度报告及利润分配方案",
    "公司发布公告,披露近期经营情况及未来发展规划",
    "行业研究报告显示,本季度市场规模较上季度略有变化",
    "监管部门召开行业座谈会,通报近期合规情况",
    "公司宣布人事调整,任命新任首席财务官",
    "产品说明书已更新,请用户查阅官网获取最新信息",
    "公司将于下月召开业绩说明会,届时将公布经营数据",
    "行业组织发布最新统计数据,涵盖主要细分领域",
    "公司发布可持续发展报告,披露环境社会治理情况",
    "监管部门发布行业指引,要求企业加强合规管理",
    "公司公告披露股东大会决议,审议通过多项议案",
    "公司召开董事会,审议通过季度报告",
    "公司发布公告,披露重大资产重组进展",
    "公司召开临时股东大会,审议关联交易事项",
    "公司披露回购股份方案,用于员工激励计划",
    "公司发布年报,披露主要财务指标及经营成果",
    "监管部门发布行业风险提示,提醒投资者注意风险",
    "公司召开业绩说明会,管理层回应投资者关切",
    "行业研究报告显示,本季度市场规模与上季度持平",
    "监管部门通报行业检查情况,未发现重大违规",
    "公司召开产品发布会,介绍新一代产品特性",
    "公司召开技术研讨会,探讨行业未来发展方向",
    "公司召开合作伙伴大会,分享最新业务进展",
    "公司召开媒体沟通会,回应市场关注热点",
    "公司召开投资者交流会,介绍公司战略规划",
    "公司召开供应商大会,洽谈下一步合作事宜",
    "公司召开经销商大会,部署下季度销售目标",
    "公司召开客户答谢会,感谢客户长期支持",
    "公司召开年会,总结过去一年工作成果",
    "公司召开表彰大会,奖励优秀员工和团队",
    "公司召开动员大会,部署下阶段重点工作",
    "公司召开总结大会,回顾年度经营情况",
    "公司召开座谈会,听取员工意见建议",
    "公司召开研讨会,探讨行业前沿技术",
    "公司召开座谈会,讨论市场发展趋势",
    "公司召开座谈会,研究下一步发展策略",
    "公司召开座谈会,听取合作伙伴反馈",
    "公司召开座谈会,了解客户需求变化",
    "公司召开座谈会,听取投资者意见建议",
    "公司召开座谈会,讨论行业政策走向",
    "公司召开座谈会,研究应对市场变化",
    "公司召开座谈会,部署年度经营计划",
    "公司召开座谈会,讨论新产品研发方向",
    "公司召开座谈会,审议重大投资项目",
    "公司召开座谈会,研究市场拓展策略",
    "公司召开座谈会,讨论品牌建设方案",
    "公司召开座谈会,听取员工对管理层的意见",
    "公司召开座谈会,讨论数字化转型路径",
    "公司召开座谈会,研究降本增效措施",
    "公司召开座谈会,审议组织架构调整方案",
    "公司召开座谈会,讨论人才培养计划",
    "公司召开座谈会,研究绩效考核改革方案",
    "公司召开座谈会,审议薪酬体系调整方案",
    "公司召开座谈会,讨论员工福利改善方案",
    "公司召开座谈会,审议年度预算方案",
    "公司召开座谈会,讨论重大决策事项",
    "公司召开座谈会,听取法律顾问意见",
    "公司召开座谈会,讨论合规管理工作",
    "公司召开座谈会,审议重大合同条款",
    "公司召开座谈会,研究应对监管政策变化",
    "公司召开座谈会,讨论 ESG 工作推进",
    "公司召开座谈会,审议信息披露事项",
    "公司召开座谈会,讨论投资者关系工作",
    "公司召开座谈会,听取独立董事意见建议",
    "公司召开座谈会,审议高管薪酬方案",
    "公司召开座谈会,讨论股权激励计划",
    "公司召开座谈会,审议员工持股计划",
    "公司召开座谈会,研究公司治理结构优化",
    "公司召开座谈会,讨论内部控制建设",
    "公司召开座谈会,审议风险管理制度",
    "公司召开座谈会,讨论审计工作安排",
    "公司召开座谈会,研究合规管理体系",
    "公司召开座谈会,审议关联交易事项",
    "公司召开座谈会,讨论对外担保事项",
    "公司召开座谈会,研究募集资金使用",
    "公司召开座谈会,审议重大投资决策",
    "公司召开座谈会,讨论重大融资方案",
    "公司召开座谈会,审议重大资产购置",
    "公司召开座谈会,讨论重大资产处置",
    "公司召开座谈会,审议重大资产置换",
    "公司召开座谈会,讨论重大资产剥离",
    "公司召开座谈会,审议公司合并事项",
    "公司召开座谈会,讨论公司分立事项",
    "公司召开座谈会,审议公司增资事项",
    "公司召开座谈会,讨论公司减资事项",
    "公司召开座谈会,审议公司股权变更事项",
    "公司召开座谈会,讨论公司组织形式变更",
    "公司召开座谈会,审议公司章程修订",
    "公司召开座谈会,讨论董事会议事规则修订",
    "公司召开座谈会,审议监事会议事规则修订",
    "公司召开座谈会,讨论股东大会议事规则修订",
    "公司召开座谈会,审议信息披露管理制度修订",
    "公司召开座谈会,讨论关联交易管理制度修订",
    "公司召开座谈会,审议对外担保管理制度修订",
    "公司今日发布公告,披露股权激励计划进展",
    "公司召开工作汇报会,各部门汇报季度工作进展",
    "公司召开专题会议,研究数字化转型实施方案",
    "公司召开协调会议,推进跨部门协作事项",
    "公司召开评审会议,审议技术方案可行性",
    "公司召开论证会议,评估投资项目风险",
    "公司召开评估会议,审核年度经营计划",
    "公司召开审议会议,讨论薪酬调整方案",
    "公司召开审查会议,审议重大合同条款",
    "公司召开工作会议,部署下阶段重点任务",
    "公司召开总结会议,回顾上月工作完成情况",
    "公司召开推进会议,督促重点项目落实进度",
    "公司召开落实会议,贯彻上级文件精神",
]

neutral_pool = []
for i, t in enumerate(_NEUTRAL_TEMPLATES):
    neutral_pool.append(_row(f"neu-n{i:03d}", t, "neutral", "synthetic", "factual announcement"))


# ---------- edge cases (50) -------------------------------------------------
# Targets known keyword-provider failures: negation, idioms, "重大" contexts,
# weak positives that are actually negative, etc.

_EDGE_CASES = [
    # Negation on positive words (should be negative)
    ("这个产品我不推荐", "negative", "neg: 不+推荐"),
    ("客户对服务没有明显的好评反馈", "negative", "neg: 没有+好评"),
    ("业绩本季度没有增长", "negative", "neg: 没有+增长"),
    ("公司治理水平不达标", "negative", "neg: 不+达标"),
    ("我不赞同这个观点", "negative", "neg: 不+赞同"),
    ("产品质量没有达到预期", "negative", "neg: 没有+达到"),
    ("使用体验不太满意", "negative", "neg: 不太+满意"),
    ("服务响应稍微慢了点", "negative", "neg: 稍微+慢"),
    ("客户口碑未能扩大", "negative", "neg: 未+扩大"),
    ("品牌影响力无法提升", "negative", "neg: 无法+提升"),
    # "重大" context-dependent
    ("公司实现重大突破,获得客户高度好评", "positive", "重大+突破=positive"),
    ("发生重大安全事故,产品被召回", "negative", "重大+事故=negative"),
    ("发布重大新产品,引发市场关注", "positive", "重大+产品=positive"),
    ("重大违规行为被监管部门查处", "negative", "重大+违规=negative"),
    ("公司实现重大创新,引领行业发展", "positive", "重大+创新=positive"),
    ("重大数据泄露事件引发担忧", "negative", "重大+泄露=negative"),
    # "无" negation on negative words
    ("本月无安全事故发生", "positive", "无+事故=positive"),
    ("报告期内无重大违规", "positive", "无+违规=positive"),
    ("经营过程中无重大风险", "positive", "无+风险=positive"),
    ("公司无重大亏损", "positive", "无+亏损=positive"),
    # Idiom-based — should hit positive/negative via tokens
    ("公司业绩蒸蒸日上,受到投资者青睐", "positive", "idiom: 蒸蒸日上"),
    ("公司经营举步维艰,股东表示担忧", "negative", "idiom: 举步维艰"),
    ("公司前景一片光明,值得期待", "positive", "idiom: 一片光明"),
    ("公司陷入四面楚歌,股价暴跌", "negative", "idiom: 四面楚歌"),
    ("公司经营如履薄冰,需要警惕", "negative", "idiom: 如履薄冰"),
    # Mild praise with caveat — neutral
    ("产品质量一般,价格实惠,够用就好", "neutral", "balanced mild"),
    ("服务态度尚可,价格略高,整体一般", "neutral", "balanced mild"),
    ("产品外观漂亮,但功能不足,有些失望", "negative", "外观+失望"),
    # Strong intensifiers
    ("公司业绩极其出色,大幅增长", "positive", "degree: 极其"),
    ("服务质量极度糟糕,令人愤怒", "negative", "degree: 极度"),
    ("表现非常优秀,获得客户一致好评", "positive", "degree: 非常"),
    # Mixed signal — should be neutral due to dead zone
    ("公司增长明显,但也存在不少问题", "neutral", "mixed"),
    ("产品有优点也有缺点,中规中矩", "neutral", "balanced"),
    # Specific舆情 scenarios
    ("监管部门约谈公司负责人,要求说明情况", "negative", "约谈=negative"),
    ("公司被列入经营异常名录", "negative", "经营异常"),
    ("公司完成整改,恢复经营", "positive", "完成+整改+恢复"),
    ("公司发布盈利预警,股价承压", "negative", "盈利预警"),
    ("公司宣布分红计划,回馈股东", "positive", "分红+回馈"),
    ("公司被曝数据造假,股价暴跌", "negative", "数据+造假+暴跌"),
    ("公司获得行业奖项,实力获得认可", "positive", "获得+奖项+认可"),
    ("公司被举报涉嫌垄断,监管部门介入", "negative", "举报+垄断"),
    ("公司新产品上市,市场反应良好", "positive", "上市+良好"),
    ("公司召开新闻发布会,澄清市场传闻", "neutral", "新闻发布会"),
    ("公司高管离职,引发市场猜测", "negative", "高管离职"),
    ("公司发布业绩快报,数据符合预期", "neutral", "业绩快报"),
    ("公司股价异动,公司回应称无重大事项", "positive", "无+重大事项"),
    ("公司被监管处罚,影响恶劣", "negative", "监管+处罚"),
    ("公司被监管处罚,公司将整改到位", "neutral", "balanced regulatory"),
    ("公司召开产品发布会,展示新一代产品", "positive", "positive product launch"),
    ("监管部门发布行业指引,要求加强合规管理", "neutral", "neutral regulatory"),
]

edge_pool = [_row(f"edge-{i:03d}", t, lbl, "edge_case", note) for i, (t, lbl, note) in enumerate(_EDGE_CASES)]


# ---------- assemble ---------------------------------------------------------

# Sanity check label distribution.
from collections import Counter

# Trim each pool to exact target size (the template substitution can produce
# duplicate texts across MISC pools, so we shuffle and slice to the target).
random.shuffle(positive_pool)
positive_pool = positive_pool[:200]
random.shuffle(negative_pool)
negative_pool = negative_pool[:150]
random.shuffle(neutral_pool)
neutral_pool = neutral_pool[:100]
random.shuffle(edge_pool)

all_rows = positive_pool + negative_pool + neutral_pool + edge_pool
random.shuffle(all_rows)

counts = Counter(r["label"] for r in all_rows)
print("label distribution:", dict(counts), "total:", len(all_rows))
# Edge cases (50) have mixed labels (some positive, some negative, some neutral)
# and get folded into the overall counts. We require a healthy mix:
assert counts["positive"] >= 150, counts
assert counts["negative"] >= 150, counts
assert counts["neutral"] >= 50, counts
assert sum(counts.values()) == 500, counts
# Edge cases may flip some labels, so just check totals and ratios.
total = sum(counts.values())
assert total == 500, f"expected 500 rows, got {total}"
assert counts.get("positive", 0) >= 150, counts
assert counts.get("negative", 0) >= 150, counts
assert counts.get("neutral", 0) >= 50, counts

# Sanity check all required fields present.
for r in all_rows:
    assert {"id", "text", "label", "source", "notes"} <= r.keys()
    assert r["label"] in {"positive", "negative", "neutral"}
    assert r["text"].strip()

OUT.parent.mkdir(parents=True, exist_ok=True)
with OUT.open("w", encoding="utf-8") as f:
    for r in all_rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

print(f"wrote {len(all_rows)} rows -> {OUT}")