"""
log_analyzer.py  -  API Health Log Analyzer
-------------------------------------------
Reads an API log file, calculates health metrics (success rate, error rate,
response times) for every endpoint, assigns a health status, and saves
the report as text, CSV and JSON.

Usage:
    python log_analyzer.py                       # analyzes api_health.log
    python log_analyzer.py --file mylog.log
    python log_analyzer.py --slow 800 --top 3
    python log_analyzer.py --chart               # also saves health_chart.png
    python log_analyzer.py --dashboard           # saves and opens dashboard.html
"""

import argparse
import csv
import json
import re
import statistics
from collections import Counter, defaultdict

# ---------- Configuration ----------
LOG_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2}) (?P<time>\d{2}:\d{2}:\d{2}) \| "
    r"(?P<method>[A-Z]+) \| (?P<endpoint>\S+) \| "
    r"(?P<status>\d{3}) \| (?P<rt>\d+)$"
)


# ---------- Step 1: Parse ----------
def parse_log(filename):
    """Read the file and return (list of valid entries, number of bad lines)."""
    entries, bad_lines = [], 0
    try:
        with open(filename) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                match = LOG_PATTERN.match(line)
                if match:
                    entries.append({
                        "hour": match["time"][:2],
                        "method": match["method"],
                        "endpoint": match["endpoint"],
                        "status": int(match["status"]),
                        "rt": int(match["rt"]),
                    })
                else:
                    bad_lines += 1
    except FileNotFoundError:
        print(f"Error: file '{filename}' not found. Run generate_logs.py first.")
        raise SystemExit(1)
    return entries, bad_lines


# ---------- Step 2: Calculate metrics ----------
def percentile(values, p):
    """Simple percentile (e.g. p=95) without external libraries."""
    ordered = sorted(values)
    index = max(0, int(round(p / 100 * len(ordered))) - 1)
    return ordered[index]


def health_status(error_rate, avg_rt):
    """Rule-based health classification."""
    if error_rate > 15 or avg_rt > 1500:
        return "CRITICAL"
    if error_rate > 5 or avg_rt > 600:
        return "DEGRADED"
    return "HEALTHY"


def analyze(entries):
    by_endpoint = defaultdict(list)
    for e in entries:
        by_endpoint[e["endpoint"]].append(e)

    results = []
    for endpoint, rows in by_endpoint.items():
        total = len(rows)
        times = [r["rt"] for r in rows]
        client_err = sum(1 for r in rows if 400 <= r["status"] < 500)
        server_err = sum(1 for r in rows if r["status"] >= 500)
        error_rate = (client_err + server_err) / total * 100
        avg_rt = statistics.mean(times)
        results.append({
            "endpoint": endpoint,
            "requests": total,
            "success_rate": round(100 - error_rate, 2),
            "error_rate": round(error_rate, 2),
            "4xx": client_err,
            "5xx": server_err,
            "avg_ms": round(avg_rt, 1),
            "min_ms": min(times),
            "max_ms": max(times),
            "p95_ms": percentile(times, 95),
            "status": health_status(error_rate, avg_rt),
        })
    return sorted(results, key=lambda r: r["error_rate"], reverse=True)


def overall_summary(entries):
    total = len(entries)
    errors = sum(1 for e in entries if e["status"] >= 400)
    times = [e["rt"] for e in entries]
    return {
        "total_requests": total,
        "total_errors": errors,
        "overall_error_rate": round(errors / total * 100, 2),
        "overall_success_rate": round(100 - errors / total * 100, 2),
        "avg_response_ms": round(statistics.mean(times), 1),
        "median_response_ms": statistics.median(times),
        "p95_response_ms": percentile(times, 95),
        "status_codes": dict(sorted(Counter(e["status"] for e in entries).items())),
        "errors_by_hour": dict(sorted(Counter(
            e["hour"] for e in entries if e["status"] >= 400).items())),
    }


# ---------- Step 3: Report ----------
def print_report(summary, results, bad_lines, slow_limit, top_n, entries):
    line = "=" * 78
    print(line)
    print("                     API HEALTH LOG ANALYSIS REPORT")
    print(line)
    print(f"Total requests     : {summary['total_requests']}")
    print(f"Success rate       : {summary['overall_success_rate']}%")
    print(f"Error rate         : {summary['overall_error_rate']}%")
    print(f"Avg response time  : {summary['avg_response_ms']} ms "
          f"(median {summary['median_response_ms']}, p95 {summary['p95_response_ms']})")
    print(f"Malformed lines    : {bad_lines}")

    print("\nStatus code distribution:")
    for code, count in summary["status_codes"].items():
        bar = "#" * int(count / summary["total_requests"] * 100)
        print(f"  {code}  {count:>5}  {bar}")

    print("\nPer-endpoint health:")
    print(f"  {'Endpoint':<16}{'Reqs':>6}{'Err%':>8}{'Avg ms':>9}{'P95 ms':>9}  Status")
    print("  " + "-" * 62)
    for r in results:
        print(f"  {r['endpoint']:<16}{r['requests']:>6}{r['error_rate']:>8}"
              f"{r['avg_ms']:>9}{r['p95_ms']:>9}  {r['status']}")

    print(f"\nTop {top_n} most error-prone endpoints:")
    for i, r in enumerate(results[:top_n], 1):
        print(f"  {i}. {r['endpoint']}  ({r['error_rate']}% errors)")

    slow = [e for e in entries if e["rt"] > slow_limit]
    print(f"\nSlow requests (> {slow_limit} ms): {len(slow)}")

    print("\nErrors by hour:")
    for hour, count in summary["errors_by_hour"].items():
        print(f"  {hour}:00  {count}")

    worst = [r for r in results if r["status"] != "HEALTHY"]
    print("\nALERTS:")
    if worst:
        for r in worst:
            print(f"  [{r['status']}] {r['endpoint']} - "
                  f"{r['error_rate']}% errors, avg {r['avg_ms']} ms")
    else:
        print("  All endpoints are healthy.")
    print(line)


def save_reports(summary, results):
    with open("report.json", "w") as f:
        json.dump({"summary": summary, "endpoints": results}, f, indent=4)
    with open("report.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)
    print("Saved: report.json, report.csv")


def save_chart(summary, results, filename="health_chart.png"):
    """Draw a 4-panel dashboard image (needs matplotlib: pip install matplotlib)."""
    try:
        import matplotlib
        matplotlib.use("Agg")          # draw to a file, no window needed
        import matplotlib.pyplot as plt
    except ImportError:
        print("Chart skipped: matplotlib is not installed (pip install matplotlib)")
        return

    colors = {"HEALTHY": "#2E9E6B", "DEGRADED": "#F2A541", "CRITICAL": "#D64545"}
    names = [r["endpoint"] for r in results][::-1]          # highest error on top
    bar_colors = [colors[r["status"]] for r in results][::-1]

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    fig.suptitle("API Health Dashboard", fontsize=16, fontweight="bold")

    # 1) error rate per endpoint, coloured by health status
    ax = axes[0][0]
    ax.barh(names, [r["error_rate"] for r in results][::-1], color=bar_colors)
    ax.axvline(5, color="gray", linestyle="--", linewidth=1)
    ax.axvline(15, color="gray", linestyle="--", linewidth=1)
    ax.set_title("Error rate by endpoint (%)")

    # 2) average response time per endpoint
    ax = axes[0][1]
    ax.barh(names, [r["avg_ms"] for r in results][::-1], color=bar_colors)
    ax.axvline(600, color="gray", linestyle="--", linewidth=1)
    ax.axvline(1500, color="gray", linestyle="--", linewidth=1)
    ax.set_title("Average response time (ms)")

    # 3) status code distribution
    ax = axes[1][0]
    codes = summary["status_codes"]
    code_colors = ["#2E9E6B" if c < 400 else "#F2A541" if c < 500 else "#D64545"
                   for c in codes]
    ax.bar([str(c) for c in codes], list(codes.values()), color=code_colors)
    ax.set_title("Status code distribution")

    # 4) errors by hour
    ax = axes[1][1]
    hours = summary["errors_by_hour"]
    ax.plot([h + ":00" for h in hours], list(hours.values()), marker="o", color="#0E9AA7")
    ax.set_title("Errors by hour")
    ax.set_ylim(bottom=0)
    ax.yaxis.get_major_locator().set_params(integer=True)   # whole numbers only

    for ax in axes.flat:
        ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(filename, dpi=150)
    plt.close(fig)
    print(f"Saved: {filename}")


DASHBOARD_CSS = """
body{font-family:Segoe UI,Arial,sans-serif;background:#F4F8FB;color:#0B1B2B;margin:0;padding:24px}
h1{margin:0 0 4px}h2{margin:0 0 10px;font-size:17px}.sub{color:#5B7C99;margin-bottom:20px}
.grid{display:grid;gap:16px}.kpis{grid-template-columns:repeat(auto-fit,minmax(180px,1fr))}
.two{grid-template-columns:repeat(auto-fit,minmax(340px,1fr));margin-top:16px}
.card,.kpi{background:#fff;border-radius:10px;padding:16px;box-shadow:0 1px 4px rgba(0,0,0,.1)}
.n{font-size:30px;font-weight:700;color:#0E9AA7}
.row{display:flex;align-items:center;gap:8px;margin:7px 0;font-size:14px}
.lbl{width:105px}.track{flex:1;background:#EAF2F7;border-radius:4px;height:16px}
.fill{height:100%;border-radius:4px}.val{width:72px;text-align:right}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{padding:8px;text-align:right;border-bottom:1px solid #E3EAF0}
th:first-child,td:first-child{text-align:left}
.b{padding:2px 10px;border-radius:10px;font-weight:600;font-size:12px}
.alert{margin:6px 0;font-size:14px}
"""


def save_dashboard(summary, results, filename="dashboard.html"):
    """Write a self-contained HTML dashboard. Open it in any web browser."""
    import os
    import webbrowser
    from html import escape

    col = {"HEALTHY": "#2E9E6B", "DEGRADED": "#F2A541", "CRITICAL": "#D64545"}
    ink = {"HEALTHY": "#fff", "DEGRADED": "#0B1B2B", "CRITICAL": "#fff"}

    def bars(items, colors, unit=""):
        top = max(v for _, v in items) or 1
        out = ""
        for (label, v), c in zip(items, colors):
            out += (f'<div class="row"><span class="lbl">{escape(str(label))}</span>'
                    f'<div class="track"><div class="fill" style="width:{v / top * 100:.1f}%;'
                    f'background:{c}"></div></div><span class="val">{v}{unit}</span></div>')
        return out

    s = summary
    kpis = [("Total requests", s["total_requests"]), ("Success rate", f'{s["overall_success_rate"]}%'),
            ("Error rate", f'{s["overall_error_rate"]}%'), ("Avg response", f'{s["avg_response_ms"]} ms')]
    kpi_html = "".join(f'<div class="kpi"><div class="n">{v}</div>{k}</div>' for k, v in kpis)

    status_colors = [col[r["status"]] for r in results]
    err_chart = bars([(r["endpoint"], r["error_rate"]) for r in results], status_colors, "%")
    rt_chart = bars([(r["endpoint"], r["avg_ms"]) for r in results], status_colors, " ms")
    codes = list(s["status_codes"].items())
    code_chart = bars(codes, ["#2E9E6B" if c < 400 else "#F2A541" if c < 500 else "#D64545"
                              for c, _ in codes])
    hours = list(s["errors_by_hour"].items())
    hour_chart = bars([(h + ":00", n) for h, n in hours], ["#0E9AA7"] * len(hours))

    rows = ""
    for r in results:
        rows += (f'<tr><td>{escape(r["endpoint"])}</td><td>{r["requests"]}</td><td>{r["error_rate"]}%</td>'
                 f'<td>{r["avg_ms"]}</td><td>{r["p95_ms"]}</td><td><span class="b" '
                 f'style="background:{col[r["status"]]};color:{ink[r["status"]]}">{r["status"]}</span></td></tr>')

    alerts = "".join(
        f'<div class="alert"><b style="color:{col[r["status"]]}">[{r["status"]}]</b> '
        f'{escape(r["endpoint"])} - {r["error_rate"]}% errors, avg {r["avg_ms"]} ms</div>'
        for r in results if r["status"] != "HEALTHY") or "<div>All endpoints are healthy.</div>"

    html = ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>API Health Dashboard</title><style>' + DASHBOARD_CSS + '</style></head><body>'
            '<h1>API Health Dashboard</h1><div class="sub">Generated by log_analyzer.py</div>'
            f'<div class="grid kpis">{kpi_html}</div>'
            f'<div class="card" style="margin-top:16px"><h2>Alerts</h2>{alerts}</div>'
            f'<div class="grid two"><div class="card"><h2>Error rate by endpoint</h2>{err_chart}</div>'
            f'<div class="card"><h2>Average response time</h2>{rt_chart}</div>'
            f'<div class="card"><h2>Status codes</h2>{code_chart}</div>'
            f'<div class="card"><h2>Errors by hour</h2>{hour_chart}</div></div>'
            '<div class="card" style="margin-top:16px"><h2>Endpoint health</h2><table><tr>'
            '<th>Endpoint</th><th>Requests</th><th>Error %</th><th>Avg ms</th><th>P95 ms</th><th>Status</th></tr>'
            f'{rows}</table></div></body></html>')

    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Saved: {filename}")
    try:
        webbrowser.open("file://" + os.path.abspath(filename))
    except Exception:
        pass


# ---------- Main ----------
def main():
    parser = argparse.ArgumentParser(description="API Health Log Analyzer")
    parser.add_argument("--file", default="api_health.log", help="log file path")
    parser.add_argument("--slow", type=int, default=1000, help="slow request limit (ms)")
    parser.add_argument("--top", type=int, default=3, help="how many top error endpoints")
    parser.add_argument("--chart", action="store_true", help="also save health_chart.png")
    parser.add_argument("--dashboard", action="store_true", help="save and open dashboard.html")
    args = parser.parse_args()

    entries, bad_lines = parse_log(args.file)
    if not entries:
        print("No valid log entries found.")
        return

    results = analyze(entries)
    summary = overall_summary(entries)
    print_report(summary, results, bad_lines, args.slow, args.top, entries)
    save_reports(summary, results)
    if args.chart:
        save_chart(summary, results)
    if args.dashboard:
        save_dashboard(summary, results)


if __name__ == "__main__":
    main()
