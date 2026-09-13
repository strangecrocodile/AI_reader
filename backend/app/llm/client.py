"""LLM 客户端：OpenAI 兼容 Chat Completions（DeepSeek/SiliconFlow/通义等）。

- CloudLLM：配置了 LLM_BASE_URL + LLM_API_KEY 时使用，直连云端开源模型 API。
- MockLLM：未配置时的离线回退，产出确定性规则答案，保证演示与测试不断链。
"""
import json
import re
from abc import ABC, abstractmethod
from typing import Iterator, List


class LLMError(RuntimeError):
    pass


class LLMClient(ABC):
    kind: str = "base"
    name: str = ""

    @abstractmethod
    def chat(self, messages: List[dict], temperature: float = 0.3, max_tokens: int = 1500) -> str:
        """messages: [{'role':..., 'content':...}] → 模型回复文本。"""

    def chat_stream(
        self, messages: List[dict], temperature: float = 0.3, max_tokens: int = 1500
    ) -> Iterator[str]:
        """流式输出。默认退化为一次性返回，子类可覆写为真流式。"""
        yield self.chat(messages, temperature=temperature, max_tokens=max_tokens)


class CloudLLM(LLMClient):
    kind = "cloud"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0):
        import httpx

        self._httpx = httpx
        self.base_url = base_url.rstrip("/")
        self.url = self.base_url + "/chat/completions"
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.name = f"cloud:{model}"

    def chat(self, messages: List[dict], temperature: float = 0.3, max_tokens: int = 1500) -> str:
        try:
            resp = self._httpx.post(
                self.url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"LLM 调用失败: {e}") from e

    def chat_stream(
        self, messages: List[dict], temperature: float = 0.3, max_tokens: int = 1500
    ) -> Iterator[str]:
        """OpenAI 兼容的流式补全：逐块产出 delta 文本。"""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        try:
            with self._httpx.stream(
                "POST",
                self.url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=self.timeout,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    text = line.decode("utf-8", "ignore") if isinstance(line, bytes) else line
                    if not text or not text.startswith("data:"):
                        continue
                    chunk = text[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        data = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue  # 允许服务端插入的心跳/空行
                    delta = (data.get("choices") or [{}])[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield content
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"LLM 流式调用失败: {e}") from e


class MockLLM(LLMClient):
    """离线规则回退：不依赖任何外部服务，输出稳定的演示答案。"""

    kind = "mock"
    name = "mock-rule"

    def chat(self, messages: List[dict], temperature: float = 0.3, max_tokens: int = 1500) -> str:
        # 取最后一条 user 内容作为问题，模拟「极限/为什么」类问答
        user_text = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_text = msg.get("content", "")
                break
        if "极限" in user_text or "为什么" in user_text:
            return (
                "因为我们要描述的是「某一瞬间」的变化，而平均变化率一定跨着一段区间。"
                "让 Δx 不断变小，才能把这段区间压缩到目标时刻；极限存在，说明逼近的结果是稳定、唯一的。"
            )
        return (
            "这段话先定义了自变量的增量 Δx，再由它得到函数增量 Δy。"
            "接下来用 Δy / Δx 表示平均变化率；当 Δx 趋近于 0 时，它的极限就是导数。"
        )


def extract_json(text: str) -> dict:
    """从模型输出中提取 JSON 对象（容忍 ```json 围栏与前后杂讯）。"""
    s = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s)
    if m:
        s = m.group(1).strip()
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1:
        raise LLMError("模型输出中未找到 JSON")
    return json.loads(s[start:end + 1])


def extract_json_array(text: str) -> List[dict]:
    """从模型输出中提取 JSON 数组（容忍 ```json 围栏与前后杂讯）。

    与 tools/kb-agent 的 `_parse_json_array` 契约一致：非数组或非法 JSON 抛错，
    调用方据此回退规则抽取。数组中非字典元素会被丢弃。
    """
    s = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s)
    if m:
        s = m.group(1).strip()
    start = s.find("[")
    end = s.rfind("]")
    if start == -1 or end <= start:
        raise LLMError("模型输出中未找到 JSON 数组")
    data = json.loads(s[start:end + 1])
    if not isinstance(data, list):
        raise LLMError("模型输出不是 JSON 数组")
    return [item for item in data if isinstance(item, dict)]
