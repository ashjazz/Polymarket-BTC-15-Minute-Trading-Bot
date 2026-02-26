#!/usr/bin/env python3
"""
Fix market loading to avoid URL timeout
Changes range(-1, 97) to range(0, 3) to only load 3 markets at a time
"""

import re

bot_path = '/Users/jazzash/Data/Mfashion/Polymarket-BTC-15-Minute-Trading-Bot/bot.py'

with open(bot_path, 'r') as f:
    content = f.read()

# Fix 1: Change range(-1, 97) to range(0, 3)
old_pattern = r'for i in range\(-1, 97\):'
new_pattern = r'for i in range(0, 3):  # Current + next 2 only - avoid URL timeout'
content = re.sub(old_pattern, new_pattern, content)

# Fix 2: Change limit from 100 to 10
old_limit = '"limit": 100,'
new_limit = '"limit": 10,'
content = content.replace(old_limit, new_limit)

# Fix 3: Update comment
old_comment = 'Generate slugs for current + next 24 hours.'
new_comment = 'Load CURRENT + NEXT 2 markets only (avoid URL timeout)'
content = content.replace(old_comment, new_comment)

with open(bot_path, 'w') as f:
    f.write(content)

print("✅ Fixed market loading to only load 3 markets at a time")
print("   This will prevent URL timeout issues with Gamma API")
