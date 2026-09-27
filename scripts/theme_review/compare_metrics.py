"""Compare two in-page metrics runs (theme_screenshots.py --metrics) and report,
per metric, how many theme x mode combos pass before/after, plus every
regression (a combo that passed before and fails after, or a contrast that
dropped by more than 0.3). Usage: python scripts/theme_review/compare_metrics.py before.json after.json
"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

CONTRAST = {
    "dl_selected_min": 4.5, "dl_warning_min": 4.5, "dl_critical_min": 4.5, "dl_plain_min": 4.5,
    "share_name": 4.5, "rss_keyword": 4.5, "search_result_source": 4.5, "rss_error": 4.5,
    "field_note": 4.5, "status_line": 4.5, "drop_zone": 4.5, "scan_reasons": 4.5, "info_hint": 4.5,
    "profile_checkbox_label": 4.5, "modal_msg": 4.5, "tooltip": 4.5,
}


def ok(metric, v):
    if v is None or isinstance(v, str):
        return None
    if metric in CONTRAST:
        return v >= CONTRAST[metric]
    if metric == "dl_name_min_width":
        return v >= 40
    if metric == "form_select_mosaic":
        return v == 0
    if metric == "form_select_no_image":
        return v == 0
    if metric == "scan_visible_rows":
        return v >= 5
    if metric == "start_reachable":
        return bool(v)
    return None


def main(before_path, after_path):
    b = json.load(open(before_path, encoding="utf-8"))
    a = json.load(open(after_path, encoding="utf-8"))
    metrics = list(next(iter(next(iter(b.values())).values())).keys())
    print(f"{'metric':24s} {'pass before':>12s} {'pass after':>11s} {'regressions':>12s}")
    regressions = []
    still_failing = {}
    for m in metrics:
        pb = pa = n = 0
        for theme in b:
            for mode in b[theme]:
                vb = b[theme][mode].get(m)
                va = a.get(theme, {}).get(mode, {}).get(m)
                ob, oa = ok(m, vb), ok(m, va)
                if ob is None and oa is None:
                    continue
                n += 1
                pb += bool(ob)
                pa += bool(oa)
                if ob and oa is False:
                    regressions.append((m, theme, mode, vb, va))
                elif m in CONTRAST and isinstance(vb, (int, float)) and isinstance(va, (int, float)) and va < vb - 0.3:
                    regressions.append((m, theme, mode, vb, va))
                if oa is False:
                    still_failing.setdefault(m, []).append((theme, mode, va))
        nreg = sum(1 for r in regressions if r[0] == m)
        print(f"{m:24s} {pb:5d}/{n:<6d} {pa:5d}/{n:<5d} {nreg:12d}")
    print("\nREGRESSIONS (passed before and fails now, or contrast dropped > 0.3):")
    for r in regressions:
        print(f"  {r[0]:24s} {r[1]:20s} {r[2]:8s} {r[3]} -> {r[4]}")
    print("\nSTILL FAILING AFTER (worst first, per metric):")
    for m, rows in still_failing.items():
        rows = sorted(rows, key=lambda x: (x[2] if isinstance(x[2], (int, float)) else 0))
        shown = ", ".join(f"{t}/{md}={v}" for t, md, v in rows[:14])
        more = f" (+{len(rows) - 14})" if len(rows) > 14 else ""
        print(f"  {m:24s} {len(rows):3d}: {shown}{more}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
