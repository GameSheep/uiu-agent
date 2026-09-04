---
name: echo
description: 把用户传进来的字符串原样返回。示例 skill，演示怎么写一个最简 skill。
---

exec: echo

```tool_schema
{
  "type": "object",
  "properties": {"input": {"type": "string"}},
  "required": ["input"]
}
```