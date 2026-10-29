import asyncio
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate

llm = ChatOllama(
    model="lfm2.5-thinking",
    base_url="http://localhost:11434",
    temperature=0.7,
)

prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are a quantitative research assistant. "
        "Distinguish facts from hypotheses."
    ),
    (
        "human",
        "{question}"
    )
])

chain = prompt | llm

async def process_question(idx, question):
    """Xử lý từng câu hỏi và trả về index + content"""
    response = await chain.ainvoke({"question": question})
    return idx, response.content

async def process_questions_fifo(questions):
    """Chạy song song, in kết quả FIFO (khi xong thì in ngay)"""
    tasks = [process_question(i, q) for i, q in enumerate(questions)]
    
    for coro in asyncio.as_completed(tasks):
        idx, content = await coro
        print(f"Q{idx+1}: {content}\n")

# 5 câu hỏi
questions = [
    "Explain momentum.",
    "Explain mean reversion.",
    "What is portfolio diversification?",
    "Define risk management.",
    "What is alpha?",
]

# Chạy song song, in kết quả theo thứ tự hoàn thành (FIFO)
asyncio.run(process_questions_fifo(questions))
