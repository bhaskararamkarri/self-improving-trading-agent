import re

# Simulate Claude Code logic:
# regex in binary: /\[1m\]/i.test(e)
model = "massive-context[1m]"
is_1m = bool(re.search(r'\[1m\]', model, re.IGNORECASE))
print(f"Model '{model}' has [1m]: {is_1m}")

model2 = "gemini-3.7-flash-tiered[1m]"
is_1m2 = bool(re.search(r'\[1m\]', model2, re.IGNORECASE))
print(f"Model '{model2}' has [1m]: {is_1m2}")
