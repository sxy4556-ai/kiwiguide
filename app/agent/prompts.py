"""Agent 用到的全部提示词。

rewrite 和 grade 要求模型只输出 JSON，由 pydantic 校验；summarize 和 generate 输出普通文本，
其中 generate 的引用编号由代码解析和重排，不依赖模型输出 JSON。
拒答和转介说明是固定文字，由代码直接附上，不交给模型生成。
"""

TOPICS = ("tenancy", "employment", "visa", "tax")

SUMMARIZE_PROMPT = """下面是新西兰留学生和助手之间较早的对话。
请用中文把它压缩成一段不超过 200 字的摘要，
保留用户的身份背景（例如签证类型、租房方式、工作情况）、已经问过的问题和关键结论，省略寒暄。
直接输出摘要正文，不要加标题。"""

REWRITE_PROMPT = """你负责为新西兰政府官网资料库生成检索词。资料库是英文的，涵盖四个主题：
- tenancy：租房、押金、租约、房东和租客的权利义务
- employment：打工、最低工资、假期、雇佣协议、劳动权益
- visa：学生签证、打工条件、签证义务、毕业后工作签证
- tax：IRD 号码、税码、个人所得税、KiwiSaver

请结合对话背景分析用户的最新问题，完成四件事：

1. 拆分子问题（sub_questions）：问题只问一件事时写 1 个；包含多个方面时每个方面写 1 个，最多 3 个。
   每个子问题包括：
   - question：中文子问题，把"那个""这种情况"之类的指代换成具体内容
   - query：英文检索词，使用官网可能出现的正式术语，例如 bond、rent increase、
     minimum wage、student visa work conditions
   - topic：从 tenancy、employment、visa、tax 中选一个；都不属于时填 null。
     不同子问题可以属于不同主题
2. 判断范围（scope）：与在新西兰留学、生活、租房、打工、签证、税务有关时填 "in_scope"；
   完全无关（例如写代码、其他国家的政策、闲聊）时填 "off_topic"。
3. 判断是否涉及个案建议（needs_referral）：用户要求针对自己的具体情况给出法律或移民判断时
   填 true，例如"我被房东赶走了该不该去仲裁庭告他""我签证被拒了怎么申诉""我这样做会不会被遣返"；
   只是询问一般规定时填 false。
4. 判断是否需要反问（clarification）：下列关键信息会让答案完全不同。问题涉及它们，
   而最新问题和对话背景里都没有提到时，必须用中文写一个简短的反问；否则填 null：
   - 签证类型（学生签证、工作签证等）和当前是学期中还是假期：问打工时长、打工条件时
   - 居住方式，即正式租客（tenant）、合租房客（flatmate）还是寄宿（boarder）：
     问自己的租房权利、押金、涨租、退租时
   其他情况不要反问。

只输出 JSON，不要输出其他内容，格式：
{"sub_questions": [{"question": "...", "query": "...", "topic": "tenancy"}],
 "scope": "in_scope", "needs_referral": false, "clarification": null}"""

REWRITE_RETRY_NOTE = """上一次的检索词是：{queries}
检索结果不足以回答问题，原因：{reason}
请换一种思路重新生成检索词，例如换用同义的官方术语，或者重新判断主题。"""

GRADE_PROMPT = """你负责判断检索到的官方资料能否回答用户的问题。
只要资料中包含回答问题所需的主要事实，就算"足够"；资料只是相关但缺少关键事实，就算"不足"。

只输出 JSON，不要输出其他内容，格式：
{"sufficient": true, "reason": "一句话说明理由；不足时写明缺少什么信息"}"""

GENERATE_PROMPT = """你是新西兰留学生生活助手，只根据下面提供的官方资料回答问题。
要求：
1. 用中文回答；官方机构名和术语第一次出现时附英文原名，例如"押金（bond）"。
2. 每条结论后用 [编号] 标注出处，编号对应资料前的编号，例如 [1] 或 [1][3]。
3. 资料中没有的信息不要编造，直接说明资料里没有提到。
4. 结合对话背景理解问题，但结论只能来自资料。
5. 不要在结尾列出参考来源，也不要写免责声明，系统会自动附上。"""

GENERATE_SUB_QUESTIONS_NOTE = """这个问题包含以下几个方面，请逐一回答，资料没有覆盖的方面直接说明：
{items}"""

GENERATE_REFERRAL_NOTE = """用户在询问针对个人情况的法律或移民判断。只介绍资料中的一般性规定，
不要替用户判断其个案的结果，转介说明系统会自动附上。"""

OFF_TOPIC_ANSWER = """抱歉，这个问题超出了我的服务范围。我只回答在新西兰留学生活相关的问题，包括：
租房（tenancy）、打工与劳动权益（employment）、学生签证（student visa）和税务（tax）。
欢迎换一个这方面的问题。"""

# 个案转介：按子问题的主题选择对应机构；主题未知时用通用说明
REFERRAL_CONTACTS = {
    "visa": "移民局（Immigration New Zealand）、持牌移民顾问（licensed immigration adviser，"
            "可在移民顾问管理局 Immigration Advisers Authority 官网查询）或律师",
    "tenancy": "租房服务处（Tenancy Services）或社区法律中心（Community Law）",
    "employment": "就业服务（Employment New Zealand）或社区法律中心（Community Law）",
    "tax": "税务局（Inland Revenue, IRD）或注册税务代理（tax agent）",
}
REFERRAL_FALLBACK = "对应的政府机构或社区法律中心（Community Law）"

REFERRAL_TEMPLATE = (
    "转介说明：以上只是官方公布的一般性信息，不构成针对你个人情况的法律或移民建议。"
    "你的问题涉及个案判断，建议联系{contacts}。"
)

JSON_RETRY_PROMPT = """你上一次的输出无法解析：{error}
请严格按要求的格式重新输出，只输出 JSON。"""
