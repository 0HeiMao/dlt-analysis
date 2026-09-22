"""端点集成测试脚本: 对 http://127.0.0.1:8765 依次执行全部验证.

全部输出写入 api_test_result.txt (UTF-8), 供逐项核对。
"""
import json
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8765"
RESULT = []

# 绕过系统代理: 本机回环请求不经过代理 (否则沙箱代理会返回 502).
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def log(s):
    RESULT.append(s)


def request(method, path, body=None, multipart=None, headers=None, head=False):
    url = BASE + path
    hdrs = dict(headers or {})
    data = None
    if multipart:
        boundary = "----dlttestboundary7d1a2c3"
        name, filename, content = multipart
        body_bytes = (
            (("--%s\r\n" % boundary).encode("utf-8"))
            + (("Content-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n" % filename).encode("utf-8"))
            + b"Content-Type: text/csv\r\n\r\n"
            + content
            + (("\r\n--%s--\r\n" % boundary).encode("utf-8"))
        )
        data = body_bytes
        hdrs["Content-Type"] = "multipart/form-data; boundary=%s" % boundary
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method="HEAD" if head else method, headers=hdrs)
    try:
        with OPENER.open(req, timeout=120) as resp:
            raw = resp.read()
            status = resp.status
            ctype = resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        raw = e.read()
        status = e.code
        ctype = e.headers.get("Content-Type", "") if e.headers else ""
    return status, raw, ctype


def parse_json(raw):
    try:
        return True, json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return False, "JSON 解析失败: %s" % exc


def check(tag, expect_status, status, raw, ctype):
    ok_json, payload = parse_json(raw) if "json" in ctype else (False, None)
    passed = (status == expect_status) and ok_json
    log("[%s] %s: HTTP %s (期望 %s) %s"
        % ("PASS" if passed else "FAIL", tag, status, expect_status,
           "JSON 可解析" if ok_json else ("非JSON(%s)" % ctype[:40])))
    return passed, payload


def main():
    log("=" * 76)
    log("dlt_tool Web 端点集成测试  http://127.0.0.1:8765")
    log("=" * 76)

    # 1. health (应显示无数据集)
    s, raw, ct = request("GET", "/api/health")
    ok, p = check("GET /api/health", 200, s, raw, ct)
    if ok:
        log("  status=%s version=%s dataset=%s"
            % (p["status"], p["version"], json.dumps(p["dataset"], ensure_ascii=False)))

    # 1b. 未载入数据集时 describe 应 409
    s, raw, ct = request("GET", "/api/describe?top_n=5")
    ok, p = check("GET /api/describe (未载入, 期望409)", 409, s, raw, ct)
    if ok:
        log("  detail=%s" % p["detail"])

    # 2. 载入内置模拟数据
    s, raw, ct = request("POST", "/api/dataset/sample")
    ok, p = check("POST /api/dataset/sample", 200, s, raw, ct)
    if ok:
        r = p["report"]
        log("  message=%s" % p["message"])
        log("  原始=%s 有效=%s 丢弃=%s warn=%s error=%s"
            % (r["original_rows"], r["valid_rows"], r["dropped_rows"],
               r["warning_count"], r["error_count"]))
        log("  preview 首行=%s" % json.dumps(p["preview"][0], ensure_ascii=False))

    # 3. describe
    s, raw, ct = request("GET", "/api/describe?top_n=5")
    ok, p = check("GET /api/describe", 200, s, raw, ct)
    if ok:
        st = p["statistics"]
        log("  total_issues=%s 前区35行=%s 后区12行=%s missing_front=%s"
            % (st["total_issues"], len(st["frequency_front"]),
               len(st["frequency_back"]), len(st["missing_front"])))
        log("  和值观测均值=%s 理论均值=%s" %
            (st["sum_distribution"]["observed_mean"], st["sum_distribution"]["theoretical_mean"]))
        log("  奇偶3:2观测=%s 理论=%s"
            % (st["odd_even"]["observed"]["3"], st["odd_even"]["theoretical"]["3"]))

    # 4. probability GET
    s, raw, ct = request("GET", "/api/probability")
    ok, p = check("GET /api/probability", 200, s, raw, ct)
    if ok:
        log("  总组合数=%s 一等奖概率=%s one_in=%s"
            % (p["combination_counts"]["total"],
               p["prizes"]["一等奖"]["probability"], p["prizes"]["一等奖"]["one_in"]))
        log("  自洽断言 passed=%s" % p["self_consistency"]["passed"])
        log("  返奖率(示例奖金)=%s" % p["expected_value"]["return_rate"])

    # 5. probability POST 自定义奖金 (一等奖 1000 万)
    custom = {"一等奖": 10000000.0, "二等奖": 200000.0, "三等奖": 15000.0, "四等奖": 3000.0,
              "五等奖": 300.0, "六等奖": 200.0, "七等奖": 100.0, "八等奖": 15.0, "九等奖": 5.0}
    s, raw, ct = request("POST", "/api/probability", body=custom)
    ok, p = check("POST /api/probability (一等奖1000万)", 200, s, raw, ct)
    if ok:
        ev = p["expected_value"]
        log("  毛回报=%s 返奖率=%s 净期望=%s"
            % (ev["gross_return_per_bet"], ev["return_rate"], ev["expected_value_per_bet"]))

    # 5b. probability POST 非法奖级 -> 400
    s, raw, ct = request("POST", "/api/probability", body={"特等奖": 100})
    ok, p = check("POST /api/probability (非法奖级, 期望400)", 400, s, raw, ct)
    if ok:
        log("  detail=%s" % p["detail"])

    # 6. randomness
    s, raw, ct = request("GET", "/api/randomness?mc_trials=20000&seed=20240920")
    ok, p = check("GET /api/randomness?mc_trials=20000", 200, s, raw, ct)
    if ok:
        r = p["result"]
        mc = r["monte_carlo"]
        log("  前区chi2=%s p=%s | 后区chi2=%s p=%s"
            % (r["chi2_front"]["chi2"], r["chi2_front"]["p_value"],
               r["chi2_back"]["chi2"], r["chi2_back"]["p_value"]))
        log("  FDR显著(前区)=%s 个 | MC块=%s 块x%s期 经验p前=%s"
            % (len(r["binomial_front"]["significant_indices"]), mc["blocks"],
               mc["block_size"], mc["empirical_p_value_front"]))
        log("  历史最大遗漏=%s 模拟均值=%s"
            % (mc["historical"]["front_max_missing"], mc["front_max_missing_distribution"]["mean"]))

    # 7. generate
    s, raw, ct = request("GET", "/api/generate?count=3&strategy=both&seed=20240920")
    ok, p = check("GET /api/generate?count=3&strategy=both", 200, s, raw, ct)
    if ok:
        r = p["result"]
        log("  hot_weighted 组数=%s balanced_profile 组数=%s"
            % (len(r["hot_weighted"]), len(r["balanced_profile"])))
        g = r["hot_weighted"][0]
        log("  第1组: 前区=%s 后区=%s 和值=%s 依据条数=%s"
            % (g["front"], g["back"], g["sum"], len(g["basis"])))

    # 8. 首页 HEAD
    s, raw, ct = request("HEAD", "/")
    log("[%s] HEAD / : HTTP %s (期望 200) Content-Type=%s"
        % ("PASS" if s == 200 else "FAIL", s, ct[:40]))

    # 9. 上传 dirty_demo.csv (预期 8 error / 3 warning)
    with open("../dirty_demo.csv", "rb") as fh:
        content = fh.read()
    s, raw, ct = request("POST", "/api/dataset/upload",
                         multipart=("file", "dirty_demo.csv", content))
    ok, p = check("POST /api/dataset/upload (dirty_demo.csv)", 200, s, raw, ct)
    if ok:
        r = p["report"]
        log("  message=%s" % p["message"])
        log("  原始=%s 有效=%s 丢弃=%s warning=%s error=%s"
            % (r["original_rows"], r["valid_rows"], r["dropped_rows"],
               r["warning_count"], r["error_count"]))
        log("  规则码计数=%s" % json.dumps(r["code_counts"], ensure_ascii=False))
        log("  [校验] error==8: %s ; warning==3: %s"
            % (r["error_count"] == 8, r["warning_count"] == 3))

    # 10. 上传后 health 应显示新数据集
    s, raw, ct = request("GET", "/api/health")
    ok, p = check("GET /api/health (上传后)", 200, s, raw, ct)
    if ok:
        log("  dataset=%s" % json.dumps(p["dataset"], ensure_ascii=False))

    # 11. 静态资源
    for path, tag in [("/index.html", "GET /index.html"), ("/app.js", "GET /app.js"),
                      ("/style.css", "GET /style.css")]:
        s, raw, ct = request("GET", path)
        log("[%s] %s: HTTP %s (期望 200) %s %sB"
            % ("PASS" if s == 200 else "FAIL", tag, s, ct.split(";")[0], len(raw)))

    log("=" * 76)
    fails = sum(1 for line in RESULT if line.startswith("[FAIL]"))
    log("总结: FAIL 数量 = %d %s" % (fails, "=> 全部通过" if fails == 0 else "=> 存在失败项!"))

    with open("api_test_result.txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(RESULT) + "\n")


if __name__ == "__main__":
    main()
