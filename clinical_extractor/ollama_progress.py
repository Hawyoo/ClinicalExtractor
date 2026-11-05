"""Stream Ollama responses while retaining LangExtract's extraction/grounding."""
import json
import time
from langextract.providers.ollama import OllamaLanguageModel


class ProgressOllamaModel(OllamaLanguageModel):
    def set_progress(self, callback):
        self._progress = callback
        return self

    def _post_ollama_json(self, api_url, payload, request_timeout, num_threads, model):
        callback = self._progress
        callback('正在连接 Ollama，等待模型加载与提示词处理', model=model,
                 tokens=None, tokens_per_second=None, output_chars=0,
                 token_status='等待生成')
        started = time.monotonic()
        content, thinking = [], []
        last_update = 0
        final = None
        request_payload = {**payload, 'stream': True}
        # Model weights may stay loaded; previous requests' conversation state
        # must never be forwarded to another report.
        for key in ('context', 'history', 'conversation_id'):
            request_payload.pop(key, None)
        with self._requests.post(api_url, headers=self._request_headers(),
                                 json=request_payload, stream=True,
                                 timeout=request_timeout) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if chunk.get('error'):
                    raise RuntimeError(chunk['error'])
                message = chunk.get('message') or {}
                content.append(chunk.get('response') or message.get('content') or '')
                thinking.append(chunk.get('thinking') or message.get('thinking') or '')
                now = time.monotonic()
                if now - last_update >= 0.5:
                    callback('Ollama 正在生成结果', output_chars=sum(map(len, content)),
                             generation_seconds=round(now-started, 1),
                             token_status='生成中，等待 Ollama 返回 token 统计')
                    last_update = now
                if chunk.get('done'):
                    final = chunk
            if final is None:
                raise RuntimeError('Ollama 输出中断，未返回完成标记')
        count, duration = final.get('eval_count'), final.get('eval_duration')
        metrics = dict(output_chars=sum(map(len, content)))
        if isinstance(count, (int, float)) and duration and duration > 0:
            metrics.update(tokens=count, tokens_per_second=round(count * 1e9 / duration, 2),
                           token_status='Ollama 本次请求实际统计')
        else:
            metrics['token_status'] = 'Ollama 未提供 token 统计'
        callback('Ollama 已完成生成，正在校验原文证据', **metrics)
        if '/chat' in api_url:
            final['message'] = {'role': 'assistant', 'content': ''.join(content), 'thinking': ''.join(thinking)}
        else:
            final['response'] = ''.join(content)
            final['thinking'] = ''.join(thinking)
        return final
