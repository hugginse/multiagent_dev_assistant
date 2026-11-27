"""三通道统一 LLM 客户端（ollama / openai / anthropic）。

设计要点（architecture.md §0 D3、§10 质量红线）：
- 默认 ollama + ``qwen3.5:9b``，本地模型**不得降级**
- openai / anthropic 缺 key 在构造时**显式失败**（``LLMError``），禁止静默降级
- 统一接口：同步/流式补全 + tool-calling + usage 累计
- 流式产出 ``llm_delta`` 粒度 token，供 CLI 真流式打印
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import Settings, get_settings

# 事件协议里 llm_delta 的类型别名（展示层订阅）
LLMDelta = str


class LLMError(Exception):
    """配置或通道级错误（缺 key、非法 provider、HTTP 失败等）。CLI 映射退出码 2。"""


@dataclass(slots=True)
class LLMUsage:
    tokens_in: int = 0
    tokens_out: int = 0

    def add(self, other: LLMUsage) -> None:
        self.tokens_in += other.tokens_in
        self.tokens_out += other.tokens_out


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class Message:
    """统一消息（role: system | user | assistant | tool）。"""

    role: str
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None


@dataclass(slots=True)
class LLMResult:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: LLMUsage = field(default_factory=LLMUsage)
    model: str = ""
    finish_reason: str = ""


def _estimate_tokens(text: str) -> int:
    """本地模型无官方 usage 时的粗估口径（≈4 字符/token），报告需注明。"""
    if not text:
        return 0
    return max(1, len(text) // 4)


def _openai_tools(tools: Sequence[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


def _parse_openai_tool_calls(raw: Any) -> list[ToolCall]:
    calls: list[ToolCall] = []
    if not raw:
        return calls
    import json

    for i, item in enumerate(raw):
        fn = item.get("function") or {}
        args_raw = fn.get("arguments") or "{}"
        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else dict(args_raw)
        except (json.JSONDecodeError, TypeError):
            args = {"_raw": args_raw}
        calls.append(
            ToolCall(
                id=item.get("id") or f"call_{i}",
                name=fn.get("name") or "",
                arguments=args if isinstance(args, dict) else {"value": args},
            )
        )
    return calls


class LLMClient:
    """按 ``Settings.llm_provider`` 选择通道的统一客户端。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.provider = self.settings.llm_provider
        # 构造时完成显式校验：缺 key / 缺模型立即失败
        try:
            self.settings.require_api_key()
            self.model = self.settings.resolve_llm_model()
        except ValueError as e:
            raise LLMError(str(e)) from e
        if self.provider not in {"ollama", "openai", "anthropic"}:
            raise LLMError(f"不支持的 LLM_PROVIDER: {self.provider!r}")

        headers: dict[str, str] = {"Content-Type": "application/json"}
        base_url = ""
        if self.provider == "ollama":
            base_url = self.settings.ollama_host.rstrip("/")
        elif self.provider == "openai":
            base_url = self.settings.openai_base_url.rstrip("/")
            headers["Authorization"] = f"Bearer {self.settings.openai_api_key}"
        else:  # anthropic
            base_url = "https://api.anthropic.com"
            headers["x-api-key"] = self.settings.anthropic_api_key
            headers["anthropic-version"] = "2023-06-01"

        self._base_url = base_url
        self._headers = headers
        self._client = httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0))

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> LLMClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # 统一接口
    # ------------------------------------------------------------------ #
    def complete(
        self,
        messages: Sequence[Message | dict[str, Any]],
        *,
        tools: Sequence[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> LLMResult:
        """非流式补全，返回完整文本 + tool_calls + usage。"""
        norm = [_to_dict(m) for m in messages]
        if self.provider == "ollama":
            return self._ollama_complete(norm, tools, temperature, max_tokens)
        if self.provider == "openai":
            return self._openai_complete(norm, tools, temperature, max_tokens)
        return self._anthropic_complete(norm, tools, temperature, max_tokens)

    def stream(
        self,
        messages: Sequence[Message | dict[str, Any]],
        *,
        tools: Sequence[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> Iterator[LLMDelta]:
        """流式补全：逐 token 产出 delta；结束后内部 usage 可从最后 result 读取。

        使用方式::

            for delta in client.stream(...):
                print(delta, end="", flush=True)   # CLI 真流式
        """
        norm = [_to_dict(m) for m in messages]
        if self.provider == "ollama":
            yield from self._ollama_stream(norm, tools, temperature, max_tokens)
        elif self.provider == "openai":
            yield from self._openai_stream(norm, tools, temperature, max_tokens)
        else:
            yield from self._anthropic_stream(norm, tools, temperature, max_tokens)

    def stream_with_result(
        self,
        messages: Sequence[Message | dict[str, Any]],
        *,
        tools: Sequence[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> Iterator[LLMDelta | LLMResult]:
        """流式过程中混入终态 ``LLMResult``（最后一个元素）。"""
        norm = [_to_dict(m) for m in messages]
        if self.provider == "ollama":
            it = self._ollama_stream_iter(norm, tools, temperature, max_tokens)
        elif self.provider == "openai":
            it = self._openai_stream_iter(norm, tools, temperature, max_tokens)
        else:
            it = self._anthropic_stream_iter(norm, tools, temperature, max_tokens)
        result: LLMResult | None = None
        for item in it:
            if isinstance(item, LLMResult):
                result = item
            else:
                yield item
        if result is None:
            raise LLMError("流式补全未产生终态结果")
        yield result

    # ------------------------------------------------------------------ #
    # Ollama
    # ------------------------------------------------------------------ #
    def _ollama_options(self) -> dict[str, Any]:
        return {"num_ctx": self.settings.ollama_num_ctx, "temperature": 0.2}

    def _ollama_payload(
        self,
        messages: list[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int,
        stream: bool,
    ) -> dict[str, Any]:
        opts = self._ollama_options()
        opts["temperature"] = temperature
        opts["num_predict"] = max_tokens
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "options": opts,
        }
        if tools:
            payload["tools"] = _openai_tools(tools)
        return payload

    def _ollama_complete(
        self,
        messages: list[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int,
    ) -> LLMResult:
        payload = self._ollama_payload(messages, tools, temperature, max_tokens, stream=False)
        try:
            resp = self._client.post(f"{self._base_url}/api/chat", json=payload)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise LLMError(f"ollama 请求失败: {e}") from e
        data = resp.json()
        if data.get("error"):
            raise LLMError(f"ollama 错误: {data['error']}")
        msg = data.get("message") or {}
        usage = LLMUsage(
            tokens_in=int(data.get("prompt_eval_count") or 0),
            tokens_out=int(data.get("eval_count") or 0),
        )
        if usage.tokens_in == 0 and usage.tokens_out == 0:
            # 估算口径，报告注明
            usage = LLMUsage(
                tokens_in=_estimate_tokens(str(messages)),
                tokens_out=_estimate_tokens(msg.get("content") or ""),
            )
        return LLMResult(
            content=msg.get("content") or "",
            tool_calls=_parse_openai_tool_calls(msg.get("tool_calls")),
            usage=usage,
            model=self.model,
            finish_reason=data.get("done_reason") or "stop",
        )

    def _ollama_stream_iter(
        self,
        messages: list[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int,
    ) -> Iterator[LLMDelta | LLMResult]:
        payload = self._ollama_payload(messages, tools, temperature, max_tokens, stream=True)
        parts: list[str] = []
        tool_calls: list[ToolCall] = []
        usage = LLMUsage()
        finish = "stop"
        try:
            with self._client.stream(
                "POST", f"{self._base_url}/api/chat", json=payload
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    import json

                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if data.get("error"):
                        raise LLMError(f"ollama 错误: {data['error']}")
                    msg = data.get("message") or {}
                    delta = msg.get("content") or ""
                    if delta:
                        parts.append(delta)
                        yield delta
                    for tc in _parse_openai_tool_calls(msg.get("tool_calls")):
                        # ollama 可能分片返回 tool_calls，按 id 合并
                        _merge_tool_call(tool_calls, tc)
                    if data.get("done"):
                        usage = LLMUsage(
                            tokens_in=int(data.get("prompt_eval_count") or 0),
                            tokens_out=int(data.get("eval_count") or 0),
                        )
                        finish = data.get("done_reason") or "stop"
        except httpx.HTTPError as e:
            raise LLMError(f"ollama 流式请求失败: {e}") from e

        content = "".join(parts)
        if usage.tokens_in == 0 and usage.tokens_out == 0:
            usage = LLMUsage(
                tokens_in=_estimate_tokens(str(messages)),
                tokens_out=_estimate_tokens(content),
            )
        yield LLMResult(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            model=self.model,
            finish_reason=finish,
        )

    def _ollama_stream(self, *args: Any, **kwargs: Any) -> Iterator[LLMDelta]:
        for item in self._ollama_stream_iter(*args, **kwargs):
            if isinstance(item, LLMResult):
                self.last_result = item
            else:
                yield item

    # ------------------------------------------------------------------ #
    # OpenAI 兼容
    # ------------------------------------------------------------------ #
    def _openai_payload(
        self,
        messages: list[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if stream:
            payload["stream_options"] = {"include_usage": True}
        ot = _openai_tools(tools)
        if ot:
            payload["tools"] = ot
        return payload

    def _openai_complete(
        self,
        messages: list[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int,
    ) -> LLMResult:
        payload = self._openai_payload(messages, tools, temperature, max_tokens, stream=False)
        try:
            resp = self._client.post(
                f"{self._base_url}/chat/completions", json=payload, headers=self._headers
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise LLMError(f"openai 请求失败: {e}") from e
        data = resp.json()
        if data.get("error"):
            err = data["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise LLMError(f"openai 错误: {msg}")
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        usage_raw = data.get("usage") or {}
        return LLMResult(
            content=msg.get("content") or "",
            tool_calls=_parse_openai_tool_calls(msg.get("tool_calls")),
            usage=LLMUsage(
                tokens_in=int(usage_raw.get("prompt_tokens") or 0),
                tokens_out=int(usage_raw.get("completion_tokens") or 0),
            ),
            model=data.get("model") or self.model,
            finish_reason=choice.get("finish_reason") or "stop",
        )

    def _openai_stream_iter(
        self,
        messages: list[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int,
    ) -> Iterator[LLMDelta | LLMResult]:
        payload = self._openai_payload(messages, tools, temperature, max_tokens, stream=True)
        parts: list[str] = []
        tool_calls: list[ToolCall] = []
        usage = LLMUsage()
        finish = "stop"
        import json

        try:
            with self._client.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=self._headers,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if data.get("error"):
                        err = data["error"]
                        m = err.get("message") if isinstance(err, dict) else str(err)
                        raise LLMError(f"openai 错误: {m}")
                    choice = (data.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    text = delta.get("content") or ""
                    if text:
                        parts.append(text)
                        yield text
                    for tc in _parse_openai_tool_calls(delta.get("tool_calls")):
                        _merge_tool_call(tool_calls, tc)
                    if choice.get("finish_reason"):
                        finish = choice["finish_reason"]
                    usage_raw = data.get("usage")
                    if usage_raw:
                        usage = LLMUsage(
                            tokens_in=int(usage_raw.get("prompt_tokens") or 0),
                            tokens_out=int(usage_raw.get("completion_tokens") or 0),
                        )
        except httpx.HTTPError as e:
            raise LLMError(f"openai 流式请求失败: {e}") from e

        content = "".join(parts)
        yield LLMResult(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            model=self.model,
            finish_reason=finish,
        )

    def _openai_stream(self, *args: Any, **kwargs: Any) -> Iterator[LLMDelta]:
        for item in self._openai_stream_iter(*args, **kwargs):
            if isinstance(item, LLMResult):
                self.last_result = item
            else:
                yield item

    # ------------------------------------------------------------------ #
    # Anthropic
    # ------------------------------------------------------------------ #
    def _anthropic_split(
        self, messages: list[dict[str, Any]]
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """system 消息拆出；其余转 Anthropic user/assistant 格式。"""
        system_parts: list[str] = []
        out: list[dict[str, Any]] = []
        for m in messages:
            role = m.get("role")
            content = m.get("content") or ""
            if role == "system":
                system_parts.append(content)
            elif role == "tool":
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m.get("tool_call_id") or "",
                                "content": content,
                            }
                        ],
                    }
                )
            elif role == "assistant":
                blocks: list[dict[str, Any]] = []
                if content:
                    blocks.append({"type": "text", "text": content})
                for tc in _parse_openai_tool_calls(m.get("tool_calls")):
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                        }
                    )
                if blocks:
                    out.append({"role": "assistant", "content": blocks})
            else:
                out.append({"role": "user", "content": content})
        system = "\n\n".join(system_parts) if system_parts else None
        return system, out

    def _anthropic_tools(self, tools: Sequence[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        return [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t.get("parameters", {"type": "object", "properties": {}}),
            }
            for t in tools
        ]

    def _anthropic_complete(
        self,
        messages: list[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int,
    ) -> LLMResult:
        system, amessages = self._anthropic_split(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": amessages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if system:
            payload["system"] = system
        at = self._anthropic_tools(tools)
        if at:
            payload["tools"] = at
        try:
            resp = self._client.post(
                f"{self._base_url}/v1/messages", json=payload, headers=self._headers
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise LLMError(f"anthropic 请求失败: {e}") from e
        data = resp.json()
        if data.get("type") == "error" or data.get("error"):
            err = data.get("error") or data
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise LLMError(f"anthropic 错误: {msg}")
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in data.get("content") or []:
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text") or "")
            elif btype == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.get("id") or "",
                        name=block.get("name") or "",
                        arguments=block.get("input") or {},
                    )
                )
        usage_raw = data.get("usage") or {}
        return LLMResult(
            content="".join(text_parts),
            tool_calls=tool_calls,
            usage=LLMUsage(
                tokens_in=int(usage_raw.get("input_tokens") or 0),
                tokens_out=int(usage_raw.get("output_tokens") or 0),
            ),
            model=data.get("model") or self.model,
            finish_reason=data.get("stop_reason") or "end_turn",
        )

    def _anthropic_stream_iter(
        self,
        messages: list[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int,
    ) -> Iterator[LLMDelta | LLMResult]:
        system, amessages = self._anthropic_split(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": amessages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if system:
            payload["system"] = system
        at = self._anthropic_tools(tools)
        if at:
            payload["tools"] = at

        parts: list[str] = []
        tool_calls: list[ToolCall] = []
        usage = LLMUsage()
        finish = "end_turn"
        import json

        # 流式 tool_use 块按 index 聚合
        pending_tools: dict[int, dict[str, Any]] = {}

        try:
            with self._client.stream(
                "POST",
                f"{self._base_url}/v1/messages",
                json=payload,
                headers=self._headers,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    etype = data.get("type")
                    if etype == "content_block_start":
                        block = data.get("content_block") or {}
                        if block.get("type") == "tool_use":
                            idx = int(data.get("index") or 0)
                            pending_tools[idx] = {
                                "id": block.get("id") or "",
                                "name": block.get("name") or "",
                                "input": dict(block.get("input") or {}),
                            }
                    elif etype == "content_block_delta":
                        delta = data.get("delta") or {}
                        dtype = delta.get("type")
                        if dtype == "text_delta":
                            text = delta.get("text") or ""
                            if text:
                                parts.append(text)
                                yield text
                        elif dtype == "input_json_delta":
                            idx = int(data.get("index") or 0)
                            if idx in pending_tools:
                                partial = pending_tools[idx].setdefault("_json", "")
                                pending_tools[idx]["_json"] = partial + (
                                    delta.get("partial_json") or ""
                                )
                    elif etype == "message_delta":
                        d = data.get("delta") or {}
                        if d.get("stop_reason"):
                            finish = d["stop_reason"]
                        u = data.get("usage") or {}
                        if u:
                            usage = LLMUsage(
                                tokens_in=int(u.get("input_tokens") or usage.tokens_in),
                                tokens_out=int(u.get("output_tokens") or usage.tokens_out),
                            )
                    elif etype == "message_start":
                        u = (data.get("message") or {}).get("usage") or {}
                        if u:
                            usage.tokens_in = int(u.get("input_tokens") or 0)
                    elif etype == "error":
                        err = data.get("error") or {}
                        raise LLMError(
                            f"anthropic 错误: {err.get('message') if isinstance(err, dict) else err}"
                        )
        except httpx.HTTPError as e:
            raise LLMError(f"anthropic 流式请求失败: {e}") from e

        for idx in sorted(pending_tools):
            info = pending_tools[idx]
            raw_json = info.pop("_json", "") or "{}"
            try:
                args = json.loads(raw_json)
            except json.JSONDecodeError:
                args = {"_raw": raw_json}
            tool_calls.append(
                ToolCall(
                    id=info["id"] or f"toolu_{idx}",
                    name=info["name"],
                    arguments=args if isinstance(args, dict) else {"value": args},
                )
            )

        content = "".join(parts)
        if usage.tokens_in == 0 and usage.tokens_out == 0:
            usage = LLMUsage(
                tokens_in=_estimate_tokens(str(messages)),
                tokens_out=_estimate_tokens(content),
            )
        yield LLMResult(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            model=self.model,
            finish_reason=finish,
        )

    def _anthropic_stream(self, *args: Any, **kwargs: Any) -> Iterator[LLMDelta]:
        for item in self._anthropic_stream_iter(*args, **kwargs):
            if isinstance(item, LLMResult):
                self.last_result = item
            else:
                yield item


def _merge_tool_call(existing: list[ToolCall], incoming: ToolCall) -> None:
    """按 id 合并分片 tool_call（ollama/openai 流式）。"""
    for tc in existing:
        if tc.id == incoming.id or (not incoming.id and tc.name == incoming.name):
            if incoming.name:
                tc.name = incoming.name
            if incoming.arguments:
                # arguments 可能是增量 dict，浅合并
                tc.arguments = {**tc.arguments, **incoming.arguments}
            return
    existing.append(incoming)


def _to_dict(m: Message | dict[str, Any]) -> dict[str, Any]:
    if isinstance(m, Message):
        d: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": __import__("json").dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in m.tool_calls
            ]
        if m.tool_call_id:
            d["tool_call_id"] = m.tool_call_id
        if m.name:
            d["name"] = m.name
        return d
    return dict(m)


def create_llm_client(settings: Settings | None = None) -> LLMClient:
    """工厂：按配置创建通道客户端；配置错误抛 ``LLMError``。"""
    return LLMClient(settings)


# 供异步 runner 使用的占位（同步 httpx；后续可换 AsyncClient）
AsyncLLMDelta = LLMDelta
AsyncIteratorLLM = AsyncIterator[LLMDelta]
