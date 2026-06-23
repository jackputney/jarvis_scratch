"""Platform adapter layer.

Thin, swappable boundaries between Jarvis's shared core and the few OS-specific
implementations (speech-to-text backend, audio I/O, system/app control, etc.).
Core code calls these adapters and never branches on ``platform.system()`` itself.

The package is named ``adapters`` (not ``platform``) on purpose: a top-level
``platform`` package would shadow the standard-library ``platform`` module that
much of the codebase imports.

See ``docs/PLATFORM.md`` for the full design and the planned adapter set.
"""
