#!/usr/bin/env python3
"""
Debug - Verificar issues no JSON com ID > 1281
"""

import json
from datetime import datetime
import re

# Carregar JSON
with open('gitlab_issues_raw.json', 'r', encoding='utf-8') as f:
    issues = json.load(f)

print("\n" + "="*70)
print("DEBUG - JSON ISSUES > 1281")
print("="*70)

def extract_module(title):
    """Extract module from title"""
    match = re.search(r'\[([^\]]+)\]', title)
    if match:
        return match.group(1).strip()
    return ''

def parse_date(date_str):
    """Parse GitLab date format"""
    if not date_str:
        return None
    try:
        clean = re.sub(r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s*', '', date_str)
        clean = re.sub(r'\s+GMT[+-]\d+', '', clean)
        return datetime.strptime(clean, '%B %d, %Y at %I:%M:%S %p')
    except:
        return None

# Filtrar issues > 1281
print(f"\n✓ Issues com ID > 1281:\n")

count = 0
for issue in issues:
    issue_id = int(issue.get('id', 0))
    if issue_id > 1281:
        title = issue.get('title', '')
        module = extract_module(title)
        created_date = parse_date(issue.get('createdDate', ''))

        print(f"ID: {issue_id:4d} | Módulo: {module:20s} | Data: {created_date.strftime('%d/%m/%Y') if created_date else 'N/A':10s}")
        print(f"         Título: {title[:70]}\n")
        count += 1

        if count >= 20:
            break

print(f"\nTotal de issues > 1281: {count}")
print("="*70)
