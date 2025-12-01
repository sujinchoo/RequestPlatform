# ============================================================
# SaaS 데모 대시보드 (모바일 전용 요약)
# ============================================================
@app.route("/dashboard_demo")
@login_required
@admin_required
def dashboard_demo():

    # -----------------------------------------------
    # 1) 전체 개수
    # -----------------------------------------------
    total = Req.query.count()

    # 상태별 개수
    status_wait = Req.query.filter_by(status="모집중").count()
    status_pre = Req.query.filter_by(status="선탑진행중").count()
    status_interview = Req.query.filter_by(status="면접예정").count()
    status_done = Req.query.filter_by(status="배차완료").count()

    # 진행률
    progress_rate = round((status_done / total) * 100, 1) if total > 0 else 0

    # 비중
    total2 = status_wait + status_pre + status_interview + status_done or 1
    pct_wait = round((status_wait / total2) * 100, 1)
    pct_pre = round((status_pre / total2) * 100, 1)
    pct_interview = round((status_interview / total2) * 100, 1)
    pct_done = round((status_done / total2) * 100, 1)

    # -----------------------------------------------
    # 2) 최근 요청 5건
    # -----------------------------------------------
    recent = Req.query.order_by(Req.created_at.desc()).limit(5).all()

    # -----------------------------------------------
    # 3) ⭐ 지역별 개수 집계 (TOP 5 + 기타 + 라벨(숫자))
    # -----------------------------------------------
    raw_rows = (
        db.session.query(Req.region, db.func.count(Req.id))
        .group_by(Req.region)
        .all()
    )
    
    # dict 형태로 변환
    temp = { (r or "미기입"): int(cnt) for r, cnt in raw_rows }

    # 개수 순으로 정렬
    sorted_regions = sorted(temp.items(), key=lambda x: x[1], reverse=True)

    # Top 5
    top5 = sorted_regions[:5]

    # 나머지 합산 → 기타
    others_total = sum(cnt for _, cnt in sorted_regions[5:])
    if others_total > 0:
        top5.append(("기타", others_total))

    # 최종 dict: “지역명 (숫자)” → value는 숫자 그대로
    region_count = {}
    for region, cnt in top5:
        label = f"{region} ({cnt})"       # 라벨 + 숫자 표시
        region_count[label] = cnt         # value는 숫자 그대로 전달

    # -----------------------------------------------
    # 4) 월별 요청 수 집계 (Bar Chart)
    # -----------------------------------------------
    monthly_rows = (
        db.session.query(
            extract('year', Req.created_at).label("year"),
            extract('month', Req.created_at).label("month"),
            func.count(Req.id)
        )
        .group_by("year", "month")
        .order_by("year", "month")
        .all()
    )

    monthly_labels = []
    monthly_values = []
    
    for y, m, cnt in monthly_rows:
        monthly_labels.append(f"{int(y)}-{int(m):02d}")  # 2025-01
        monthly_values.append(int(cnt))

    # -----------------------------------------------
    # 5) 템플릿 전달
    # -----------------------------------------------
    return render_template(
        "dashboard_demo.html",
        total_cases=total,
        status_wait=status_wait,
        status_pre=status_pre,
        status_interview=status_interview,
        status_done=status_done,
        progress_rate=progress_rate,
        pct_wait=pct_wait,
        pct_pre=pct_pre,
        pct_interview=pct_interview,
        pct_done=pct_done,
        recent=recent,
        region_count=region_count,      # ← 라벨(숫자) 포함 + Top5 구조
        monthly_labels=monthly_labels,
        monthly_values=monthly_values
    )
