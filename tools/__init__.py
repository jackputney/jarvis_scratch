"""tools — Jarvis tool implementations and registry.

Tools are Python functions dispatched by name through registry.py.
They are exposed to Claude via the native Anthropic tools= parameter and return
raw data; all formatting happens in the Claude reply.
"""
