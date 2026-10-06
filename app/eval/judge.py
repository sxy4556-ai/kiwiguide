"""回答质量的 LLM 评判：忠实度和正确率，各 1–5 分。

评判只看回答正文：来源列表、转介说明和免责声明都是代码附加的固定文字，不参与打分。
"""

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agent.nodes import invoke_json

FAITHFULNESS_PROMPT = """你负责评判一个问答系统的回答是否忠实于它所依据的资料。
逐条检查回答中的事实性陈述（数字、期限、条件、权利义务等），看能否在资料中找到依据。
引用编号可能已经重新排列，请忽略编号，只核对内容本身。
回答中说明"资料没有提到"之类的话不算无依据。

评分标准：
5：所有陈述都有依据
4：只有个别细节无依据，且不影响结论
3：有少量无依据的陈述，其中包含实质内容
2：较多陈述无依据，或有与资料矛盾的内容
1：大部分内容无依据或与资料矛盾

只输出 JSON，不要输出其他内容，格式：
{"score": 5, "reason": "一句话说明理由，指出无依据的陈述"}"""

CORRECTNESS_PROMPT = """你负责评判一个问答系统的回答是否覆盖了标准答案的要点。
逐条对照要点，看回答是否给出了相同的结论（表述可以不同，数字和条件必须一致）。
回答先向用户反问、或说明需要更多信息才能确定的，如果要点本身就是"需要先了解某信息"，算作覆盖。

评分标准：
5：覆盖全部要点，没有错误
4：覆盖大部分要点，没有错误
3：只覆盖约一半要点，或有小的错误
2：只覆盖少量要点，或有明显错误
1：没有覆盖要点，或结论错误

只输出 JSON，不要输出其他内容，格式：
{"score": 5, "reason": "一句话说明理由，指出遗漏或错误的要点"}"""

SOURCES_MARKER = "\n\n参考来源："


class JudgeOutput(BaseModel):
    score: int = Field(ge=1, le=5)
    reason: str = ""


def answer_body(answer: str) -> str:
    """去掉代码附加的来源列表及其后的转介说明和免责声明，只留模型写的正文。"""
    return answer.split(SOURCES_MARKER, 1)[0].strip()


def judge_faithfulness(llm, question: str, answer: str, context: str) -> JudgeOutput | None:
    """返回 None 表示评判结果两次都无法解析，该题不计入平均分。"""
    content = f"问题：{question}\n\n资料：\n\n{context}\n\n回答：\n{answer_body(answer)}"
    return invoke_json(
        llm, [SystemMessage(FAITHFULNESS_PROMPT), HumanMessage(content)], JudgeOutput
    )


def judge_correctness(
    llm, question: str, answer: str, key_points: list[str]
) -> JudgeOutput | None:
    points = "\n".join(f"- {p}" for p in key_points)
    content = f"问题：{question}\n\n标准答案要点：\n{points}\n\n回答：\n{answer_body(answer)}"
    return invoke_json(
        llm, [SystemMessage(CORRECTNESS_PROMPT), HumanMessage(content)], JudgeOutput
    )
