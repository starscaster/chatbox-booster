with open(r"I:\codex\CBB260701\app\plugins\search\quality_evaluator.py", "rb") as f:
    data = bytearray(f.read())

# The corruption: each occurrence of character 0x3001 (、"、"、) got corrupted by Set-Content
# Fix 1: e9 8a 86 e5 80 87 -> e3 80 81 (、 in the f-string)
# Fix 2: e9 8a 86 3f -> e3 80 81 22 (、" in .strip())

import re
pat1 = bytes([0xe9, 0x8a, 0x86, 0xe5, 0x80, 0x87])
rep1 = bytes([0xe3, 0x80, 0x81])  # 、
data = data.replace(pat1, rep1)

pat2 = bytes([0xe9, 0x8a, 0x86, 0x3f])
rep2 = bytes([0xe3, 0x80, 0x81, 0x22])  # 、"
data = data.replace(pat2, rep2)

with open(r"I:\codex\CBB260701\app\plugins\search\quality_evaluator.py", "wb") as f:
    f.write(data)

# Verify byte-level
with open(r"I:\codex\CBB260701\app\plugins\search\quality_evaluator.py", "rb") as f:
    verify = f.read()
idx = verify.find(b"full_query")
chunk = verify[idx:idx+55]
print(f"Fixed result: {repr(chunk)}")

# Verify syntax
import ast
with open(r"I:\codex\CBB260701\app\plugins\search\quality_evaluator.py", "r", encoding="utf-8") as f:
    ast.parse(f.read())
print("Syntax OK")
