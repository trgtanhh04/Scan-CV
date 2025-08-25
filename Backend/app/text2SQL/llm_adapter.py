import re
# =================================
# 3) LLM interface (plug your LLM)
# =================================
class LLM:
    def __init__(self, invoke_fn):
        self._invoke = invoke_fn

    def gen(self, prompt: str) -> str:
        out = self._invoke(prompt).strip()
        # remove markdown fences if any
        out = re.sub(r"^```(?:sql|SQL)?\s*|\s*```$", "", out, flags=re.MULTILINE).strip()
        return out
