#!/usr/bin/env python3
"""Regenerate the dashboard's static bugs.json snapshot.

Run this after any pipeline step (triage or verify-fix) changes the bugs
table, then redeploy the app — the public dashboard reads the baked-in
JSON file rather than querying the pod live (see fetch_bugs.py for why).
"""
from fetch_bugs import main

if __name__ == "__main__":
    main()
