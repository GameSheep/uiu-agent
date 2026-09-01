---
name: say_hello
description: 用给定的语言问候某人。用于演示 skill 工作机制。
---

exec: echo

```tool_schema
{
  "type": "object",
  "properties": {"input": {"type": "string"}},
  "required": ["input"]
}
```