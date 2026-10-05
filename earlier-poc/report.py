"""Build a self-contained dashboard.html from results.json.   python report.py"""
import json

data = json.load(open("results.json"))
html = open("dashboard_template.html").read().replace("__DATA__", json.dumps(data).replace("</", "<\\/"))
open("dashboard.html", "w").write(html)
print("Wrote dashboard.html")
