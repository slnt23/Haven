import asyncio
import logging
import sys

from forest.agents import OrchestratorAgent, ResearcherAgent, CoderAgent
from forest.services.email_service import EmailService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("forest.email_service.main")


def build_agent_handler():
    orchestrator = OrchestratorAgent()
    researcher = ResearcherAgent("researcher")
    coder = CoderAgent("coder")
    orchestrator.register_agent("researcher", researcher)
    orchestrator.register_agent("coder", coder)

    async def handle_message(subject: str, body: str) -> str:
        prompt = f"用户通过邮件提问。\n主题: {subject}\n内容:\n{body}\n\n请用中文回复。"
        return await orchestrator.run(prompt)

    return handle_message


async def main():
    logger.info("Starting Forest Email Service...")

    agent_handler = build_agent_handler()
    service = EmailService(agent_handler=agent_handler)

    await service.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
