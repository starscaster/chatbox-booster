import re, ast
with open(r'I:\codex\CBB260701\app\plugins\search\quality_evaluator.py', 'rb') as f:
    data = bytearray(f.read())

# The corruption turned all these characters to wrong bytes:
# We need to fix line 213 specifically since it has the f-string issue
# Find full_query line and fix it
lines = data.split(b'\n')
for i, linetext in enumerate(lines):
    if b'full_query' in linetext:
        print(f'Line {i+1} before: {repr(linetext)}')
        # Replace corrupted patterns
        # Pattern 1: e9 8a 86 e5 80 87 -> e3 80 81 (f-string,、)
        linetext = linetext.replace(b'\xe9\x8a\x86\xe5\x80\x87', b'\xe3\x80\x81')
        # Pattern 2: e9 8a 86 3f -> e3 80 81 22 (strip,、"->、接")
        # Wait, 3f is '?' in ascii, but it's really the corrupted '"'
        # Let me check if 3f is at the right position
        # Original was: .strip("、") -> strip(" + 、 + ") 
        # After corruption: strip(" + weird_stuff + ?)
        # The ? is the corrupted closing quote
        idx = linetext.find(b'\xe9\x8a\x86')
        if idx >= 0:
            # Check what follows
            suffix = linetext[idx:idx+8]
            print(f'  Suffix at {idx}: {repr(suffix)}')
            if suffix == b'\xe9\x8a\x86\x3f':
                linetext = linetext[:idx] + b'\xe3\x80\x81\x22' + linetext[idx+4:]
            elif suffix[:6] == b'\xe9\x8a\x86\xe5\x80\x87\x3f':
                linetext = linetext[:idx] + b'\xe3\x80\x81\x3f' + linetext[idx+7:]
        
        print(f'Line {i+1} after:  {repr(linetext)}')
        lines[i] = linetext
        break

data = b'\n'.join(lines)
with open(r'I:\codex\CBB260701\app\plugins\search\quality_evaluator.py', 'wb') as f:
    f.write(data)

# Verify
with open(r'I:\codex\CBB260701\app\plugins\search\quality_evaluator.py', 'rb') as f:
    verify = f.read()
i = verify.find(b'full_query')
chunk = verify[i:i+55]
print(f'Final bytes: {repr(chunk)}')