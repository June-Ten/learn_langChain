"""命令行问一次：python -m corp_assistant.demo 年假有几天？"""

import sys

from corp_assistant.assistant import chat
from corp_assistant.main import create_app
from corp_assistant.store import get_employee


def main() -> None:
    create_app()
    question = " ".join(sys.argv[1:]).strip() or "年假有几天？先查制度再回答。"
    user = get_employee("E004")
    if user is None:
        raise SystemExit("种子员工 E004 不存在")
    result = chat(user, question, None)
    print(result["answer"])
    if result["tools"]:
        names = ", ".join(item["name"] for item in result["tools"])
        print(f"\n工具: {names}")


if __name__ == "__main__":
    main()
